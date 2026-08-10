from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.document_entity import DocumentEntity, DocumentVersionEntity
from core_api.modules.document.document_schema import DocumentCreate, DocumentRead, DocumentStatus, DocumentVersionRead
from core_api.modules.document.storage import DocumentStorage, LocalDocumentStorage
from core_api.modules.signature_request.signature_request_entity import AuditEventEntity, SignatureEntity, SignatureRequestEntity, SignerEntity
from core_api.modules.signature_request.workflow_schema import AuditEventRead, RequestStatus, SignatureRequestCreate, SignatureRequestRead, SignerCreate, SignerCreated, SignerRead, SignerStatus, SigningRead
from core_api.modules.signature_request.workflow_service import WorkflowError
from shared_kernel.time.datetime_service import DateTimeService


class DatabaseSignatureWorkflowService:
    def __init__(self, storage: DocumentStorage) -> None:
        self.storage = storage

    def create_document(self, payload: DocumentCreate, content: bytes) -> DocumentRead:
        if not content:
            raise WorkflowError("Document content cannot be empty")
        digest = sha256(content).hexdigest()
        key, size = self.storage.put(BytesIO(content), filename=payload.original_filename)
        try:
            with SessionLocal.begin() as db:
                item = DocumentEntity(**payload.model_dump(), storage_key=key, sha256=digest, version=1, status=DocumentStatus.READY.value)
                db.add(item)
                db.flush()
                db.add(DocumentVersionEntity(document_id=item.id, version=1, original_filename=item.original_filename, content_type=item.content_type, storage_key=key, sha256=digest, size_bytes=size, created_by=item.created_by))
                db.flush()
                self._audit(db, None, payload.created_by, "document.uploaded", "document", item.id, {"version": 1, "sha256": digest})
                result = self._document_read(item)
            return result
        except Exception:
            self.storage.delete(key)
            raise

    def add_version(self, document_id: str, *, filename: str, content_type: str, actor_id: str, content: bytes) -> DocumentRead:
        if not content:
            raise WorkflowError("Document content cannot be empty")
        key: str | None = None
        try:
            with SessionLocal.begin() as db:
                item = self._document(db, document_id, lock=True)
                frozen = db.scalar(select(SignatureRequestEntity.id).where(SignatureRequestEntity.document_id == item.id, SignatureRequestEntity.status.in_([RequestStatus.OPEN.value, RequestStatus.COMPLETED.value])).limit(1))
                if frozen is not None:
                    raise WorkflowError("A frozen document cannot receive a new version", 409)
                digest = sha256(content).hexdigest()
                key, size = self.storage.put(BytesIO(content), filename=filename)
                item.version += 1
                item.original_filename = filename
                item.content_type = content_type
                item.storage_key = key
                item.sha256 = digest
                db.add(DocumentVersionEntity(document_id=item.id, version=item.version, original_filename=filename, content_type=content_type, storage_key=key, sha256=digest, size_bytes=size, created_by=actor_id))
                db.flush()
                self._audit(db, None, actor_id, "document.version_created", "document", item.id, {"version": item.version, "sha256": digest})
                result = self._document_read(item)
            return result
        except Exception:
            if key:
                self.storage.delete(key)
            raise

    def list_documents(self) -> list[DocumentRead]:
        with SessionLocal() as db:
            return [self._document_read(item) for item in db.scalars(select(DocumentEntity).where(DocumentEntity.deleted_at.is_(None)).order_by(DocumentEntity.id)).all()]

    def get_document(self, document_id: str) -> DocumentRead:
        with SessionLocal() as db:
            return self._document_read(self._document(db, document_id))

    def get_content(self, document_id: str, version: int | None = None) -> tuple[DocumentVersionRead, bytes]:
        with SessionLocal() as db:
            document = self._document(db, document_id)
            item = db.scalar(select(DocumentVersionEntity).where(DocumentVersionEntity.document_id == document.id, DocumentVersionEntity.version == (version or document.version)))
            if item is None:
                raise WorkflowError("Document version not found", 404)
            metadata = self._version_read(item)
            storage_key = item.storage_key
        with self.storage.get(storage_key) as stream:
            content = stream.read()
        if sha256(content).hexdigest() != metadata.sha256:
            raise WorkflowError("Stored document integrity check failed", 409)
        return metadata, content

    def create_request(self, payload: SignatureRequestCreate) -> SignatureRequestRead:
        now = DateTimeService.utc_now()
        if payload.expires_at <= now:
            raise WorkflowError("Expiration must be in the future")
        with SessionLocal.begin() as db:
            document = self._document(db, payload.document_id)
            item = SignatureRequestEntity(document_id=document.id, document_version=document.version, document_sha256=document.sha256, status=RequestStatus.DRAFT.value, expires_at=payload.expires_at, created_by=payload.created_by)
            db.add(item)
            db.flush()
            self._audit(db, item.id, payload.created_by, "signature_request.created", "signature_request", item.id, {"document_version": document.version, "document_sha256": document.sha256})
            return self._request_read(db, item)

    def list_requests(self) -> list[SignatureRequestRead]:
        with SessionLocal() as db:
            return [self._request_read(db, item) for item in db.scalars(select(SignatureRequestEntity).where(SignatureRequestEntity.deleted_at.is_(None)).order_by(SignatureRequestEntity.id)).all()]

    def get_request(self, request_id: str) -> SignatureRequestRead:
        with SessionLocal() as db:
            return self._request_read(db, self._request(db, request_id))

    def add_signer(self, request_id: str, payload: SignerCreate, actor_id: str) -> SignerCreated:
        token = token_urlsafe(32)
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            if request.status != RequestStatus.DRAFT.value:
                raise WorkflowError("Signers can only be added to a draft request", 409)
            email = payload.email.lower()
            item = SignerEntity(signature_request_id=request.id, auth_user_id=email, name=payload.name, email=email, signing_token_hash=sha256(token.encode()).hexdigest(), token_expires_at=DateTimeService.utc_now() + timedelta(seconds=payload.token_ttl_seconds), status=SignerStatus.PENDING.value)
            db.add(item)
            try:
                db.flush()
            except IntegrityError as exc:
                raise WorkflowError("This authenticated user is already a signer", 409) from exc
            self._audit(db, request.id, actor_id, "signer.link_created", "signer", item.id, {"token_expires_at": item.token_expires_at.isoformat()})
            return SignerCreated(**self._signer_read(item).model_dump(), signing_url=self._signing_url(str(request.id)))

    def list_signers(self, request_id: str) -> list[SignerRead]:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            return [self._signer_read(item) for item in db.scalars(select(SignerEntity).where(SignerEntity.signature_request_id == request.id).order_by(SignerEntity.id)).all()]

    def revoke_signer_link(self, request_id: str, signer_id: str, actor_id: str) -> SignerRead:
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            signer = self._signer(db, signer_id, request.id, lock=True)
            if signer.status == SignerStatus.SIGNED.value:
                raise WorkflowError("A completed signature link cannot be revoked", 409)
            if signer.link_revoked_at is None:
                signer.link_revoked_at = DateTimeService.utc_now()
                self._audit(db, request.id, actor_id, "signer.link_revoked", "signer", signer.id, {})
            db.flush()
            return self._signer_read(signer)

    def open_request(self, request_id: str, actor_id: str) -> SignatureRequestRead:
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            if request.status != RequestStatus.DRAFT.value:
                raise WorkflowError("Only a draft request can be opened", 409)
            if not db.scalar(select(SignerEntity.id).where(SignerEntity.signature_request_id == request.id).limit(1)):
                raise WorkflowError("At least one signer is required", 409)
            document = self._document(db, str(request.document_id))
            if document.version != request.document_version or document.sha256 != request.document_sha256:
                raise WorkflowError("Document changed after request creation", 409)
            request.status = RequestStatus.OPEN.value
            self._audit(db, request.id, actor_id, "signature_request.opened", "signature_request", request.id, {})
            db.flush()
            return self._request_read(db, request)

    def cancel_request(self, request_id: str, actor_id: str) -> SignatureRequestRead:
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            if request.status not in {RequestStatus.DRAFT.value, RequestStatus.OPEN.value}:
                raise WorkflowError("Request cannot be cancelled", 409)
            request.status = RequestStatus.CANCELLED.value
            self._audit(db, request.id, actor_id, "signature_request.cancelled", "signature_request", request.id, {})
            db.flush()
            return self._request_read(db, request)

    def signing_context(self, request_id: str, auth_user_id: str) -> SigningRead:
        with SessionLocal() as db:
            signer, request = self._resolve_request(db, request_id, auth_user_id)
            document = self._document(db, str(request.document_id))
            return SigningRead(request=self._request_read(db, request), signer=self._signer_read(signer), document_title=document.title, original_filename=document.original_filename)

    def view(self, request_id: str, auth_user_id: str) -> SignerRead:
        with SessionLocal.begin() as db:
            signer, request = self._resolve_request(db, request_id, auth_user_id, lock=True)
            if signer.status == SignerStatus.PENDING.value:
                signer.status = SignerStatus.VIEWED.value
                self._audit(db, request.id, auth_user_id, "document.viewed", "signer", signer.id, {})
            db.flush()
            return self._signer_read(signer)

    def sign(self, request_id: str, auth_user_id: str, consent: bool) -> SignerRead:
        if not consent:
            raise WorkflowError("Explicit consent is required")
        with SessionLocal.begin() as db:
            signer, request = self._resolve_request(db, request_id, auth_user_id, lock=True)
            if signer.status == SignerStatus.SIGNED.value:
                raise WorkflowError("Signer has already signed", 409)
            version = db.scalar(select(DocumentVersionEntity).where(DocumentVersionEntity.document_id == request.document_id, DocumentVersionEntity.version == request.document_version))
            if version is None or version.sha256 != request.document_sha256:
                raise WorkflowError("Document hash does not match the frozen request", 409)
            with self.storage.get(version.storage_key) as stream:
                if sha256(stream.read()).hexdigest() != request.document_sha256:
                    raise WorkflowError("Document hash does not match the frozen request", 409)
            now = DateTimeService.utc_now()
            db.add(SignatureEntity(signature_request_id=request.id, signer_id=signer.id, auth_user_id=auth_user_id, document_sha256=request.document_sha256, signed_at=now, evidence_json={"consent": True, "document_version": request.document_version}))
            signer.status = SignerStatus.SIGNED.value
            signer.signed_at = now
            self._audit(db, request.id, auth_user_id, "signature.completed", "signer", signer.id, {"document_sha256": request.document_sha256, "document_version": request.document_version})
            db.flush()
            pending = db.scalar(select(func.count()).select_from(SignerEntity).where(SignerEntity.signature_request_id == request.id, SignerEntity.status != SignerStatus.SIGNED.value))
            if pending == 0:
                request.status = RequestStatus.COMPLETED.value
                request.completed_at = now
                self._audit(db, request.id, auth_user_id, "signature_request.completed", "signature_request", request.id, {})
            return self._signer_read(signer)

    def decline(self, request_id: str, auth_user_id: str) -> SignerRead:
        with SessionLocal.begin() as db:
            signer, request = self._resolve_request(db, request_id, auth_user_id, lock=True)
            if signer.status in {SignerStatus.SIGNED.value, SignerStatus.DECLINED.value}:
                raise WorkflowError("Signer already answered", 409)
            signer.status = SignerStatus.DECLINED.value
            self._audit(db, request.id, auth_user_id, "signature.declined", "signer", signer.id, {})
            db.flush()
            return self._signer_read(signer)

    def audit_events(self, request_id: str) -> list[AuditEventRead]:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            items = db.scalars(select(AuditEventEntity).where(AuditEventEntity.signature_request_id == request.id).order_by(AuditEventEntity.id)).all()
            return [AuditEventRead(id=str(x.id), occurred_at=x.occurred_at, actor_type=x.actor_type, actor_id=x.actor_id, action=x.action, entity_type=x.entity_type, entity_id=x.entity_id, correlation_id=x.correlation_id, metadata_sanitized=x.metadata_sanitized) for x in items]

    def _resolve_request(self, db, request_id: str, auth_user_id: str, lock: bool = False):
        request = self._request(db, request_id, lock=lock)
        statement = select(SignerEntity).where(SignerEntity.signature_request_id == request.id, SignerEntity.auth_user_id == auth_user_id.lower())
        signer = db.scalar(statement.with_for_update() if lock else statement)
        if signer is None:
            self._audit(db, request.id, auth_user_id, "authorization.failed", "signature_request", request.id, {})
            raise WorkflowError("Authenticated user does not match a signer for this request", 403)
        now = DateTimeService.utc_now()
        if signer.link_revoked_at is not None:
            raise WorkflowError("Signing access has been revoked", 410)
        if request.expires_at <= now:
            raise WorkflowError("Signature request has expired", 410)
        if request.status != RequestStatus.OPEN.value:
            raise WorkflowError("Signature request is not open", 409)
        return signer, request

    def _signer(self, db, identifier: str, request_id: int, lock: bool = False) -> SignerEntity:
        try:
            value = int(identifier)
        except ValueError as exc:
            raise WorkflowError("Signer not found", 404) from exc
        statement = select(SignerEntity).where(SignerEntity.id == value, SignerEntity.signature_request_id == request_id)
        item = db.scalar(statement.with_for_update() if lock else statement)
        if item is None:
            raise WorkflowError("Signer not found", 404)
        return item

    def _document(self, db, identifier: str, lock: bool = False) -> DocumentEntity:
        try:
            value = int(identifier)
        except ValueError as exc:
            raise WorkflowError("Document not found", 404) from exc
        statement = select(DocumentEntity).where(DocumentEntity.id == value, DocumentEntity.deleted_at.is_(None))
        item = db.scalar(statement.with_for_update() if lock else statement)
        if item is None:
            raise WorkflowError("Document not found", 404)
        return item

    def _request(self, db, identifier: str, lock: bool = False) -> SignatureRequestEntity:
        try:
            value = int(identifier)
        except ValueError as exc:
            raise WorkflowError("Signature request not found", 404) from exc
        statement = select(SignatureRequestEntity).where(SignatureRequestEntity.id == value, SignatureRequestEntity.deleted_at.is_(None))
        item = db.scalar(statement.with_for_update() if lock else statement)
        if item is None:
            raise WorkflowError("Signature request not found", 404)
        return item

    def _request_read(self, db, item: SignatureRequestEntity) -> SignatureRequestRead:
        signer_count = db.scalar(select(func.count()).select_from(SignerEntity).where(SignerEntity.signature_request_id == item.id)) or 0
        signed_count = db.scalar(select(func.count()).select_from(SignerEntity).where(SignerEntity.signature_request_id == item.id, SignerEntity.status == SignerStatus.SIGNED.value)) or 0
        return SignatureRequestRead(id=str(item.id), document_id=str(item.document_id), document_version=item.document_version, document_sha256=item.document_sha256, status=item.status, expires_at=item.expires_at, created_by=item.created_by, created_at=item.created_at, completed_at=item.completed_at, signer_count=signer_count, signed_count=signed_count, signing_url=self._signing_url(str(item.id)))

    @staticmethod
    def _document_read(x: DocumentEntity) -> DocumentRead:
        return DocumentRead(id=str(x.id), organization_id=x.organization_id, title=x.title, original_filename=x.original_filename, content_type=x.content_type, sha256=x.sha256, version=x.version, status=x.status, created_by=x.created_by, created_at=x.created_at, updated_at=x.updated_at)

    @staticmethod
    def _version_read(x: DocumentVersionEntity) -> DocumentVersionRead:
        return DocumentVersionRead(document_id=str(x.document_id), version=x.version, original_filename=x.original_filename, content_type=x.content_type, sha256=x.sha256, size_bytes=x.size_bytes, created_by=x.created_by, created_at=x.created_at)

    @staticmethod
    def _signer_read(x: SignerEntity) -> SignerRead:
        return SignerRead(id=str(x.id), signature_request_id=str(x.signature_request_id), auth_user_id=x.auth_user_id, name=x.name, email=x.email, status=x.status, token_expires_at=x.token_expires_at, link_revoked_at=x.link_revoked_at, signed_at=x.signed_at)

    @staticmethod
    def _signing_url(request_id: str) -> str:
        return f"{settings.SIGNING_APP_URL.rstrip('/')}/{request_id}"

    @staticmethod
    def _audit(db, request_id: int | None, actor_id: str, action: str, entity_type: str, entity_id: object, metadata: dict[str, object]) -> None:
        db.add(AuditEventEntity(signature_request_id=request_id, occurred_at=DateTimeService.utc_now(), actor_type="user", actor_id=actor_id, action=action, entity_type=entity_type, entity_id=str(entity_id), correlation_id=str(uuid4()), metadata_sanitized=metadata))


database_workflow_service = DatabaseSignatureWorkflowService(LocalDocumentStorage(Path(settings.DOCUMENT_STORAGE_PATH)))
