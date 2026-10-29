"""Fernet-based credential encryption for database connection secrets.

Key sourced from FERNET_KEY env var.  Falls back to deriving one from
JWT_SECRET for local development (never rely on this in production).
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet

_fernet_instance = None


def _get_key() -> bytes:
    raw = os.getenv("FERNET_KEY", "")
    if raw:
        return raw.encode()
    # Dev fallback – deterministic from JWT_SECRET
    from ..config import settings
    digest = hashlib.sha256(settings.JWT_SECRET.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _f() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = Fernet(_get_key())
    return _fernet_instance


def encrypt(plaintext: str) -> str:
    """Encrypt a string.  Returns URL-safe base64 ciphertext."""
    return _f().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt ciphertext back to plaintext."""
    return _f().decrypt(ciphertext.encode()).decode()
