"""Authentication API endpoints."""

import secrets

from fastapi import APIRouter, HTTPException, status

from src.config import get_settings
from src.auth.keycloak import (
    generate_pkce_pair,
    get_authorization_url,
    exchange_code_for_tokens,
    refresh_access_token,
    get_userinfo,
    get_or_create_user,
    OAuthError,
)
from src.api.v1.schemas import (
    LoginInitResponse,
    TokenCallbackRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserResponse,
)
from src.api.v1.dependencies import CurrentUser, DbSession

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()


@router.get("/status")
async def get_auth_status():
    """Return whether authentication is required.

    Used by the browser extension to skip login when auth is disabled.
    """
    return {"auth_enabled": settings.auth_enabled}


@router.get("/oidc-config")
async def get_oidc_config():
    """Return public OIDC configuration for browser-based auth flows.

    The browser extension uses this to discover where to send users
    for login without hardcoding Keycloak URLs.
    """
    return {
        "authorization_url": settings.oidc_authorization_url,
        "client_id": settings.keycloak_client_id,
        "scopes": "openid profile email",
    }


@router.get("/login", response_model=LoginInitResponse)
async def login_init(redirect_uri: str = ""):
    """Initialize OAuth2 PKCE login flow.

    Returns authorization URL, state, and code verifier.
    Client must store state and code_verifier for the callback.

    Args:
        redirect_uri: Client callback URL (provided by the browser extension)

    Returns:
        Authorization URL and PKCE parameters
    """
    # Generate PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Build authorization URL
    auth_url = get_authorization_url(state, code_challenge, redirect_uri)

    return LoginInitResponse(
        authorization_url=auth_url,
        state=state,
        code_verifier=code_verifier,
    )


@router.post("/callback", response_model=TokenResponse)
async def token_callback(request: TokenCallbackRequest, db: DbSession):
    """Exchange authorization code for tokens.

    Called after user completes Keycloak login and is redirected back.

    Args:
        request: Authorization code and PKCE verifier
        db: Database session

    Returns:
        Access and refresh tokens
    """
    try:
        # Exchange code for tokens
        token_response = await exchange_code_for_tokens(
            code=request.code,
            code_verifier=request.code_verifier,
            redirect_uri=request.redirect_uri,
        )

        # Get user info and create/update user in database
        access_token = token_response["access_token"]
        userinfo = await get_userinfo(access_token)
        await get_or_create_user(db, userinfo)

        return TokenResponse(
            access_token=token_response["access_token"],
            refresh_token=token_response.get("refresh_token", ""),
            token_type="Bearer",
            expires_in=token_response.get("expires_in", 3600),
        )

    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authentication failed: {e.description}",
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshTokenRequest):
    """Refresh an access token using a refresh token.

    Args:
        request: Refresh token

    Returns:
        New access and refresh tokens
    """
    try:
        token_response = await refresh_access_token(request.refresh_token)

        return TokenResponse(
            access_token=token_response["access_token"],
            refresh_token=token_response.get("refresh_token", request.refresh_token),
            token_type="Bearer",
            expires_in=token_response.get("expires_in", 3600),
        )

    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token refresh failed: {e.description}",
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(user: CurrentUser):
    """Get current authenticated user information.

    Args:
        user: Current authenticated user (from token)

    Returns:
        User information
    """
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        groups=user.groups,
        is_admin=user.is_admin,
    )


@router.post("/logout")
async def logout():
    """Logout current user.

    Note: Actual token revocation should be done client-side by
    discarding tokens. This endpoint is mainly for completeness.

    Returns:
        Success message
    """
    # In a more complete implementation, we would:
    # 1. Revoke the token at Keycloak
    # 2. Clear any server-side session data
    # For now, token management is client-side

    return {"message": "Logged out successfully"}
