# app/services/crypto.py — шифрование токенов для хранения в БД
"""Fernet symmetric encryption for tokens. Fallback to plaintext if key not configured."""
import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_FERNET = None


def _get_fernet(secret_key: Optional[str]) -> Optional["Fernet"]:
    global _FERNET
    if _FERNET is not None:
        return _FERNET
    if not secret_key or len(secret_key.strip()) < 16:
        return None
    try:
        from cryptography.fernet import Fernet
        # Fernet needs 32 bytes, base64url encoded. Derive from secret.
        h = hashlib.sha256(secret_key.strip().encode()).digest()
        key_b64 = base64.urlsafe_b64encode(h)
        _FERNET = Fernet(key_b64)
        return _FERNET
    except Exception as e:
        logger.warning("Fernet init failed: %s", e)
        return None


def encrypt_token(plain: str, secret_key: Optional[str]) -> str:
    """Шифрует токен. Если ключ не задан — возвращает как есть (legacy)."""
    f = _get_fernet(secret_key)
    if not f:
        return plain
    try:
        return f.encrypt(plain.encode()).decode()
    except Exception as e:
        logger.warning("Token encrypt failed: %s", e)
        return plain


def decrypt_token(cipher: str, secret_key: Optional[str]) -> str:
    """Расшифровывает токен. Если не зашифрован (legacy) — возвращает как есть."""
    if not cipher:
        return cipher
    f = _get_fernet(secret_key)
    if not f:
        return cipher
    try:
        return f.decrypt(cipher.encode()).decode()
    except Exception:
        # Вероятно plaintext (legacy)
        return cipher
