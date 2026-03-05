"""FastAPI dependencies for API endpoints."""

import logging
import re
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.db.session import get_db
from src.db.models import User
from src.auth.keycloak import verify_token, get_or_create_user, OAuthError

logger = logging.getLogger(__name__)

# Header names set by oauth2-proxy via Traefik forward-auth
PROXY_HEADER_USER = "X-Auth-Request-User"
PROXY_HEADER_EMAIL = "X-Auth-Request-Email"
PROXY_HEADER_GROUPS = "X-Auth-Request-Groups"

# Roles that grant admin access (same set as keycloak.py)
ADMIN_ROLES = {"ancroo-admin", "admin", "admin-users"}

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _derive_display_name(username: str, email: str) -> str:
    """Derive a human-readable display name.

    oauth2-proxy often forwards the Keycloak ``sub`` claim (a UUID)
    as X-Auth-Request-User.  When that happens, fall back to the
    local part of the email address instead.
    """
    if not _UUID_RE.match(username) and username:
        return username
    if email and "@" in email:
        return email.split("@")[0]
    return username


async def _get_dev_user(db: AsyncSession) -> User:
    """Get or create a local development user (auth disabled)."""
    result = await db.execute(
        select(User).where(User.external_id == "dev")
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            external_id="dev",
            email="dev@localhost",
            display_name="Developer",
            groups=[],
            is_admin=True,
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            # Race condition: another concurrent request created the user first
            await db.rollback()
            result = await db.execute(
                select(User).where(User.external_id == "dev")
            )
            user = result.scalar_one()

    return user


async def _get_proxy_user(request: Request, db: AsyncSession) -> User:
    """Resolve user from oauth2-proxy forward-auth headers.

    When Traefik's keycloak-forward-auth middleware validates the
    _oauth2_proxy session cookie, it sets X-Auth-Request-* headers
    on the forwarded request.
    """
    username = request.headers.get(PROXY_HEADER_USER)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Sign in to your Ancroo server first.",
        )

    email = request.headers.get(PROXY_HEADER_EMAIL, "")
    groups_raw = request.headers.get(PROXY_HEADER_GROUPS, "")
    groups = [g.strip() for g in groups_raw.split(",") if g.strip()]

    is_admin = bool(set(groups) & ADMIN_ROLES)

    result = await db.execute(
        select(User).where(User.external_id == username)
    )
    user = result.scalar_one_or_none()

    display = _derive_display_name(username, email)

    if user:
        user.email = email or user.email
        user.display_name = display
        user.groups = groups
        user.is_admin = is_admin
        user.last_login_at = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)
    else:
        user = User(
            external_id=username,
            email=email,
            display_name=display,
            groups=groups,
            is_admin=is_admin,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            # Race condition: another concurrent request created the user first
            await db.rollback()
            result = await db.execute(
                select(User).where(User.external_id == username)
            )
            user = result.scalar_one()
            return user

    await db.flush()
    logger.debug("Proxy auth resolved user: %s (admin=%s)", username, is_admin)
    return user


async def _get_bearer_user(request: Request, db: AsyncSession) -> User:
    """Resolve user from JWT Bearer token (extension PKCE flow).

    When the browser extension authenticates via PKCE, it sends an
    ``Authorization: Bearer <access_token>`` header.  The token is
    verified against Keycloak's JWKS and the user is synced to the DB.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    token = auth_header[7:]
    try:
        claims = await verify_token(token)
    except OAuthError as exc:
        logger.debug("Bearer token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim. Ensure the Keycloak client has the 'basic' scope.",
        )

    userinfo = {
        "sub": sub,
        "email": claims.get("email", ""),
        "preferred_username": claims.get("preferred_username", ""),
    }

    return await get_or_create_user(db, userinfo, access_token_claims=claims)


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve the current user.

    When auth_enabled=false (default), returns a local dev user.
    When auth_enabled=true, tries forward-auth headers first (browser
    via oauth2-proxy), then falls back to Bearer token (extension via
    PKCE).
    """
    settings = get_settings()

    if not settings.auth_enabled:
        return await _get_dev_user(db)

    # Forward-auth headers present → browser request via oauth2-proxy
    if request.headers.get(PROXY_HEADER_USER):
        return await _get_proxy_user(request, db)

    # Fall back to Bearer token → extension request via PKCE
    return await _get_bearer_user(request, db)


# Type aliases for cleaner dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
