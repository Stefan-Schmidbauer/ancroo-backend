"""Configuration settings for Ancroo Backend."""

from functools import lru_cache
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "Ancroo"
    debug: bool = False
    secret_key: str  # Required — set SECRET_KEY in environment
    ssl_verify: bool = True
    auth_enabled: bool = False  # Set to true to enable OIDC authentication

    # Database
    database_url: str = "postgresql+asyncpg://ancroo:ancroo@localhost:5432/ancroo"

    # External service URLs
    ollama_base_url: str = "http://ollama:11434"
    ollama_default_model: str = "mistral:7b"
    ollama_cuda_base_url: Optional[str] = None  # e.g. http://ollama-cuda:11434
    ollama_cuda_default_model: str = "mistral:7b"
    ollama_rocm_base_url: Optional[str] = None  # e.g. http://ollama-rocm:11434
    ollama_rocm_default_model: str = "mistral:7b"
    whisper_base_url: str = "http://speaches:8000"
    whisper_model: str = "Systran/faster-whisper-large-v3"
    whisper_rocm_base_url: Optional[str] = None  # e.g. http://whisper-rocm:8000
    whisper_rocm_model: str = "openai/whisper-large-v3-turbo"
    n8n_url: str = "http://n8n:5678"
    n8n_api_key: Optional[str] = None

    # Workflow settings
    workflow_timeout_seconds: int = 60
    ancroo_backends: str = "cuda"  # Comma-separated: "cuda", "rocm"

    @property
    def selected_backends(self) -> set[str]:
        """Parse ANCROO_BACKENDS into a set of backend identifiers."""
        return {b.strip().lower() for b in self.ancroo_backends.split(",") if b.strip()}

    # File upload settings
    max_upload_size_mb: int = 200
    upload_temp_dir: str = "/tmp/ancroo-uploads"

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000

    # Keycloak OIDC
    keycloak_client_id: str = "ancroo"
    keycloak_realm: str = "ancroo"
    oidc_issuer: str = "http://keycloak:8080/realms/ancroo"
    oidc_authorization_url: str = ""
    oidc_token_url: str = ""
    oidc_userinfo_url: str = ""
    oidc_jwks_url: str = ""
    oidc_logout_url: str = ""

    # CORS
    cors_origins: list[str] = ["chrome-extension://"]
    cors_extension_ids: list[str] = []  # Restrict to specific extension IDs; empty = allow all (dev mode)

    @model_validator(mode="after")
    def derive_oidc_urls(self) -> "Settings":
        """Auto-derive OIDC endpoint URLs from oidc_issuer if not explicitly set."""
        issuer = self.oidc_issuer.rstrip("/")
        oidc_base = f"{issuer}/protocol/openid-connect"
        if not self.oidc_authorization_url:
            self.oidc_authorization_url = f"{oidc_base}/auth"
        if not self.oidc_token_url:
            self.oidc_token_url = f"{oidc_base}/token"
        if not self.oidc_userinfo_url:
            self.oidc_userinfo_url = f"{oidc_base}/userinfo"
        if not self.oidc_jwks_url:
            self.oidc_jwks_url = f"{oidc_base}/certs"
        if not self.oidc_logout_url:
            self.oidc_logout_url = f"{oidc_base}/logout"
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
