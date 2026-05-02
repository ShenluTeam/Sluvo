from __future__ import annotations

import hashlib
from typing import Optional

from sqlmodel import Session, select

from models import ExternalProviderCredential
from schemas import EXTERNAL_PROVIDER_SHENLU_AGENT
from services.external_agent_crypto import decrypt_token


API_KEY_PREFIX_LENGTH = 16


def normalize_api_key(value: Optional[str]) -> str:
    return str(value or "").strip()


def build_api_key_hash(api_key: Optional[str]) -> Optional[str]:
    normalized = normalize_api_key(api_key)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_api_key_prefix(api_key: Optional[str]) -> Optional[str]:
    normalized = normalize_api_key(api_key)
    if not normalized:
        return None
    return normalized[:API_KEY_PREFIX_LENGTH]


def apply_api_key_fingerprint(credential: ExternalProviderCredential, api_key: Optional[str]) -> ExternalProviderCredential:
    credential.token_hash = build_api_key_hash(api_key)
    credential.token_prefix = build_api_key_prefix(api_key)
    return credential


def find_openclaw_credential_by_api_key(
    session: Session,
    *,
    api_key: str,
    provider: str = EXTERNAL_PROVIDER_SHENLU_AGENT,
) -> Optional[ExternalProviderCredential]:
    normalized = normalize_api_key(api_key)
    if not normalized:
        return None

    token_hash = build_api_key_hash(normalized)
    token_prefix = build_api_key_prefix(normalized)
    if token_hash and token_prefix:
        candidates = session.exec(
            select(ExternalProviderCredential).where(
                ExternalProviderCredential.provider == provider,
                ExternalProviderCredential.is_active == True,
                ExternalProviderCredential.token_prefix == token_prefix,
            )
        ).all()
        for credential in candidates:
            if credential.token_hash and credential.token_hash == token_hash:
                return credential

    prefix_candidates = []
    if token_prefix:
        prefix_candidates = session.exec(
            select(ExternalProviderCredential).where(
                ExternalProviderCredential.provider == provider,
                ExternalProviderCredential.is_active == True,
                ExternalProviderCredential.token_prefix == token_prefix,
            )
        ).all()

    for credential in prefix_candidates:
        try:
            if decrypt_token(credential.token_encrypted) == normalized:
                return credential
        except Exception:
            continue

    legacy_candidates = session.exec(
        select(ExternalProviderCredential).where(
            ExternalProviderCredential.provider == provider,
            ExternalProviderCredential.is_active == True,
        )
    ).all()
    for credential in legacy_candidates:
        try:
            if decrypt_token(credential.token_encrypted) == normalized:
                return credential
        except Exception:
            continue
    return None

