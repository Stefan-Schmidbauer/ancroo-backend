"""OAuth2/OIDC authentication with Keycloak."""

import secrets
import hashlib
import base64
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
import jwt
from jwt.exceptions import PyJWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.models import User

settings = get_settings()


class OAuthError(Exception):
    """OAuth authentication error."""

    def __init__(self, error: str, description: str = ""):
        self.error = error
        self.description = description
        super().__init__(f"{error}: {description}")


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge.

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def get_authorization_url(state: str, code_challenge: str, redirect_uri: str) -> str:
    """Build the Keycloak authorization URL.

    Args:
        state: Random state for CSRF protection
        code_challenge: PKCE code challenge
        redirect_uri: Client callback URL

    Returns:
        Full authorization URL
    """
    params = {
        "client_id": settings.keycloak_client_id,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{settings.oidc_authorization_url}?{query}"


async def exchange_code_for_tokens(
    code: str, code_verifier: str, redirect_uri: str
) -> dict:
    """Exchange authorization code for tokens.

    Args:
        code: Authorization code from callback
        code_verifier: PKCE code verifier
        redirect_uri: Same redirect URI used in authorization

    Returns:
        Token response containing access_token, refresh_token, id_token
    """
    async with httpx.AsyncClient(verify=settings.ssl_verify) as client:
        response = await client.post(
            settings.oidc_token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.keycloak_client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )

        if response.status_code != 200:
            error_data = response.json()
            raise OAuthError(
                error_data.get("error", "token_exchange_failed"),
                error_data.get("error_description", "Failed to exchange code for tokens"),
            )

        return response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Refresh an access token using the refresh token.

    Args:
        refresh_token: Valid refresh token

    Returns:
        New token response
    """
    async with httpx.AsyncClient(verify=settings.ssl_verify) as client:
        response = await client.post(
            settings.oidc_token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.keycloak_client_id,
                "refresh_token": refresh_token,
            },
        )

        if response.status_code != 200:
            error_data = response.json()
            raise OAuthError(
                error_data.get("error", "refresh_failed"),
                error_data.get("error_description", "Failed to refresh token"),
            )

        return response.json()


async def get_jwks() -> dict:
    """Fetch JWKS (JSON Web Key Set) from Keycloak.

    Returns:
        JWKS containing public keys for token verification
    """
    async with httpx.AsyncClient(verify=settings.ssl_verify) as client:
        response = await client.get(settings.oidc_jwks_url)
        response.raise_for_status()
        return response.json()


async def verify_token(token: str) -> dict:
    """Verify and decode a JWT token.

    Args:
        token: JWT access token or ID token

    Returns:
        Decoded token claims

    Raises:
        OAuthError: If token is invalid
    """
    try:
        jwks = await get_jwks()

        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        key = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = k
                break

        if not key:
            raise OAuthError("invalid_token", "No matching key found in JWKS")

        # Keycloak access tokens often set aud to "account" rather than
        # the client_id.  Skip audience verification here; the signature
        # and issuer check are sufficient for security.
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.oidc_issuer,
            options={"verify_aud": False},
        )

        return claims

    except PyJWTError as e:
        raise OAuthError("invalid_token", str(e))


async def get_userinfo(access_token: str) -> dict:
    """Fetch user info from Keycloak userinfo endpoint.

    Args:
        access_token: Valid access token

    Returns:
        User information claims
    """
    async with httpx.AsyncClient(verify=settings.ssl_verify) as client:
        response = await client.get(
            settings.oidc_userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if response.status_code != 200:
            raise OAuthError("userinfo_failed", "Failed to fetch user info")

        return response.json()


async def get_or_create_user(
    db: AsyncSession, userinfo: dict, access_token_claims: dict | None = None
) -> User:
    """Get existing user or create new one from OIDC userinfo.

    Args:
        db: Database session
        userinfo: User info from OIDC provider
        access_token_claims: Decoded access token claims (for role extraction)

    Returns:
        User instance
    """
    external_id = userinfo.get("sub")
    if not external_id:
        raise OAuthError("invalid_userinfo", "Missing 'sub' claim in userinfo")

    result = await db.execute(
        select(User).where(User.external_id == external_id)
    )
    user = result.scalar_one_or_none()

    # Extract groups + roles from Keycloak access token claims.
    # "groups" comes from the group-membership mapper (e.g. admin-users,
    # standard-users).  "realm_access.roles" are realm-level roles.
    # We merge both so WorkflowPermission can match on either.
    groups: list[str] = []
    if access_token_claims:
        groups = list(access_token_claims.get("groups", []))
        realm_access = access_token_claims.get("realm_access", {})
        for role in realm_access.get("roles", []):
            if role not in groups:
                groups.append(role)

    # Admin detection via Keycloak groups or realm roles
    admin_names = {"ancroo-admin", "admin", "admin-users"}
    is_admin = bool(set(groups) & admin_names)

    if user:
        user.email = userinfo.get("email", user.email)
        user.display_name = userinfo.get("preferred_username", user.display_name)
        user.groups = groups
        user.last_login_at = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)
        user.is_admin = is_admin
    else:
        user = User(
            external_id=external_id,
            email=userinfo.get("email", ""),
            display_name=userinfo.get("preferred_username"),
            groups=groups,
            is_admin=is_admin,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)

    await db.flush()
    return user


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> Optional[User]:
    """Get user by ID.

    Args:
        db: Database session
        user_id: User UUID

    Returns:
        User or None
    """
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
