"""Symmetric encryption for API keys stored in the database.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the ``cryptography`` package.
The encryption key is derived from the application's SECRET_KEY so no
additional environment variable is needed.

Encrypted values are stored with an ``enc:`` prefix. Plain-text legacy
values (without the prefix) are returned as-is on decrypt, enabling
transparent migration: old keys work immediately and get encrypted on
the next update.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from src.config import get_settings

_PREFIX = "enc:"


def _get_fernet() -> Fernet:
    """Derive a Fernet key from SECRET_KEY."""
    secret = get_settings().secret_key.encode()
    # SHA-256 produces 32 bytes; Fernet needs url-safe base64 of 32 bytes
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_api_key(plain: str) -> str:
    """Encrypt an API key for database storage.

    Returns a string prefixed with ``enc:``.
    Empty/None values are returned as-is.
    """
    if not plain:
        return plain
    token = _get_fernet().encrypt(plain.encode())
    return _PREFIX + token.decode()


def decrypt_api_key(stored: str) -> str:
    """Decrypt an API key retrieved from the database.

    If the value does not have the ``enc:`` prefix it is assumed to be
    a legacy plain-text key and returned unchanged.
    """
    if not stored:
        return stored
    if not stored.startswith(_PREFIX):
        return stored  # legacy plain-text
    try:
        return _get_fernet().decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        return stored  # fall back to raw value if decryption fails
