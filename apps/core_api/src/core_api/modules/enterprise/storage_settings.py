from hashlib import sha256
from pathlib import Path


def for_mode(settings, sandbox, namespace="isolated-v1"):
    if namespace not in {"legacy", "isolated-v1"}:
        raise ValueError("Unknown enterprise storage namespace")
    if not sandbox or namespace == "legacy":
        return settings
    return settings.model_copy(update={
        "DOCUMENT_STORAGE_PATH": str(Path(settings.DOCUMENT_STORAGE_PATH) / "enterprise-sandbox"),
        "R2_DOCUMENTS_PREFIX": f"{settings.R2_DOCUMENTS_PREFIX.strip('/')}/enterprise-sandbox".strip("/"),
        "DOCUMENT_STORAGE_ENCRYPTION_KEY": sha256(
            b"rubrica.enterprise.sandbox.root.v1\x00" + settings.DOCUMENT_STORAGE_ENCRYPTION_KEY.encode()).hexdigest(),
    })
