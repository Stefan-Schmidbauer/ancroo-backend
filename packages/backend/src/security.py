"""Shared security utilities."""

from urllib.parse import urlparse

from fastapi import HTTPException

# Blocked hostnames for SSRF protection (cloud metadata, loopback, link-local)
_SSRF_BLOCKED_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "100.100.100.200",
    "127.0.0.1",
    "0.0.0.0",
    "localhost",
    "::1",
}


def validate_provider_url(url: str) -> str:
    """Validate a provider base_url to prevent SSRF attacks.

    Raises HTTPException(400) if the URL is invalid or points to a blocked host.
    Returns the URL unchanged if valid.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Provider URL must use http:// or https://")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Provider URL must include a hostname")
    if parsed.hostname in _SSRF_BLOCKED_HOSTS:
        raise HTTPException(status_code=400, detail="Provider URL points to a blocked address")
    return url
