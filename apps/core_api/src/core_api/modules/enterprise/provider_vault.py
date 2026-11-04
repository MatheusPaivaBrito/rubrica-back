"""Per-tenant provider secrets with authenticated binding and purpose separation."""

from base64 import b64decode, b64encode
from hashlib import sha256
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from core_api.infrastructure.settings import settings


def associated_data(tenant_id, provider, sandbox, version):
    return json.dumps([str(tenant_id), provider, bool(sandbox), settings.ENVIRONMENT, version],
                      separators=(",", ":")).encode()


def cipher():
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b"rubrica.enterprise.provider-secrets.v1").derive(
                   sha256(settings.DOCUMENT_STORAGE_ENCRYPTION_KEY.encode()).digest())
    return AESGCM(key)


def encrypt_configuration(tenant_id, provider, sandbox, version, configuration):
    nonce = os.urandom(12)
    payload = json.dumps(configuration, separators=(",", ":")).encode()
    return b64encode(nonce + cipher().encrypt(nonce, payload,
        associated_data(tenant_id, provider, sandbox, version))).decode()


def decrypt_configuration(tenant_id, provider, sandbox, version, encrypted):
    raw = b64decode(encrypted, validate=True)
    return json.loads(cipher().decrypt(raw[:12], raw[12:],
        associated_data(tenant_id, provider, sandbox, version)))


def load_configuration(db, tenant_id, provider, sandbox, *, expected_version=None):
    from sqlalchemy import select
    from fastapi import HTTPException
    from core_api.modules.enterprise.entities import EnterpriseProvider
    item = db.scalar(select(EnterpriseProvider).where(
        EnterpriseProvider.tenant_id == tenant_id, EnterpriseProvider.provider == provider,
        EnterpriseProvider.sandbox == sandbox, EnterpriseProvider.deleted_at.is_(None),
    ))
    if item is None:
        raise HTTPException(409, "Tenant provider is not configured")
    if expected_version is not None and item.version != expected_version:
        raise HTTPException(409, "Provider configuration changed during signing")
    return decrypt_configuration(tenant_id, provider, sandbox, item.version, item.encrypted_configuration)
