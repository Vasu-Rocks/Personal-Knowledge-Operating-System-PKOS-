"""
Encryption for secrets stored in the database (users' cloud API keys).

Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from PKOS_SETTINGS_KEY, or PKOS_SECRET_KEY if that is
unset. The key never lives in the database, so a copied database alone does not reveal API keys.
If the secret changes, stored keys can no longer be decrypted: they read as "not set" and the user re-enters them.
"""
import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import base64

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def _fernet(material: str) -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"pkos llm settings v1").derive(material.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _material() -> str:
    from core.security import SECRET_KEY
    return os.getenv("PKOS_SETTINGS_KEY") or SECRET_KEY


def encrypt(plaintext: str) -> str:
    return _fernet(_material()).encrypt(plaintext.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet(_material()).decrypt(token.encode()).decode()
    except InvalidToken:
        logger.warning("A stored API key could not be decrypted (secret key changed?); treating it as not set.")
        return None


def hint(secret: str) -> str:
    """Shows the user which key is saved without revealing it: '…a1b2'."""
    return f"…{secret[-4:]}" if len(secret) > 8 else "…"
