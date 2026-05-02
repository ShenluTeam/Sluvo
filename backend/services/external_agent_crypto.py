from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet
from fastapi import HTTPException

from core.config import settings


def _build_fernet() -> Fernet:
    secret = (settings.EXTERNAL_PROVIDER_CREDENTIAL_SECRET or "").strip()
    if not secret:
        # Fall back to the app-level stable salt so token issuance still works
        # if the dedicated secret was not configured in an older deployment.
        secret = (settings.HASH_SALT or "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail="AI导演助理凭据加密密钥未配置")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(token: str) -> str:
    return _build_fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token_encrypted: str) -> str:
    return _build_fernet().decrypt(token_encrypted.encode("utf-8")).decode("utf-8")


def mask_token(token: str) -> str:
    raw = str(token or "").strip()
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:6]}***{raw[-4:]}"
