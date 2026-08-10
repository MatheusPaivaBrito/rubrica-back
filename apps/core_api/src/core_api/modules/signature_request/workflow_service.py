from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from secrets import token_urlsafe
from threading import RLock
from uuid import uuid4

from core_api.infrastructure.settings import settings
from core_api.modules.document.document_schema import (
    DocumentCreate,
    DocumentRead,
    DocumentStatus,
    DocumentVersionRead,
)
from core_api.modules.document.storage import DocumentStorage, LocalDocumentStorage
from core_api.modules.signature_request.workflow_schema import (
    AuditEventRead,
    RequestStatus,
    SignatureRequestCreate,
    SignatureRequestRead,
    SignerCreate,
    SignerRead,
    SignerStatus,
    SigningLinkRead,
    SigningRead,
)
from shared_kernel.time.datetime_service import DateTimeService


class WorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class StoredVersion:
    read: DocumentVersionRead
    storage_key: str


class SignatureWorkflowService:
    """Application workflow with an injectable object store.

    The lock makes state transitions atomic in the development backend. The ORM
    schema/migration supplies the equivalent uniqueness constraints in Postgres.
    """

    def __init__(self, storage: DocumentStorage) -> None:
        self.storage = storage
        self.documents: dict[str, DocumentRead] = {}
        self.versions: dict[str, list[StoredVersion]] = {}
        self.requests: dict[str, SignatureRequestRead] = {}
        self.signers: dict[str, SignerRead] = {}
        self.request_signers: dict[str, list[str]] = {}
        self.request_token_index: dict[str, str] = {}
        self.signatures: set[tuple[str, str]] = set()
        self.audit: dict[str, list[AuditEventRead]] = {}
        self._lock = RLock()

    def create_document(self, payload: DocumentCreate, content: bytes) -> DocumentRead:
        if not content:
            raise WorkflowError("Document content cannot be empty")
        now = DateTimeService.utc_now()
        document_id = str(uuid4())
        digest = sha256(content).hexdigest()
        key, size = self.storage.put(BytesIO(content), filename=payload.original_filename)
        item = DocumentRead(
            id=document_id, **payload.model_dump(), sha256=digest, version=1,
            status=DocumentStatus.READY, created_at=now, updated_at=now,
        )
        version = DocumentVersionRead(
            document_id=document_id, version=1, original_filename=payload.original_filename,
            content_type=payload.content_type, sha256=digest, size_bytes=size,
            created_by=payload.created_by, created_at=now,
        )
        with self._lock:
            self.documents[document_id] = item
            self.versions[document_id] = [StoredVersion(version, key)]
            self._audit(document_id, payload.created_by, "document.uploaded", "document", document_id, {"version": 1, "sha256": digest})
        return item

    def add_version(self, document_id: str, *, filename: str, content_type: str, actor_id: str, content: bytes) -> DocumentRead:
        if not content:
            raise WorkflowError("Document content cannot be empty")
        with self._lock:
            current = self._document(document_id)
            if any(r.document_id == document_id and r.status in {RequestStatus.OPEN, RequestStatus.COMPLETED} for r in self.requests.values()):
                raise WorkflowError("A frozen document cannot receive a new version", 409)
            now = DateTimeService.utc_now()
            number = current.version + 1
            digest = sha256(content).hexdigest()
            key, size = self.storage.put(BytesIO(content), filename=filename)
            version = DocumentVersionRead(document_id=document_id, version=number, original_filename=filename, content_type=content_type, sha256=digest, size_bytes=size, created_by=actor_id, created_at=now)
            updated = current.model_copy(update={"original_filename": filename, "content_type": content_type, "sha256": digest, "version": number, "updated_at": now})
            self.versions[document_id].append(StoredVersion(version, key))
            self.documents[document_id] = updated
            self._audit(document_id, actor_id, "document.version_created", "document", document_id, {"version": number, "sha256": digest})
            return updated

    def list_documents(self) -> list[DocumentRead]:
        return list(self.documents.values())

    def get_document(self, document_id: str) -> DocumentRead:
        return self._document(document_id)

    def delete_document(self, document_id: str, actor_id: str) -> None:
        with self._lock:
            self._document(document_id)
            if any(item.document_id == document_id and item.status in {RequestStatus.DRAFT, RequestStatus.OPEN, RequestStatus.COMPLETED} for item in self.requests.values()):
                raise WorkflowError("A document linked to an active signature request cannot be deleted", 409)
            del self.documents[document_id]
            self._audit(document_id, actor_id, "document.deleted", "document", document_id, {})

    def get_content(self, document_id: str, version: int | None = None) -> tuple[DocumentVersionRead, bytes]:
        current = self._document(document_id)
        target = version or current.version
        stored = next((item for item in self.versions[document_id] if item.read.version == target), None)
        if stored is None:
            raise WorkflowError("Document version not found", 404)
        with self.storage.get(stored.storage_key) as stream:
            content = stream.read()
        if sha256(content).hexdigest() != stored.read.sha256:
            raise WorkflowError("Stored document integrity check failed", 409)
        return stored.read, content

    def create_request(self, payload: SignatureRequestCreate) -> SignatureRequestRead:
        document = self._document(payload.document_id)
        now = DateTimeService.utc_now()
        if payload.expires_at <= now:
            raise WorkflowError("Expiration must be in the future")
        item = SignatureRequestRead(id=str(uuid4()), document_id=document.id, document_version=document.version, document_sha256=document.sha256, status=RequestStatus.DRAFT, expires_at=payload.expires_at, created_by=payload.created_by, created_at=now)
        with self._lock:
            self.requests[item.id] = item
            self.request_signers[item.id] = []
            self.audit[item.id] = []
            self._audit(item.id, payload.created_by, "signature_request.created", "signature_request", item.id, {"document_version": document.version, "document_sha256": document.sha256})
        return item

    def list_requests(self) -> list[SignatureRequestRead]:
        return [self._counts(item) for item in self.requests.values()]

    def get_request(self, request_id: str) -> SignatureRequestRead:
        return self._counts(self._request(request_id))

    def add_signer(self, request_id: str, payload: SignerCreate, actor_id: str) -> SignerRead:
        with self._lock:
            request = self._request(request_id)
            if request.status != RequestStatus.DRAFT:
                raise WorkflowError("Signers can only be added to a draft request", 409)
            email = payload.email.lower()
            if any(self.signers[sid].auth_user_id == email for sid in self.request_signers[request_id]):
                raise WorkflowError("This authenticated user is already a signer", 409)
            now = DateTimeService.utc_now()
            signer = SignerRead(id=str(uuid4()), signature_request_id=request_id, auth_user_id=email, name=payload.name, email=email, status=SignerStatus.PENDING, token_expires_at=now + timedelta(seconds=payload.token_ttl_seconds))
            self.signers[signer.id] = signer
            self.request_signers[request_id].append(signer.id)
            self._audit(request_id, actor_id, "signer.link_created", "signer", signer.id, {"token_expires_at": signer.token_expires_at.isoformat()})
            return signer

    def create_signing_link(self, request_id: str, actor_id: str) -> SigningLinkRead:
        with self._lock:
            request = self._request(request_id)
            if request.status != RequestStatus.OPEN:
                raise WorkflowError("Only an open request can receive a signing link", 409)
            token = token_urlsafe(32)
            self.request_token_index[sha256(token.encode()).hexdigest()] = request.id
            self._audit(request.id, actor_id, "signature_request.link_created", "signature_request", request.id, {})
            return SigningLinkRead(signing_url=self._signing_url(token))

    def list_signers(self, request_id: str) -> list[SignerRead]:
        self._request(request_id)
        return [self.signers[sid] for sid in self.request_signers[request_id]]

    def revoke_signer_link(self, request_id: str, signer_id: str, actor_id: str) -> SignerRead:
        with self._lock:
            request = self._request(request_id)
            try:
                signer = self.signers[signer_id]
            except KeyError as exc:
                raise WorkflowError("Signer not found", 404) from exc
            if signer.signature_request_id != request.id:
                raise WorkflowError("Signer not found", 404)
            if signer.status == SignerStatus.SIGNED:
                raise WorkflowError("A completed signature link cannot be revoked", 409)
            if signer.link_revoked_at is None:
                signer = signer.model_copy(update={"link_revoked_at": DateTimeService.utc_now()})
                self.signers[signer.id] = signer
                self._audit(request.id, actor_id, "signer.link_revoked", "signer", signer.id, {})
            return signer

    def open_request(self, request_id: str, actor_id: str) -> SignatureRequestRead:
        with self._lock:
            request = self._request(request_id)
            if request.status != RequestStatus.DRAFT:
                raise WorkflowError("Only a draft request can be opened", 409)
            if not self.request_signers[request_id]:
                raise WorkflowError("At least one signer is required", 409)
            document = self._document(request.document_id)
            if document.version != request.document_version or document.sha256 != request.document_sha256:
                raise WorkflowError("Document changed after request creation", 409)
            updated = request.model_copy(update={"status": RequestStatus.OPEN})
            self.requests[request_id] = updated
            self._audit(request_id, actor_id, "signature_request.opened", "signature_request", request_id, {})
            return self._counts(updated)

    def cancel_request(self, request_id: str, actor_id: str) -> SignatureRequestRead:
        with self._lock:
            request = self._request(request_id)
            if request.status not in {RequestStatus.DRAFT, RequestStatus.OPEN}:
                raise WorkflowError("Request cannot be cancelled", 409)
            updated = request.model_copy(update={"status": RequestStatus.CANCELLED})
            self.requests[request_id] = updated
            self._audit(request_id, actor_id, "signature_request.cancelled", "signature_request", request_id, {})
            return self._counts(updated)

    def signing_context(self, token: str, auth_user_id: str) -> SigningRead:
        signer, request = self._resolve_request(token, auth_user_id)
        document = self._document(request.document_id)
        return SigningRead(request=self._counts(request), signer=signer, document_title=document.title, original_filename=document.original_filename)

    def signing_document(self, token: str, auth_user_id: str) -> tuple[DocumentVersionRead, bytes]:
        _, request = self._resolve_request(token, auth_user_id)
        return self.get_content(request.document_id, request.document_version)

    def view(self, token: str, auth_user_id: str) -> SignerRead:
        with self._lock:
            signer, request = self._resolve_request(token, auth_user_id)
            if signer.status == SignerStatus.PENDING:
                signer = signer.model_copy(update={"status": SignerStatus.VIEWED})
                self.signers[signer.id] = signer
                self._audit(request.id, auth_user_id, "document.viewed", "signer", signer.id, {})
            return signer

    def sign(self, token: str, auth_user_id: str, consent: bool) -> SignerRead:
        if not consent:
            raise WorkflowError("Explicit consent is required")
        with self._lock:
            signer, request = self._resolve_request(token, auth_user_id)
            if signer.status == SignerStatus.SIGNED or (request.id, signer.id) in self.signatures:
                raise WorkflowError("Signer has already signed", 409)
            document = self._document(request.document_id)
            _, content = self.get_content(document.id, request.document_version)
            if sha256(content).hexdigest() != request.document_sha256:
                raise WorkflowError("Document hash does not match the frozen request", 409)
            now = DateTimeService.utc_now()
            signer = signer.model_copy(update={"status": SignerStatus.SIGNED, "signed_at": now})
            self.signatures.add((request.id, signer.id))
            self.signers[signer.id] = signer
            self._audit(request.id, auth_user_id, "signature.completed", "signer", signer.id, {"document_sha256": request.document_sha256, "document_version": request.document_version})
            if all(self.signers[sid].status == SignerStatus.SIGNED for sid in self.request_signers[request.id]):
                self.requests[request.id] = request.model_copy(update={"status": RequestStatus.COMPLETED, "completed_at": now})
                self._audit(request.id, auth_user_id, "signature_request.completed", "signature_request", request.id, {})
            return signer

    def decline(self, token: str, auth_user_id: str) -> SignerRead:
        with self._lock:
            signer, request = self._resolve_request(token, auth_user_id)
            if signer.status in {SignerStatus.SIGNED, SignerStatus.DECLINED}:
                raise WorkflowError("Signer already answered", 409)
            signer = signer.model_copy(update={"status": SignerStatus.DECLINED})
            self.signers[signer.id] = signer
            self._audit(request.id, auth_user_id, "signature.declined", "signer", signer.id, {})
            return signer

    def audit_events(self, request_id: str) -> list[AuditEventRead]:
        self._request(request_id)
        return list(self.audit[request_id])

    def _resolve_request(self, token: str, auth_user_id: str) -> tuple[SignerRead, SignatureRequestRead]:
        request_id = self.request_token_index.get(sha256(token.encode()).hexdigest())
        if request_id is None:
            raise WorkflowError("Signing link is invalid", 404)
        request = self._request(request_id)
        signer = next((item for item in self.list_signers(request.id) if item.auth_user_id == auth_user_id.lower()), None)
        if signer is None:
            self._audit(request.id, auth_user_id, "authorization.failed", "signature_request", request.id, {})
            raise WorkflowError("Authenticated user does not match a signer for this request", 403)
        now = DateTimeService.utc_now()
        if signer.link_revoked_at is not None:
            raise WorkflowError("Signing access has been revoked", 410)
        if request.expires_at <= now:
            if signer.status not in {SignerStatus.SIGNED, SignerStatus.DECLINED}:
                self.signers[signer.id] = signer.model_copy(update={"status": SignerStatus.EXPIRED})
            raise WorkflowError("Signature request has expired", 410)
        if request.status != RequestStatus.OPEN:
            raise WorkflowError("Signature request is not open", 409)
        return signer, request

    def _counts(self, request: SignatureRequestRead) -> SignatureRequestRead:
        signers = [self.signers[sid] for sid in self.request_signers.get(request.id, [])]
        return request.model_copy(update={"signer_count": len(signers), "signed_count": sum(s.status == SignerStatus.SIGNED for s in signers)})

    def _document(self, document_id: str) -> DocumentRead:
        try:
            return self.documents[document_id]
        except KeyError as exc:
            raise WorkflowError("Document not found", 404) from exc

    def _request(self, request_id: str) -> SignatureRequestRead:
        try:
            return self.requests[request_id]
        except KeyError as exc:
            raise WorkflowError("Signature request not found", 404) from exc

    def _audit(self, scope_id: str, actor_id: str, action: str, entity_type: str, entity_id: str, metadata: dict[str, object]) -> None:
        event = AuditEventRead(id=str(uuid4()), occurred_at=DateTimeService.utc_now(), actor_type="user", actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, correlation_id=str(uuid4()), metadata_sanitized=metadata)
        self.audit.setdefault(scope_id, []).append(event)

    @staticmethod
    def _signing_url(token: str) -> str:
        return f"{settings.SIGNING_APP_URL.rstrip('/')}/{token}"


workflow_service = SignatureWorkflowService(LocalDocumentStorage(Path(settings.DOCUMENT_STORAGE_PATH)))
