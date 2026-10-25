from __future__ import annotations

import logging
from datetime import datetime, timedelta
from hashlib import sha256
from hmac import new as hmac_new
from io import BytesIO
from secrets import token_urlsafe
from typing import Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_service import billing_service
from core_api.modules.document.document_entity import DocumentEntity, DocumentVersionEntity
from core_api.modules.document.document_schema import DocumentCreate, DocumentRead, DocumentStatus, DocumentVersionRead
from core_api.modules.document.pdf_validation import validate_pdf_upload
from core_api.modules.document.storage import (
    DocumentStorage,
    configured_document_storage,
    document_version_storage_scope,
    signed_artifact_storage_scope,
)
from core_api.modules.signature_request.signature_request_entity import AuditEventEntity, SignatureEntity, SignatureOperationEntity, SignatureRequestEntity, SignerEntity
from core_api.modules.signature_request.notification_client import send_signature_invitation
from core_api.modules.signature_request.identity_client import IdentitySummary, identity_summary
from core_api.modules.signature_request.signed_pdf import _stamp_locale_for_country, canonical_json, evidence_sha256, generate_signed_pdf
from core_api.modules.signature_request.workflow_schema import AuditEventRead, ClientEvidence, GeolocationEvidence, ParticipantRole, ReopenSignatureRequest, RequestStatus, SignatureEvidenceRead, SignatureMode, SignatureRequestCreate, SignatureRequestRead, SignerContactRead, SignerCreate, SignerRead, SignerStatus, SigningLinkRead, SigningRead, StampConfiguration, StampCustomization, StampPosition
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_service import tenant_service
from shared_kernel.time.datetime_service import DateTimeService


logger = logging.getLogger(__name__)


class DatabaseSignatureWorkflowService:
    def __init__(self, storage: DocumentStorage) -> None:
        self.storage = storage

    def create_document(self, payload: DocumentCreate, content: bytes) -> DocumentRead:
        if not content:
            raise WorkflowError("Document content cannot be empty")
        digest = sha256(content).hexdigest()
        document_id = uuid4()
        with SessionLocal() as db:
            tenant = db.scalar(
                select(TenantEntity).where(
                    TenantEntity.slug == payload.organization_id,
                    TenantEntity.deleted_at.is_(None),
                )
            )
            if tenant is None:
                raise WorkflowError("Tenant not found", 404)
            member = tenant_service.require_role(
                db, tenant.id, payload.created_by, {"admin", "member"}
            )
            tenant_id = tenant.id
            account_storage_id = self._account_storage_id(member, payload.created_by)
        key: str | None = None
        try:
            key, size = self.storage.put(
                BytesIO(content),
                filename=payload.original_filename,
                sha256=digest,
                scope=document_version_storage_scope(
                    tenant_id,
                    account_storage_id,
                    document_id,
                ),
            )
            with SessionLocal.begin() as db:
                tenant = db.scalar(
                    select(TenantEntity).where(
                        TenantEntity.id == tenant_id,
                        TenantEntity.slug == payload.organization_id,
                        TenantEntity.deleted_at.is_(None),
                    )
                )
                if tenant is None:
                    raise WorkflowError("Tenant not found", 404)
                tenant_service.require_role(
                    db, tenant.id, payload.created_by, {"admin", "member"}
                )
                billing_service.consume_document(db, tenant.id)
                item = DocumentEntity(id=document_id, **payload.model_dump(), tenant_id=tenant.id, storage_key=key, sha256=digest, version=1, status=DocumentStatus.READY.value)
                db.add(item)
                db.flush()
                db.add(DocumentVersionEntity(document_id=item.id, version=1, original_filename=item.original_filename, content_type=item.content_type, storage_key=key, sha256=digest, size_bytes=size, created_by=item.created_by))
                db.flush()
                self._audit(db, None, payload.created_by, "document.uploaded", "document", item.id, {"version": 1, "sha256": digest})
                result = self._document_read(db, item)
            return result
        except Exception:
            if key:
                self.storage.discard_uncommitted(key)
            raise

    def add_version(self, document_id: str, *, filename: str, content_type: str, actor_id: str, content: bytes) -> DocumentRead:
        if not content:
            raise WorkflowError("Document content cannot be empty")
        digest = sha256(content).hexdigest()
        with SessionLocal() as db:
            item = self._document(db, document_id)
            member = tenant_service.require_role(
                db, item.tenant_id, actor_id, {"admin", "member"}
            )
            frozen = db.scalar(select(SignatureRequestEntity.id).where(SignatureRequestEntity.document_id == item.id, SignatureRequestEntity.status.in_([RequestStatus.OPEN.value, RequestStatus.COMPLETED.value])).limit(1))
            if frozen is not None:
                raise WorkflowError("A frozen document cannot receive a new version", 409)
            expected_version = item.version
            tenant_id = item.tenant_id
            item_id = item.id
            account_storage_id = self._account_storage_id(member, actor_id)
        key: str | None = None
        try:
            key, size = self.storage.put(
                BytesIO(content), filename=filename, sha256=digest,
                scope=document_version_storage_scope(
                    tenant_id,
                    account_storage_id,
                    item_id,
                ),
            )
            with SessionLocal.begin() as db:
                item = self._document(db, document_id, lock=True)
                tenant_service.require_role(db, item.tenant_id, actor_id, {"admin", "member"})
                if item.version != expected_version:
                    raise WorkflowError("Document changed while the version was uploaded", 409)
                frozen = db.scalar(select(SignatureRequestEntity.id).where(SignatureRequestEntity.document_id == item.id, SignatureRequestEntity.status.in_([RequestStatus.OPEN.value, RequestStatus.COMPLETED.value])).limit(1))
                if frozen is not None:
                    raise WorkflowError("A frozen document cannot receive a new version", 409)
                item.version += 1
                item.original_filename = filename
                item.content_type = content_type
                item.storage_key = key
                item.sha256 = digest
                db.add(DocumentVersionEntity(document_id=item.id, version=item.version, original_filename=filename, content_type=content_type, storage_key=key, sha256=digest, size_bytes=size, created_by=actor_id))
                db.flush()
                self._audit(db, None, actor_id, "document.version_created", "document", item.id, {"version": item.version, "sha256": digest})
                result = self._document_read(db, item)
            return result
        except Exception:
            if key:
                self.storage.discard_uncommitted(key)
            raise

    def list_documents(self, actor_id: str) -> list[DocumentRead]:
        with SessionLocal() as db:
            normalized_actor = actor_id.lower()
            invited = select(SignerEntity.id).join(SignatureRequestEntity, SignatureRequestEntity.id == SignerEntity.signature_request_id).where(
                SignatureRequestEntity.document_id == DocumentEntity.id,
                SignatureRequestEntity.deleted_at.is_(None),
                or_(SignerEntity.auth_user_id == normalized_actor, SignerEntity.email == normalized_actor),
            ).exists()
            statement = select(DocumentEntity).join(TenantMemberEntity, TenantMemberEntity.tenant_id == DocumentEntity.tenant_id).where(
                DocumentEntity.deleted_at.is_(None), TenantMemberEntity.deleted_at.is_(None),
                TenantMemberEntity.status == "active", tenant_service.membership_identity_filter(actor_id),
                or_(TenantMemberEntity.role == "admin", func.lower(DocumentEntity.created_by) == normalized_actor, invited),
            ).order_by(DocumentEntity.created_at.desc(), DocumentEntity.id.desc())
            return [self._document_read(db, item) for item in db.scalars(statement).all() if not tenant_service.team_over_limit(db, item.tenant_id)]

    def get_document(self, document_id: str, actor_id: str) -> DocumentRead:
        with SessionLocal() as db:
            item = self._document(db, document_id)
            self._require_document_access(db, item, actor_id)
            return self._document_read(db, item)

    def delete_document(self, document_id: str, actor_id: str, *, force: bool = False) -> None:
        with SessionLocal.begin() as db:
            item = self._document(db, document_id, lock=True)
            tenant_service.require_role(db, item.tenant_id, actor_id, {"admin"})
            active_requests = list(db.scalars(select(SignatureRequestEntity).where(SignatureRequestEntity.document_id == item.id, SignatureRequestEntity.status.in_([RequestStatus.DRAFT.value, RequestStatus.OPEN.value])).with_for_update()).all())
            if active_requests and not force:
                raise WorkflowError(
                    "Document has signature requests in progress",
                    409,
                    code="document_has_active_requests",
                    context={"active_request_count": len(active_requests)},
                )
            for request in active_requests:
                request.status = RequestStatus.CANCELLED.value
                self._audit(db, request.id, actor_id, "signature_request.cancelled", "signature_request", request.id, {"reason": "document_deleted"})
            item.deleted_at = DateTimeService.utc_now()
            self._audit(db, None, actor_id, "document.deleted", "document", item.id, {"cancelled_request_count": len(active_requests)})

    def get_content(self, document_id: str, version: int | None = None, actor_id: str | None = None) -> tuple[DocumentVersionRead, bytes]:
        with SessionLocal() as db:
            document = self._document(db, document_id)
            if actor_id is not None:
                self._require_document_access(db, document, actor_id)
            item = db.scalar(select(DocumentVersionEntity).where(DocumentVersionEntity.document_id == document.id, DocumentVersionEntity.version == (version or document.version)))
            if item is None:
                raise WorkflowError("Document version not found", 404)
            metadata = self._version_read(item)
            storage_key = item.storage_key
        with self.storage.get(storage_key) as stream:
            content = stream.read()
        if sha256(content).hexdigest() != metadata.sha256:
            raise WorkflowError("Stored document integrity check failed", 409)
        validate_pdf_upload(content, filename=metadata.original_filename, content_type="application/pdf")
        return metadata, content

    def create_request(self, payload: SignatureRequestCreate) -> SignatureRequestRead:
        now = DateTimeService.utc_now()
        if payload.expires_at <= now:
            raise WorkflowError("Expiration must be in the future")
        with SessionLocal.begin() as db:
            document = self._document(db, payload.document_id)
            tenant_service.require_role(db, document.tenant_id, payload.created_by, {"admin", "member"})
            tenant = db.get(TenantEntity, document.tenant_id)
            if tenant is None or tenant.deleted_at is not None:
                raise WorkflowError("Tenant not found", 404)
            item = SignatureRequestEntity(
                document_id=document.id,
                document_version=document.version,
                document_sha256=document.sha256,
                status=RequestStatus.DRAFT.value,
                expires_at=payload.expires_at,
                created_by=payload.created_by,
                issuer_snapshot=tenant_service.issuer_snapshot(tenant),
            )
            db.add(item)
            db.flush()
            self._audit(db, item.id, payload.created_by, "signature_request.created", "signature_request", item.id, {"document_version": document.version, "document_sha256": document.sha256})
            return self._request_read(db, item)

    def reopen_request(
        self, request_id: str, actor_id: str, payload: ReopenSignatureRequest
    ) -> SignatureRequestRead:
        now = DateTimeService.utc_now()
        if payload.expires_at <= now:
            raise WorkflowError("Expiration must be in the future", 422)
        reason = payload.reason.strip()
        selected_ids = set(payload.pending_signer_ids)
        with SessionLocal() as db:
            parent = self._request(db, request_id)
            self._require_request_access(db, parent, actor_id)
            if parent.status != RequestStatus.OPEN.value or parent.expires_at > now:
                raise WorkflowError("Only an expired signature request can be reopened", 409)
            existing_child = db.scalar(select(SignatureRequestEntity).where(SignatureRequestEntity.parent_request_id == parent.id, SignatureRequestEntity.deleted_at.is_(None)))
            if existing_child is not None:
                return self._request_read(db, existing_child)
            pending = list(db.scalars(select(SignerEntity).where(
                SignerEntity.signature_request_id == parent.id,
                SignerEntity.id.in_(selected_ids) if selected_ids else False,
                SignerEntity.status != SignerStatus.SIGNED.value,
            )).all())
            if len(pending) != len(selected_ids):
                raise WorkflowError("A selected pending signer is not available", 422)
            current_signature_count = db.scalar(select(func.count()).select_from(SignatureEntity).where(SignatureEntity.signature_request_id == parent.id)) or 0
            latest_signature = db.scalar(select(SignatureEntity).where(
                SignatureEntity.signature_request_id == parent.id,
                SignatureEntity.artifact_storage_key.is_not(None),
            ).order_by(SignatureEntity.signed_at.desc(), SignatureEntity.id.desc()).limit(1))
            base_key = latest_signature.artifact_storage_key if latest_signature else parent.base_artifact_storage_key
            base_digest = latest_signature.artifact_sha256 if latest_signature else parent.base_artifact_sha256
            preserved_count = parent.preserved_signature_count + current_signature_count
            parent_snapshot = {
                "id": parent.id,
                "document_id": parent.document_id,
                "document_version": parent.document_version,
                "document_sha256": parent.document_sha256,
                "round_number": parent.round_number,
                "issuer_snapshot": parent.issuer_snapshot,
                "stamp_customization_snapshot": parent.stamp_customization_snapshot,
            }
            pending_snapshots = [
                {
                    "name": signer.name,
                    "email": signer.email,
                    "preferred_locale": signer.preferred_locale,
                    "participant_role": signer.participant_role,
                    "represented_tenant_id": signer.represented_tenant_id,
                    "representation_snapshot": signer.representation_snapshot,
                }
                for signer in pending
            ]
        if base_key and base_digest:
            with self.storage.get(base_key) as stream:
                if sha256(stream.read()).hexdigest() != base_digest:
                    raise WorkflowError("Previous signed artifact integrity check failed", 409)
        with SessionLocal.begin() as db:
            parent = self._request(db, request_id, lock=True)
            self._require_request_access(db, parent, actor_id)
            existing_child = db.scalar(select(SignatureRequestEntity).where(SignatureRequestEntity.parent_request_id == parent.id, SignatureRequestEntity.deleted_at.is_(None)))
            if existing_child is not None:
                return self._request_read(db, existing_child)
            if parent.status != RequestStatus.OPEN.value or parent.expires_at > DateTimeService.utc_now():
                raise WorkflowError("Signature request is no longer eligible for reopening", 409)
            if parent.document_id != parent_snapshot["document_id"] or parent.document_version != parent_snapshot["document_version"] or parent.document_sha256 != parent_snapshot["document_sha256"]:
                raise WorkflowError("Signature request changed during reopening", 409)
            item = SignatureRequestEntity(
                document_id=parent.document_id,
                document_version=parent.document_version,
                document_sha256=parent.document_sha256,
                status=RequestStatus.DRAFT.value,
                expires_at=payload.expires_at,
                created_by=actor_id,
                issuer_snapshot=parent_snapshot["issuer_snapshot"],
                stamp_customization_snapshot=parent_snapshot["stamp_customization_snapshot"],
                parent_request_id=parent.id,
                round_number=int(parent_snapshot["round_number"]) + 1,
                reopened_reason=reason,
                reopened_by=actor_id,
                reopened_at=now,
                base_artifact_storage_key=base_key,
                base_artifact_sha256=base_digest,
                preserved_signature_count=preserved_count,
            )
            db.add(item)
            db.flush()
            for snapshot in pending_snapshots:
                token = token_urlsafe(32)
                db.add(SignerEntity(
                    signature_request_id=item.id,
                    auth_user_id=str(snapshot["email"]).lower(),
                    name=snapshot["name"],
                    email=snapshot["email"],
                    preferred_locale=snapshot["preferred_locale"],
                    signing_token_hash=sha256(token.encode()).hexdigest(),
                    token_expires_at=payload.expires_at,
                    status=SignerStatus.PENDING.value,
                    participant_role=snapshot["participant_role"],
                    represented_tenant_id=snapshot["represented_tenant_id"],
                    representation_snapshot=snapshot["representation_snapshot"],
                ))
            self._audit(db, item.id, actor_id, "signature_request.reopened", "signature_request", item.id, {
                "parent_request_id": str(parent.id),
                "round_number": item.round_number,
                "preserved_signature_count": preserved_count,
                "pending_signer_count": len(pending_snapshots),
            })
            db.flush()
            return self._request_read(db, item)

    def list_requests(self, actor_id: str) -> list[SignatureRequestRead]:
        with SessionLocal() as db:
            normalized_actor = actor_id.lower()
            invited = select(SignerEntity.id).where(
                SignerEntity.signature_request_id == SignatureRequestEntity.id,
                or_(SignerEntity.auth_user_id == normalized_actor, SignerEntity.email == normalized_actor),
            ).exists()
            statement = select(SignatureRequestEntity).join(DocumentEntity, DocumentEntity.id == SignatureRequestEntity.document_id).join(TenantMemberEntity, TenantMemberEntity.tenant_id == DocumentEntity.tenant_id).where(
                SignatureRequestEntity.deleted_at.is_(None), DocumentEntity.deleted_at.is_(None),
                TenantMemberEntity.deleted_at.is_(None), TenantMemberEntity.status == "active",
                tenant_service.membership_identity_filter(actor_id),
                or_(TenantMemberEntity.role == "admin", func.lower(SignatureRequestEntity.created_by) == normalized_actor, invited),
            ).order_by(SignatureRequestEntity.created_at.desc(), SignatureRequestEntity.id.desc())
            return [self._request_read(db, item) for item in db.scalars(statement).all() if not tenant_service.team_over_limit(db, self._document(db, item.document_id).tenant_id)]

    def get_request(self, request_id: str, actor_id: str) -> SignatureRequestRead:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            self._require_request_access(db, request, actor_id)
            return self._request_read(db, request)

    def add_signer(self, request_id: str, payload: SignerCreate, actor_id: str) -> SignerRead:
        token = token_urlsafe(32)
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            self._require_request_access(db, request, actor_id)
            if request.status != RequestStatus.DRAFT.value:
                raise WorkflowError("Signers can only be added to a draft request", 409)
            email = payload.email.lower()
            representation_snapshot = None
            if payload.participant_role == ParticipantRole.CORPORATE_SEAL:
                raise WorkflowError("Corporate seal requires a configured organizational credential provider", 409)
            if payload.participant_role == ParticipantRole.COMPANY_REPRESENTATIVE:
                document = self._document(db, str(request.document_id))
                if payload.represented_tenant_id != document.tenant_id:
                    raise WorkflowError("The represented company must be the document tenant", 422)
                tenant = db.get(TenantEntity, document.tenant_id)
                if tenant is None or tenant.kind != "business":
                    raise WorkflowError("Company representation requires a business tenant", 409)
                if not billing_service.business_features_enabled(db, tenant.id):
                    raise WorkflowError("A Professional or Team plan is required for company representation", 403)
                member = db.scalar(
                    select(TenantMemberEntity).where(
                        TenantMemberEntity.tenant_id == tenant.id,
                        TenantMemberEntity.auth_user_id == email,
                        TenantMemberEntity.status == "active",
                        TenantMemberEntity.role.in_(["admin", "member"]),
                        TenantMemberEntity.deleted_at.is_(None),
                    )
                )
                if member is None:
                    raise WorkflowError("The representative must be an active authorized tenant member", 422)
                representation_snapshot = tenant_service.issuer_snapshot(tenant) | {
                    "representative_role": member.role,
                    "authorization_status": "active_membership",
                    "authorized_at": DateTimeService.utc_now().isoformat(),
                }
            item = SignerEntity(
                signature_request_id=request.id,
                auth_user_id=email,
                name=payload.name,
                email=email,
                preferred_locale=payload.preferred_locale,
                signing_token_hash=sha256(token.encode()).hexdigest(),
                token_expires_at=DateTimeService.utc_now() + timedelta(seconds=payload.token_ttl_seconds),
                status=SignerStatus.PENDING.value,
                participant_role=payload.participant_role.value,
                represented_tenant_id=payload.represented_tenant_id,
                representation_snapshot=representation_snapshot,
            )
            db.add(item)
            try:
                db.flush()
            except IntegrityError as exc:
                raise WorkflowError("This authenticated user is already a signer", 409) from exc
            self._audit(db, request.id, actor_id, "signer.link_created", "signer", item.id, {"token_expires_at": item.token_expires_at.isoformat()})
            return self._signer_read(item)

    def create_signing_link(self, request_id: str, actor_id: str) -> SigningLinkRead:
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            self._require_request_access(db, request, actor_id)
            if request.status not in {RequestStatus.OPEN.value, RequestStatus.COMPLETED.value}:
                raise WorkflowError("Only an open or completed request can receive a signing link", 409)
            if request.status == RequestStatus.OPEN.value and request.expires_at <= DateTimeService.utc_now():
                raise WorkflowError("Expired signature requests must be reopened before creating a signing link", 409)
            request.signing_token_nonce = token_urlsafe(24)
            token = self._request_token(request.id, request.signing_token_nonce)
            request.signing_token_hash = sha256(token.encode()).hexdigest()
            self._audit(db, request.id, actor_id, "signature_request.link_created", "signature_request", request.id, {})
            signing_url = self._signing_url(token)
            document = self._document(db, str(request.document_id))
            signers = db.scalars(
                select(SignerEntity).where(
                    SignerEntity.signature_request_id == request.id,
                    SignerEntity.status.in_([SignerStatus.PENDING.value, SignerStatus.VIEWED.value]),
                    SignerEntity.link_revoked_at.is_(None),
                )
            ).all()
            invitations = [
                (signer.email, signer.name, signer.preferred_locale, f"signature-invite:{request.id}:{signer.id}:{request.signing_token_nonce}")
                for signer in signers
            ]
            send_email = billing_service.email_invitations_enabled(
                db, document.tenant_id
            )
            document_title = document.title
        if send_email:
            for recipient, signer_name, locale, idempotency_key in invitations:
                send_signature_invitation(
                    recipient=recipient,
                    signer_name=signer_name,
                    document_title=document_title,
                    signing_url=signing_url,
                    locale=locale,
                    idempotency_key=idempotency_key,
                )
        return SigningLinkRead(signing_url=signing_url)

    def get_signing_link(self, request_id: str, actor_id: str) -> SigningLinkRead:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            self._require_request_access(db, request, actor_id)
            if not request.signing_token_nonce:
                raise WorkflowError("Signing link must be generated again", 404)
            token = self._request_token(request.id, request.signing_token_nonce)
            if sha256(token.encode()).hexdigest() != request.signing_token_hash:
                raise WorkflowError("Signing link integrity check failed", 409)
            return SigningLinkRead(signing_url=self._signing_url(token))

    def list_signers(self, request_id: str, actor_id: str) -> list[SignerRead]:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            self._require_request_access(db, request, actor_id)
            return [self._signer_read(item) for item in db.scalars(select(SignerEntity).where(SignerEntity.signature_request_id == request.id).order_by(SignerEntity.id)).all()]

    def invite_signer_account(self, request_id: str, signer_id: str, actor_id: str) -> bool:
        from core_api.modules.tenant.user_client import invite_signer_account
        with SessionLocal() as db:
            request = self._request(db, request_id)
            self._require_request_access(db, request, actor_id)
            if request.status != RequestStatus.DRAFT.value:
                raise WorkflowError("Signer accounts can only be invited while the request is a draft", 409)
            signer = db.get(SignerEntity, signer_id)
            if signer is None or signer.signature_request_id != request.id:
                raise WorkflowError("Signer not found", 404)
            if identity_summary(signer.email).identifier_type in {"BR_CPF", "BR_CNPJ"}:
                raise WorkflowError("Signer already has a Serpro ID eligible identity", 409)
            name, email, locale = signer.name, signer.email, signer.preferred_locale
        sent = invite_signer_account(name=name, email=email, locale=locale)
        if not sent:
            raise WorkflowError("This e-mail already belongs to an active Rubrica account", 409)
        return True

    def list_signer_contacts(self, tenant_id: UUID, actor_id: str, query: str = "") -> list[SignerContactRead]:
        search = query.strip().lower()
        with SessionLocal() as db:
            tenant_service.require_role(db, tenant_id, actor_id, {"admin", "member"})
            statement = select(SignerEntity).join(SignatureRequestEntity, SignatureRequestEntity.id == SignerEntity.signature_request_id).join(DocumentEntity, DocumentEntity.id == SignatureRequestEntity.document_id).where(DocumentEntity.tenant_id == tenant_id, SignerEntity.deleted_at.is_(None)).order_by(SignerEntity.created_at.desc())
            contacts: list[SignerContactRead] = []
            seen: set[str] = set()
            for signer in db.scalars(statement).all():
                email = signer.email.strip().lower()
                if email in seen or (search and search not in signer.name.lower() and search not in email):
                    continue
                seen.add(email)
                contacts.append(SignerContactRead(name=signer.name, email=email))
                if len(contacts) == 50:
                    break
            return contacts

    def stamp_configuration(self, request_id: str, actor_id: str) -> StampConfiguration:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            self._require_request_access(db, request, actor_id)
            default_customization, signer_customizations = self._stamp_customizations(request.stamp_customization_snapshot)
            return StampConfiguration(
                placements=request.stamp_placements or [],
                customization=default_customization,
                signer_customizations=signer_customizations,
                signer_signature_modes={item.id: item.signature_mode for item in db.scalars(select(SignerEntity).where(SignerEntity.signature_request_id == request.id)).all()},
            )

    def save_stamp_configuration(
        self, request_id: str, actor_id: str, payload: StampConfiguration
    ) -> StampConfiguration:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            self._require_request_access(db, request, actor_id)
            if request.status != RequestStatus.DRAFT.value:
                raise WorkflowError("Stamp configuration is frozen after opening", 409)
            document = self._document(db, str(request.document_id))
            document_id = document.id
            tenant_id = document.tenant_id
            version = request.document_version
            placement_enabled = billing_service.custom_stamp_placement_enabled(db, tenant_id)
        if payload.placements:
            if not placement_enabled:
                raise WorkflowError("Active paid plan required for custom stamp placement", 403)
            metadata, content = self.get_content(str(document_id), version, actor_id)
            del metadata
            from pypdf import PdfReader
            page_count = len(PdfReader(BytesIO(content)).pages)
        else:
            page_count = 0
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            self._require_request_access(db, request, actor_id)
            if request.status != RequestStatus.DRAFT.value:
                raise WorkflowError("Stamp configuration is frozen after opening", 409)
            signer_ids = set(db.scalars(select(SignerEntity.id).where(
                SignerEntity.signature_request_id == request.id
            )).all())
            if set(payload.signer_signature_modes) - signer_ids:
                raise WorkflowError("Every signature mode must belong to a request signer", 422)
            if set(payload.signer_customizations) - signer_ids:
                raise WorkflowError("Every stamp customization must belong to a request signer", 422)
            positions = sorted(payload.placements, key=lambda item: (item.order, item.page))
            for position in positions:
                if position.signer_id not in signer_ids:
                    raise WorkflowError("Every stamp position must belong to a request signer", 422)
                if position.page > page_count:
                    raise WorkflowError("Stamp position references a page that does not exist", 422)
            self._reject_overlapping_positions(positions)
            if payload.customization is not None and not billing_service.custom_stamp_branding_enabled(db, tenant_id):
                raise WorkflowError("Professional business plan with CNPJ required for stamp branding", 403)
            request.stamp_placements = [item.model_dump(mode="json") for item in positions] or None
            request.stamp_customization_snapshot = {
                "schema": "per-signer-v1",
                "default": payload.customization.model_dump(mode="json") if payload.customization else None,
                "by_signer": {str(key): value.model_dump(mode="json") for key, value in payload.signer_customizations.items()},
            } if payload.customization or payload.signer_customizations else None
            for signer in db.scalars(select(SignerEntity).where(SignerEntity.signature_request_id == request.id)).all():
                signer.signature_mode = payload.signer_signature_modes.get(signer.id, SignatureMode.SERPRO_TIMESTAMP.value)
            self._audit(db, request.id, actor_id, "signature_request.stamp_configuration_saved", "signature_request", request.id, {"position_count": len(positions), "customized": payload.customization is not None})
            return StampConfiguration(placements=positions, customization=payload.customization, signer_customizations=payload.signer_customizations, signer_signature_modes={item.id: item.signature_mode for item in db.scalars(select(SignerEntity).where(SignerEntity.signature_request_id == request.id)).all()})

    def tenant_stamp_customization(
        self, tenant_id: UUID, actor_id: str
    ) -> StampCustomization | None:
        with SessionLocal() as db:
            tenant_service.require_role(db, tenant_id, actor_id, {"admin"})
            tenant = db.get(TenantEntity, tenant_id)
            return StampCustomization(**tenant.stamp_customization) if tenant and tenant.stamp_customization else None

    def save_tenant_stamp_customization(
        self, tenant_id: UUID, actor_id: str, payload: StampCustomization
    ) -> StampCustomization:
        with SessionLocal.begin() as db:
            tenant_service.require_role(db, tenant_id, actor_id, {"admin"})
            if not billing_service.custom_stamp_branding_enabled(db, tenant_id):
                raise WorkflowError("Professional business plan with CNPJ required for stamp branding", 403)
            tenant = db.get(TenantEntity, tenant_id)
            if tenant is None:
                raise WorkflowError("Tenant not found", 404)
            tenant.stamp_customization = payload.model_dump(mode="json")
            self._audit(db, None, actor_id, "tenant.stamp_customization_saved", "tenant", tenant.id, {"template": payload.template, "show_logo": payload.show_logo, "require_drawn_signature": payload.require_drawn_signature})
            return payload

    @staticmethod
    def _reject_overlapping_positions(positions: list[StampPosition]) -> None:
        for index, left in enumerate(positions):
            for right in positions[index + 1:]:
                if left.page != right.page or left.signer_id == right.signer_id:
                    continue
                if abs(left.x - right.x) < (left.width + right.width) / 2 and abs(left.y - right.y) < (left.height + right.height) / 2:
                    raise WorkflowError("Stamp positions for different signers overlap", 422)

    def revoke_signer_link(self, request_id: str, signer_id: str, actor_id: str) -> SignerRead:
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            self._require_request_access(db, request, actor_id)
            signer = self._signer(db, signer_id, request.id, lock=True)
            if signer.status == SignerStatus.SIGNED.value:
                raise WorkflowError("A completed signature link cannot be revoked", 409)
            if signer.link_revoked_at is None:
                signer.link_revoked_at = DateTimeService.utc_now()
                self._audit(db, request.id, actor_id, "signer.link_revoked", "signer", signer.id, {})
            db.flush()
            return self._signer_read(signer)

    def open_request(self, request_id: str, actor_id: str, signature_mode: SignatureMode = SignatureMode.EVIDENCE) -> SignatureRequestRead:
        with SessionLocal() as db:
            snapshot = self._request(db, request_id)
            self._require_request_access(db, snapshot, actor_id)
            base_key = snapshot.base_artifact_storage_key
            base_digest = snapshot.base_artifact_sha256
        if bool(base_key) != bool(base_digest):
            raise WorkflowError("Signature round base artifact is incomplete", 409)
        if base_key and base_digest:
            with self.storage.get(base_key) as stream:
                if sha256(stream.read()).hexdigest() != base_digest:
                    raise WorkflowError("Signature round base artifact integrity check failed", 409)
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            self._require_request_access(db, request, actor_id)
            if request.status != RequestStatus.DRAFT.value:
                raise WorkflowError("Only a draft request can be opened", 409)
            if request.base_artifact_storage_key != base_key or request.base_artifact_sha256 != base_digest:
                raise WorkflowError("Signature round base artifact changed", 409)
            signers = db.scalars(select(SignerEntity).where(SignerEntity.signature_request_id == request.id)).all()
            if not signers:
                raise WorkflowError("At least one signer is required", 409)
            from core_api.modules.signature_request.serpro_timestamp_service import timestamp_enabled, timestamp_required
            if timestamp_required() and not timestamp_enabled():
                raise WorkflowError("SERPRO timestamp is not configured", 409)
            serproid_signers = [signer for signer in signers if signer.signature_mode == SignatureMode.SERPROID.value]
            if serproid_signers:
                if timestamp_required() and (not settings.SERPROID_CLIENT_ID or not settings.SERPROID_CLIENT_SECRET):
                    raise WorkflowError("Serpro ID is not configured", 409)
                if any(identity_summary(signer.email).identifier_type not in {"BR_CPF", "BR_CNPJ"} for signer in serproid_signers):
                    raise WorkflowError("Every Serpro ID signer must have a Brazilian CPF or CNPJ", 409)
            document = self._document(db, str(request.document_id))
            if request.stamp_placements and not billing_service.custom_stamp_placement_enabled(db, document.tenant_id):
                raise WorkflowError("Active paid plan required for custom stamp placement", 403)
            if request.stamp_customization_snapshot and not billing_service.custom_stamp_branding_enabled(db, document.tenant_id):
                raise WorkflowError("Professional business plan with CNPJ required for stamp branding", 403)
            if document.version != request.document_version or document.sha256 != request.document_sha256:
                raise WorkflowError("Document changed after request creation", 409)
            request.status = RequestStatus.OPEN.value
            request.opened_at = DateTimeService.utc_now()
            request.signature_mode = signature_mode.value
            self._audit(db, request.id, actor_id, "signature_request.opened", "signature_request", request.id, {"signature_mode": signature_mode.value})
            db.flush()
            return self._request_read(db, request)

    def cancel_request(self, request_id: str, actor_id: str) -> SignatureRequestRead:
        with SessionLocal.begin() as db:
            request = self._request(db, request_id, lock=True)
            self._require_request_access(db, request, actor_id)
            if request.status not in {RequestStatus.DRAFT.value, RequestStatus.OPEN.value}:
                raise WorkflowError("Request cannot be cancelled", 409)
            request.status = RequestStatus.CANCELLED.value
            self._audit(db, request.id, actor_id, "signature_request.cancelled", "signature_request", request.id, {})
            db.flush()
            return self._request_read(db, request)

    def signing_context(self, token: str, auth_user_id: str, *, administrator: bool = False) -> SigningRead:
        with SessionLocal() as db:
            request = self._request_from_token(db, token)
            authenticated_signer = db.scalar(
                select(SignerEntity).where(
                    SignerEntity.signature_request_id == request.id,
                    SignerEntity.auth_user_id == auth_user_id.lower(),
                )
            )
            administrative_view = administrator and authenticated_signer is None
            if administrative_view:
                self._require_request_access(db, request, auth_user_id)
                signer = db.scalar(
                    select(SignerEntity)
                    .where(SignerEntity.signature_request_id == request.id)
                    .order_by(SignerEntity.signed_at.desc().nulls_last(), SignerEntity.id)
                    .limit(1)
                )
                if signer is None:
                    raise WorkflowError("Signature request has no signers", 409)
            else:
                signer, request = self._resolve_request(db, token, auth_user_id, allow_completed=True)
            document = self._document(db, str(request.document_id))
            tenant = db.get(TenantEntity, document.tenant_id)
            signature = db.scalar(select(SignatureEntity).where(SignatureEntity.signature_request_id == request.id, SignatureEntity.signer_id == signer.id))
            stamp = None if administrative_view else signature.evidence_json.get("stamp") if signature is not None else None
            assigned_positions = [item for item in (request.stamp_placements or []) if str(item.get("signer_id")) == str(signer.id)]
            customization = self._signer_stamp_customization(request.stamp_customization_snapshot, signer.id)
            return SigningRead(request=self._request_read(db, request), signer=self._signer_read(signer), document_title=document.title, original_filename=document.original_filename, account_country=tenant.country_code if tenant else None, stamp=stamp, stamp_positions=assigned_positions, stamp_customization=customization, viewer_mode="administrator" if administrative_view else "signer", issuer_snapshot=request.issuer_snapshot)

    def signing_document(self, token: str, auth_user_id: str, *, administrator: bool = False) -> tuple[DocumentVersionRead, bytes]:
        with SessionLocal() as db:
            request = self._request_from_token(db, token) if administrator else self._resolve_request(db, token, auth_user_id, allow_completed=True)[1]
            if administrator:
                signer = db.scalar(select(SignerEntity).where(SignerEntity.signature_request_id == request.id, SignerEntity.auth_user_id == auth_user_id.lower()))
                if signer is None:
                    self._require_request_access(db, request, auth_user_id)
            version = db.scalar(select(DocumentVersionEntity).where(DocumentVersionEntity.document_id == request.document_id, DocumentVersionEntity.version == request.document_version))
            if version is None:
                raise WorkflowError("Document version not found", 404)
            metadata = self._version_read(version)
            storage_key = request.base_artifact_storage_key or version.storage_key
            expected_sha256 = request.base_artifact_sha256 or version.sha256
            if request.base_artifact_sha256:
                metadata = metadata.model_copy(update={"sha256": request.base_artifact_sha256})
        with self.storage.get(storage_key) as stream:
            content = stream.read()
        if sha256(content).hexdigest() != expected_sha256:
            raise WorkflowError("Stored document integrity check failed", 409)
        validate_pdf_upload(content, filename=metadata.original_filename, content_type="application/pdf")
        return metadata, content

    def view(self, token: str, auth_user_id: str) -> SignerRead:
        with SessionLocal.begin() as db:
            signer, request = self._resolve_request(db, token, auth_user_id, lock=True)
            if signer.status == SignerStatus.PENDING.value:
                signer.status = SignerStatus.VIEWED.value
                self._audit(db, request.id, auth_user_id, "document.viewed", "signer", signer.id, {})
            db.flush()
            return self._signer_read(signer)

    def sign(self, token: str, auth_user_id: str, consent: bool, stamp: StampPosition | None, *, consent_version: str = "rubrica-evidence-v2", client: ClientEvidence | None = None, geolocation: GeolocationEvidence | None = None, ip_address: str = "unknown", user_agent: str = "unknown", certificate_signer: Callable[[bytes], bytes] | None = None, certificate_info: dict[str, str] | None = None, drawn_signature_png_data_url: str | None = None) -> SignerRead:
        if not consent:
            raise WorkflowError("Explicit consent is required")
        signer_identity = identity_summary(auth_user_id)
        prepared = self._prepare_signature_operation(
            token,
            auth_user_id,
            stamp,
            consent_version=consent_version,
            client=client,
            geolocation=geolocation,
            ip_address=ip_address,
            user_agent=user_agent,
            certificate_required=certificate_signer is not None,
            certificate_info=certificate_info,
            signer_identity=signer_identity,
            drawn_signature_png_data_url=drawn_signature_png_data_url,
        )
        if isinstance(prepared, SignerRead):
            return prepared
        operation_id = prepared["operation_id"]
        if prepared["artifact_ready"]:
            return self._finalize_signature_operation(operation_id, auth_user_id)

        artifact_key: str | None = None
        artifact_recorded = False
        try:
            with self.storage.get(prepared["version_storage_key"]) as stream:
                original = stream.read()
            if sha256(original).hexdigest() != prepared["document_sha256"]:
                raise WorkflowError("Document hash does not match the frozen request", 409)
            validate_pdf_upload(
                original,
                filename=prepared["original_filename"],
                content_type="application/pdf",
            )
            artifact = generate_signed_pdf(
                original,
                stamps=prepared["stamp_records"][-1:],
                metadata=prepared["metadata"],
            )
            if certificate_signer is not None:
                artifact = certificate_signer(artifact)
            from core_api.modules.signature_request.serpro_timestamp_service import apply_serpro_timestamp, timestamp_required

            artifact, trusted_timestamp = apply_serpro_timestamp(artifact)
            if trusted_timestamp is None and timestamp_required():
                raise WorkflowError("SERPRO timestamp is required for every signature", 503)
            artifact_hash = sha256(artifact).hexdigest()
            artifact_key, _ = self.storage.put(
                BytesIO(artifact),
                filename=f"rubrica-{prepared['request_id']}-signed.pdf",
                sha256=artifact_hash,
                scope=prepared["artifact_scope"],
            )
            self._record_signature_artifact(
                operation_id,
                auth_user_id,
                artifact_key,
                artifact_hash,
                trusted_timestamp,
            )
            artifact_recorded = True
            return self._finalize_signature_operation(operation_id, auth_user_id)
        except Exception as exc:
            logger.exception(
                "Signature artifact processing failed",
                extra={
                    "signature_operation_id": str(operation_id),
                    "signature_request_id": str(prepared["request_id"]),
                },
            )
            if artifact_key and not artifact_recorded:
                self.storage.discard_uncommitted(artifact_key)
            self._fail_signature_operation(operation_id, exc)
            raise

    def _prepare_signature_operation(
        self,
        token: str,
        auth_user_id: str,
        stamp: StampPosition | None,
        *,
        consent_version: str,
        client: ClientEvidence | None,
        geolocation: GeolocationEvidence | None,
        ip_address: str,
        user_agent: str,
        certificate_required: bool,
        certificate_info: dict[str, str] | None,
        signer_identity: IdentitySummary,
        drawn_signature_png_data_url: str | None,
    ) -> SignerRead | dict[str, object]:
        now = DateTimeService.utc_now()
        with SessionLocal.begin() as db:
            signer, request = self._resolve_request(
                db, token, auth_user_id, lock=True, allow_completed=True
            )
            operation = db.scalar(
                select(SignatureOperationEntity)
                .where(
                    SignatureOperationEntity.signature_request_id == request.id,
                    SignatureOperationEntity.signer_id == signer.id,
                )
                .with_for_update()
            )
            if signer.status == SignerStatus.SIGNED.value:
                return self._signer_read(signer)
            if operation is not None and operation.status == "completed":
                return self._signer_read(signer)
            if operation is not None and operation.status == "artifact_ready":
                return {"operation_id": operation.id, "artifact_ready": True}
            if (
                operation is not None
                and operation.status == "processing"
                and operation.lease_expires_at is not None
                and operation.lease_expires_at > now
            ):
                raise WorkflowError(
                    "Signature processing is already in progress",
                    409,
                    code="signature_in_progress",
                )
            other_operation = db.scalar(
                select(SignatureOperationEntity.id)
                .where(
                    SignatureOperationEntity.signature_request_id == request.id,
                    SignatureOperationEntity.signer_id != signer.id,
                    SignatureOperationEntity.status.in_(["processing", "artifact_ready"]),
                )
                .limit(1)
            )
            if other_operation is not None:
                raise WorkflowError(
                    "Another signature for this request is still being processed",
                    409,
                    code="signature_request_busy",
                )
            if signer.signature_mode == SignatureMode.SERPROID.value and not certificate_required and settings.ENVIRONMENT.lower() == "production":
                raise WorkflowError("This request requires a Serpro ID certificate signature", 409)
            if signer.signature_mode != SignatureMode.SERPROID.value and certificate_required:
                raise WorkflowError("This request does not accept a Serpro ID certificate signature", 409)
            if certificate_required:
                if signer.status not in {SignerStatus.PENDING.value, SignerStatus.VIEWED.value}:
                    raise WorkflowError("Signer cannot authorize a certificate signature in the current state", 409)
            version = db.scalar(select(DocumentVersionEntity).where(DocumentVersionEntity.document_id == request.document_id, DocumentVersionEntity.version == request.document_version))
            if version is None or version.sha256 != request.document_sha256:
                raise WorkflowError("Document hash does not match the frozen request", 409)
            existing = list(db.scalars(
                select(SignatureEntity)
                .where(SignatureEntity.signature_request_id == request.id)
                .order_by(SignatureEntity.signed_at, SignatureEntity.id)
            ).all())
            latest_signature = existing[-1] if existing else None
            input_storage_key = (
                latest_signature.artifact_storage_key
                if latest_signature and latest_signature.artifact_storage_key
                else request.base_artifact_storage_key or version.storage_key
            )
            input_sha256 = (
                latest_signature.artifact_sha256
                if latest_signature and latest_signature.artifact_sha256
                else request.base_artifact_sha256 or version.sha256
            )
            document = db.get(DocumentEntity, request.document_id)
            if document is None or document.deleted_at is not None:
                raise WorkflowError("Document not found", 404)
            tenant = db.get(TenantEntity, document.tenant_id)
            configured_positions = [
                StampPosition(**item)
                for item in (request.stamp_placements or [])
                if str(item.get("signer_id")) == str(signer.id)
            ]
            if configured_positions:
                stamp = configured_positions[0]
            elif stamp is None:
                raise WorkflowError("A stamp position is required", 422)
            customization = self._signer_stamp_customization(request.stamp_customization_snapshot, signer.id)
            requires_drawing = any(position.display_variant == "drawn" for position in configured_positions)
            if (requires_drawing or (customization and customization.get("require_drawn_signature"))) and not drawn_signature_png_data_url:
                raise WorkflowError("A drawn signature is required for this request", 422)
            if signer.participant_role == ParticipantRole.COMPANY_REPRESENTATIVE.value:
                active_representation = db.scalar(
                    select(TenantMemberEntity.id).where(
                        TenantMemberEntity.tenant_id == signer.represented_tenant_id,
                        tenant_service.membership_identity_filter(auth_user_id),
                        TenantMemberEntity.status == "active",
                        TenantMemberEntity.role.in_(["admin", "member"]),
                        TenantMemberEntity.deleted_at.is_(None),
                    )
                )
                if active_representation is None:
                    raise WorkflowError("Company representation authorization is no longer active", 403)
            inherited = self._ancestor_signatures(db, request)
            if operation is None:
                evidence = self._signature_evidence(
                    request,
                    signer,
                    auth_user_id,
                    now,
                    stamp,
                    consent_version,
                    client,
                    geolocation,
                    ip_address,
                    user_agent,
                    signer_identity,
                    tenant.country_code if tenant is not None else None,
                    configured_positions or [stamp],
                    customization,
                    drawn_signature_png_data_url,
                )
                evidence["signature_mode"] = signer.signature_mode
                if certificate_info is not None:
                    evidence["certificate_signature"] = certificate_info
                evidence_hash = evidence_sha256(evidence)
                operation = SignatureOperationEntity(
                    signature_request_id=request.id,
                    signer_id=signer.id,
                    auth_user_id=auth_user_id.lower(),
                    status="processing",
                    document_version=request.document_version,
                    document_sha256=input_sha256,
                    expected_signature_count=len(existing),
                    attempt_count=1,
                    lease_expires_at=now + timedelta(minutes=5),
                    evidence_json=evidence,
                    evidence_sha256=evidence_hash,
                )
                db.add(operation)
                db.flush()
                self._audit(
                    db,
                    request.id,
                    auth_user_id,
                    "signature.operation_started",
                    "signature_operation",
                    operation.id,
                    {"attempt": 1},
                )
            else:
                if operation.document_version != request.document_version or operation.document_sha256 != input_sha256:
                    raise WorkflowError("Signature operation no longer matches the frozen document", 409)
                if operation.expected_signature_count != len(existing):
                    raise WorkflowError("Signature request changed while the operation was pending", 409)
                operation.status = "processing"
                operation.attempt_count += 1
                operation.lease_expires_at = now + timedelta(minutes=5)
                operation.error_code = None
                evidence = operation.evidence_json
                evidence_hash = operation.evidence_sha256
                self._audit(
                    db,
                    request.id,
                    auth_user_id,
                    "signature.operation_retried",
                    "signature_operation",
                    operation.id,
                    {"attempt": operation.attempt_count},
                )
            stamp_records = [item.evidence_json | {"evidence_sha256": item.evidence_sha256 or evidence_sha256(item.evidence_json)} for item in existing]
            stamp_records.append(evidence | {"evidence_sha256": evidence_hash})
            inherited_records = [item.evidence_json | {"evidence_sha256": item.evidence_sha256 or evidence_sha256(item.evidence_json)} for item in inherited]
            manifest_records = inherited_records + stamp_records
            manifest_hash = sha256("|".join(str(item["evidence_sha256"]) for item in manifest_records).encode()).hexdigest()
            signer_manifest = ";".join(f'{item["signer_name"]}|{item["signed_at"]}|{str(item["subject_hmac_sha256"])[:16]}' for item in manifest_records)
            metadata = {
                "RubricaArtifactId": str(operation.id),
                "RubricaRequestId": str(request.id),
                "RubricaDocumentId": str(request.document_id),
                "RubricaDocumentVersion": str(request.document_version),
                "RubricaOriginalSHA256": request.document_sha256,
                "RubricaEvidenceManifestSHA256": manifest_hash,
                "RubricaSignerManifest": signer_manifest,
                "RubricaIdentityBindingHMACSHA256": str(evidence["identity_binding_hmac_sha256"]),
                "RubricaLastSignedAt": str(evidence["signed_at"]),
                "RubricaEvidenceJSON": canonical_json(manifest_records).decode("utf-8"),
            }
            return {
                "operation_id": operation.id,
                "artifact_ready": False,
                "request_id": request.id,
                "document_sha256": input_sha256,
                "version_storage_key": input_storage_key,
                "original_filename": version.original_filename,
                "stamp_records": stamp_records,
                "metadata": metadata,
                "artifact_scope": signed_artifact_storage_scope(
                    document.tenant_id,
                    self._document_owner_storage_id(db, document),
                    document.id,
                ),
            }

    @staticmethod
    def _record_signature_artifact(
        operation_id: UUID,
        auth_user_id: str,
        artifact_key: str,
        artifact_hash: str,
        trusted_timestamp: dict[str, object] | None,
    ) -> None:
        with SessionLocal.begin() as db:
            operation = db.scalar(
                select(SignatureOperationEntity)
                .where(SignatureOperationEntity.id == operation_id)
                .with_for_update()
            )
            if operation is None or operation.auth_user_id != auth_user_id.lower():
                raise WorkflowError("Signature operation not found", 404)
            if operation.status != "processing":
                raise WorkflowError("Signature operation cannot accept an artifact", 409)
            operation.artifact_storage_key = artifact_key
            operation.artifact_sha256 = artifact_hash
            operation.trusted_timestamp_json = trusted_timestamp
            operation.status = "artifact_ready"
            operation.lease_expires_at = None
            operation.error_code = None

    def _finalize_signature_operation(
        self, operation_id: UUID, auth_user_id: str
    ) -> SignerRead:
        with SessionLocal.begin() as db:
            operation = db.scalar(
                select(SignatureOperationEntity)
                .where(SignatureOperationEntity.id == operation_id)
                .with_for_update()
            )
            if operation is None or operation.auth_user_id != auth_user_id.lower():
                raise WorkflowError("Signature operation not found", 404)
            request = self._request(db, str(operation.signature_request_id), lock=True)
            signer = self._signer(db, str(operation.signer_id), request.id, lock=True)
            if operation.status == "completed" and signer.status == SignerStatus.SIGNED.value:
                return self._signer_read(signer)
            from core_api.modules.signature_request.serpro_timestamp_service import timestamp_required

            if (
                operation.status != "artifact_ready"
                or not operation.artifact_storage_key
                or not operation.artifact_sha256
                or (timestamp_required() and operation.trusted_timestamp_json is None)
            ):
                raise WorkflowError("Signature operation artifact is not ready", 409)
            if request.status != RequestStatus.OPEN.value:
                raise WorkflowError("Signature request is not open", 409)
            if signer.status == SignerStatus.SIGNED.value:
                raise WorkflowError("Signer has already signed", 409)
            version = db.scalar(select(DocumentVersionEntity).where(DocumentVersionEntity.document_id == request.document_id, DocumentVersionEntity.version == operation.document_version))
            existing_signatures = list(db.scalars(
                select(SignatureEntity)
                .where(SignatureEntity.signature_request_id == request.id)
                .order_by(SignatureEntity.signed_at, SignatureEntity.id)
            ).all())
            latest_signature = existing_signatures[-1] if existing_signatures else None
            expected_input_sha256 = (
                latest_signature.artifact_sha256
                if latest_signature and latest_signature.artifact_sha256
                else request.base_artifact_sha256 or request.document_sha256
            )
            if version is None or version.sha256 != request.document_sha256 or operation.document_sha256 != expected_input_sha256:
                raise WorkflowError("Document changed before signature confirmation", 409)
            existing_count = len(existing_signatures)
            if existing_count != operation.expected_signature_count:
                raise WorkflowError("Signature request changed before confirmation", 409)
            document = db.get(DocumentEntity, request.document_id)
            if document is None or document.deleted_at is not None:
                raise WorkflowError("Document not found", 404)
            if signer.participant_role == ParticipantRole.COMPANY_REPRESENTATIVE.value:
                active_representation = db.scalar(
                    select(TenantMemberEntity.id).where(
                        TenantMemberEntity.tenant_id == signer.represented_tenant_id,
                        tenant_service.membership_identity_filter(auth_user_id),
                        TenantMemberEntity.status == "active",
                        TenantMemberEntity.role.in_(["admin", "member"]),
                        TenantMemberEntity.deleted_at.is_(None),
                    )
                )
                if active_representation is None:
                    raise WorkflowError("Company representation authorization is no longer active", 403)
            billing_service.consume_signature(db, document.tenant_id)
            signed_at = datetime.fromisoformat(str(operation.evidence_json["signed_at"]))
            db.add(
                SignatureEntity(
                    signature_request_id=request.id,
                    signer_id=signer.id,
                    auth_user_id=auth_user_id,
                    document_sha256=operation.document_sha256,
                    signed_at=signed_at,
                    evidence_json=operation.evidence_json,
                    evidence_sha256=operation.evidence_sha256,
                    artifact_storage_key=operation.artifact_storage_key,
                    artifact_sha256=operation.artifact_sha256,
                    trusted_timestamp_json=operation.trusted_timestamp_json,
                )
            )
            signer.status = SignerStatus.SIGNED.value
            signer.signed_at = signed_at
            operation.status = "completed"
            operation.completed_at = DateTimeService.utc_now()
            operation.error_code = None
            self._audit(db, request.id, auth_user_id, "signature.completed", "signer", signer.id, {"document_sha256": operation.document_sha256, "document_version": operation.document_version, "evidence_sha256": operation.evidence_sha256, "artifact_sha256": operation.artifact_sha256, "operation_id": str(operation.id)})
            db.flush()
            pending = db.scalar(select(func.count()).select_from(SignerEntity).where(SignerEntity.signature_request_id == request.id, SignerEntity.status != SignerStatus.SIGNED.value))
            if pending == 0:
                request.status = RequestStatus.COMPLETED.value
                request.completed_at = signed_at
                self._audit(db, request.id, auth_user_id, "signature_request.completed", "signature_request", request.id, {"artifact_sha256": operation.artifact_sha256})
            return self._signer_read(signer)

    @staticmethod
    def _fail_signature_operation(operation_id: UUID, error: Exception) -> None:
        error_code = (
            error.code
            if isinstance(error, WorkflowError) and error.code
            else "signature_processing_failed"
        )
        try:
            with SessionLocal.begin() as db:
                operation = db.scalar(
                    select(SignatureOperationEntity)
                    .where(SignatureOperationEntity.id == operation_id)
                    .with_for_update()
                )
                if operation is not None and operation.status == "processing":
                    operation.status = "failed"
                    operation.lease_expires_at = None
                    operation.error_code = error_code[:64]
        except Exception:
            return

    def signed_document(self, request_id: str, actor_id: str | None = None) -> tuple[str, str, bytes]:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            if actor_id is not None:
                self._require_request_access(db, request, actor_id)
            signature = db.scalar(select(SignatureEntity).where(SignatureEntity.signature_request_id == request.id, SignatureEntity.artifact_storage_key.is_not(None)).order_by(SignatureEntity.signed_at.desc(), SignatureEntity.id.desc()).limit(1))
            if signature is None or not signature.artifact_storage_key or not signature.artifact_sha256:
                raise WorkflowError("Signed document is not available", 404)
            key, digest = signature.artifact_storage_key, signature.artifact_sha256
        with self.storage.get(key) as stream:
            content = stream.read()
        if sha256(content).hexdigest() != digest:
            raise WorkflowError("Signed document integrity check failed", 409)
        return f"rubrica-request-{request_id}-signed.pdf", digest, content

    def signing_signed_document(self, token: str, auth_user_id: str, *, administrator: bool = False) -> tuple[str, str, bytes]:
        with SessionLocal() as db:
            if administrator:
                request = self._request_from_token(db, token)
                signer = db.scalar(select(SignerEntity).where(SignerEntity.signature_request_id == request.id, SignerEntity.auth_user_id == auth_user_id.lower()))
                if signer is None:
                    self._require_request_access(db, request, auth_user_id)
            else:
                _, request = self._resolve_request(db, token, auth_user_id, allow_completed=True)
            request_id = str(request.id)
        return self.signed_document(request_id)

    def signature_evidence(self, request_id: str, actor_id: str) -> list[SignatureEvidenceRead]:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            self._require_request_access(db, request, actor_id)
            rows = db.execute(select(SignatureEntity, SignerEntity).join(SignerEntity, SignerEntity.id == SignatureEntity.signer_id).where(SignatureEntity.signature_request_id == request.id).order_by(SignatureEntity.id)).all()
            return [SignatureEvidenceRead(signature_id=str(signature.id), signer_id=str(signer.id), request_id=str(request.id), document_id=str(request.document_id), document_version=request.document_version, signed_at=signature.signed_at, signer_name=signer.name, signer_email=signer.email, subject_hmac_sha256=str(signature.evidence_json.get("subject_hmac_sha256", "")), original_sha256=signature.document_sha256, evidence_sha256=signature.evidence_sha256 or evidence_sha256(signature.evidence_json), artifact_sha256=signature.artifact_sha256 or "", evidence=signature.evidence_json | ({"trusted_timestamp": signature.trusted_timestamp_json} if signature.trusted_timestamp_json else {})) for signature, signer in rows]

    def decline(self, token: str, auth_user_id: str) -> SignerRead:
        with SessionLocal.begin() as db:
            signer, request = self._resolve_request(db, token, auth_user_id, lock=True)
            if signer.status in {SignerStatus.SIGNED.value, SignerStatus.DECLINED.value}:
                raise WorkflowError("Signer already answered", 409)
            signer.status = SignerStatus.DECLINED.value
            self._audit(db, request.id, auth_user_id, "signature.declined", "signer", signer.id, {})
            db.flush()
            return self._signer_read(signer)

    def audit_events(self, request_id: str, actor_id: str) -> list[AuditEventRead]:
        with SessionLocal() as db:
            request = self._request(db, request_id)
            self._require_request_access(db, request, actor_id)
            items = db.scalars(select(AuditEventEntity).where(AuditEventEntity.signature_request_id == request.id).order_by(AuditEventEntity.id)).all()
            return [AuditEventRead(id=x.id, occurred_at=x.occurred_at, actor_type=x.actor_type, actor_id=x.actor_id, action=x.action, entity_type=x.entity_type, entity_id=x.entity_id, correlation_id=x.correlation_id, metadata_sanitized=x.metadata_sanitized) for x in items]

    def _resolve_request(self, db, token: str, auth_user_id: str, lock: bool = False, *, allow_completed: bool = False):
        request = self._request_from_token(db, token, lock=lock)
        statement = select(SignerEntity).where(SignerEntity.signature_request_id == request.id, SignerEntity.auth_user_id == auth_user_id.lower())
        signer = db.scalar(statement.with_for_update() if lock else statement)
        if signer is None:
            self._audit(db, request.id, auth_user_id, "authorization.failed", "signature_request", request.id, {})
            raise WorkflowError("Authenticated user does not match a signer for this request", 403)
        now = DateTimeService.utc_now()
        if signer.link_revoked_at is not None:
            raise WorkflowError("Signing access has been revoked", 410)
        signed_history = allow_completed and signer.status == SignerStatus.SIGNED.value
        if request.expires_at <= now and not signed_history:
            raise WorkflowError("Signature request has expired", 410)
        if request.status != RequestStatus.OPEN.value and not signed_history:
            raise WorkflowError("Signature request is not open", 409)
        return signer, request

    @staticmethod
    def _request_from_token(db, token: str, lock: bool = False) -> SignatureRequestEntity:
        statement = select(SignatureRequestEntity).where(
            SignatureRequestEntity.signing_token_hash == sha256(token.encode()).hexdigest(),
            SignatureRequestEntity.deleted_at.is_(None),
        )
        request = db.scalar(statement.with_for_update() if lock else statement)
        if request is None:
            raise WorkflowError("Signing link is invalid", 404)
        return request

    @staticmethod
    def _signature_evidence(request, signer, auth_user_id: str, signed_at, stamp: StampPosition, consent_version: str, client: ClientEvidence | None, geolocation: GeolocationEvidence | None, ip_address: str, user_agent: str, identity: IdentitySummary | None = None, tenant_country: str | None = None, stamp_positions: list[StampPosition] | None = None, stamp_customization: dict[str, object] | None = None, drawn_signature_png_data_url: str | None = None) -> dict[str, object]:
        subject_hash = hmac_new(settings.EVIDENCE_SECRET.encode(), auth_user_id.lower().encode(), "sha256").hexdigest()
        identity_binding = hmac_new(settings.EVIDENCE_SECRET.encode(), f"{auth_user_id.lower()}|{request.id}|{signer.id}|{request.document_id}|{request.document_version}".encode(), "sha256").hexdigest()
        normalized_agent = user_agent[:1000] or "unknown"
        lowered = normalized_agent.lower()
        device_type = "mobile" if any(value in lowered for value in ("mobile", "android", "iphone")) else "tablet" if "ipad" in lowered else "desktop"
        evidence_country = (identity.issuing_country if identity else None) or tenant_country
        # Positions configured per signer contain UUID values. Evidence is
        # canonical JSON, so normalize Pydantic's rich types before hashing it.
        stamp_payload = stamp.model_dump(mode="json")
        stamp_payload["country_code"] = evidence_country
        stamp_payload["show_flag"] = bool(evidence_country)
        stamp_payload["template"] = evidence_country if evidence_country in {"BR", "JP"} else "INTL"
        stamp_payload["locale"] = _stamp_locale_for_country(evidence_country, stamp_payload.get("locale"))
        position_payloads = []
        for position in stamp_positions or [stamp]:
            payload = position.model_dump(mode="json")
            payload.update({
                "country_code": evidence_country,
                "show_flag": bool(evidence_country),
                "template": stamp_payload["template"],
                "locale": _stamp_locale_for_country(evidence_country, payload.get("locale")),
            })
            position_payloads.append(payload)
        drawn_signature_hash = None
        if drawn_signature_png_data_url:
            drawn_signature_hash = sha256(drawn_signature_png_data_url.encode()).hexdigest()
        return {
            "schema": "rubrica-signature-evidence-v1",
            "consent": True,
            "consent_version": consent_version,
            "request_id": str(request.id),
            "signer_id": str(signer.id),
            "document_id": str(request.document_id),
            "document_version": request.document_version,
            "original_sha256": request.document_sha256,
            "subject_hmac_sha256": subject_hash,
            "identity_binding_hmac_sha256": identity_binding,
            "signer_name": signer.name,
            "identity_document_type": identity.identifier_type if identity else None,
            "identity_document_country": identity.issuing_country if identity else None,
            "identity_document_masked": identity.masked_display if identity else None,
            "signer_email": signer.email,
            "participant_role": getattr(signer, "participant_role", "external_signer"),
            "represented_tenant_id": str(getattr(signer, "represented_tenant_id", None)) if getattr(signer, "represented_tenant_id", None) else None,
            "representation_snapshot": getattr(signer, "representation_snapshot", None),
            "issuer_snapshot": getattr(request, "issuer_snapshot", None),
            "signed_at": signed_at.isoformat(),
            "stamp": stamp_payload,
            "stamp_positions": position_payloads,
            "stamp_customization": stamp_customization,
            "drawn_signature_sha256": drawn_signature_hash,
            "drawn_signature_png_data_url": drawn_signature_png_data_url,
            "network": {"ip_address": ip_address[:64], "user_agent": normalized_agent, "device_type": device_type},
            "client": (client or ClientEvidence()).model_dump(),
            "geolocation": (geolocation or GeolocationEvidence(status="unavailable")).model_dump(),
        }

    @staticmethod
    def _request_token(request_id: UUID, nonce: str) -> str:
        legacy_value = request_id.int
        token_identifier = str(legacy_value) if request_id.int <= 0x7FFFFFFF else str(request_id)
        payload = f"rubrica-request:{token_identifier}:{nonce}".encode()
        return hmac_new(settings.EVIDENCE_SECRET.encode(), payload, "sha256").hexdigest()

    @staticmethod
    def _stamp_customizations(snapshot: dict[str, object] | None) -> tuple[dict[str, object] | None, dict[str, dict[str, object]]]:
        if not snapshot:
            return None, {}
        if snapshot.get("schema") == "per-signer-v1":
            default = snapshot.get("default")
            by_signer = snapshot.get("by_signer")
            return (default if isinstance(default, dict) else None, by_signer if isinstance(by_signer, dict) else {})
        return snapshot, {}

    @classmethod
    def _signer_stamp_customization(cls, snapshot: dict[str, object] | None, signer_id: UUID) -> dict[str, object] | None:
        default, by_signer = cls._stamp_customizations(snapshot)
        return by_signer.get(str(signer_id), default)

    def _signer(self, db, identifier: str, request_id: UUID, lock: bool = False) -> SignerEntity:
        try:
            value = UUID(str(identifier))
        except ValueError as exc:
            raise WorkflowError("Signer not found", 404) from exc
        statement = select(SignerEntity).where(SignerEntity.id == value, SignerEntity.signature_request_id == request_id)
        item = db.scalar(statement.with_for_update() if lock else statement)
        if item is None:
            raise WorkflowError("Signer not found", 404)
        return item

    @staticmethod
    def _account_storage_id(member: TenantMemberEntity | None, subject: str) -> UUID:
        if member is not None and member.auth_user_uuid is not None:
            return member.auth_user_uuid
        return uuid5(NAMESPACE_URL, f"rubrica-account:{subject.strip().lower()}")

    def _document_owner_storage_id(self, db, document: DocumentEntity) -> UUID:
        owner = db.scalar(
            select(TenantMemberEntity).where(
                TenantMemberEntity.tenant_id == document.tenant_id,
                func.lower(TenantMemberEntity.auth_user_id) == document.created_by.lower(),
                TenantMemberEntity.deleted_at.is_(None),
            )
        )
        return self._account_storage_id(owner, document.created_by)

    def _document(self, db, identifier: str, lock: bool = False) -> DocumentEntity:
        try:
            value = UUID(str(identifier))
        except ValueError as exc:
            raise WorkflowError("Document not found", 404) from exc
        statement = select(DocumentEntity).where(DocumentEntity.id == value, DocumentEntity.deleted_at.is_(None))
        item = db.scalar(statement.with_for_update() if lock else statement)
        if item is None:
            raise WorkflowError("Document not found", 404)
        return item

    def _request(self, db, identifier: str, lock: bool = False) -> SignatureRequestEntity:
        try:
            value = UUID(str(identifier))
        except ValueError as exc:
            raise WorkflowError("Signature request not found", 404) from exc
        statement = select(SignatureRequestEntity).where(SignatureRequestEntity.id == value, SignatureRequestEntity.deleted_at.is_(None))
        item = db.scalar(statement.with_for_update() if lock else statement)
        if item is None:
            raise WorkflowError("Signature request not found", 404)
        return item

    @staticmethod
    def _ancestor_signatures(db, request: SignatureRequestEntity) -> list[SignatureEntity]:
        ancestors: list[SignatureRequestEntity] = []
        parent_id = request.parent_request_id
        while parent_id is not None:
            parent = db.get(SignatureRequestEntity, parent_id)
            if parent is None:
                raise WorkflowError("Signature round history is incomplete", 409)
            ancestors.append(parent)
            parent_id = parent.parent_request_id
        signatures: list[SignatureEntity] = []
        for ancestor in reversed(ancestors):
            signatures.extend(db.scalars(select(SignatureEntity).where(SignatureEntity.signature_request_id == ancestor.id).order_by(SignatureEntity.id)).all())
        return signatures

    @staticmethod
    def _require_request_access(db, request: SignatureRequestEntity, actor_id: str) -> None:
        document = db.get(DocumentEntity, request.document_id)
        if document is None:
            raise WorkflowError("Document not found", 404)
        DatabaseSignatureWorkflowService._require_document_access(db, document, actor_id, request=request)

    @staticmethod
    def _require_document_access(db, document: DocumentEntity, actor_id: str, *, request: SignatureRequestEntity | None = None) -> None:
        member = tenant_service.require_role(db, document.tenant_id, actor_id)
        normalized_actor = actor_id.lower()
        if member.role == "admin" or document.created_by.lower() == normalized_actor:
            return
        signer_query = select(SignerEntity.id).join(SignatureRequestEntity, SignatureRequestEntity.id == SignerEntity.signature_request_id).where(
            SignatureRequestEntity.document_id == document.id,
            SignatureRequestEntity.deleted_at.is_(None),
            or_(SignerEntity.auth_user_id == normalized_actor, SignerEntity.email == normalized_actor),
        )
        if request is not None:
            signer_query = signer_query.where(SignatureRequestEntity.id == request.id)
        if db.scalar(signer_query.limit(1)) is None:
            raise WorkflowError("Document access is not allowed", 403)

    def _request_read(self, db, item: SignatureRequestEntity) -> SignatureRequestRead:
        signer_count = db.scalar(select(func.count()).select_from(SignerEntity).where(SignerEntity.signature_request_id == item.id)) or 0
        signed_count = db.scalar(select(func.count()).select_from(SignerEntity).where(SignerEntity.signature_request_id == item.id, SignerEntity.status == SignerStatus.SIGNED.value)) or 0
        document = db.get(DocumentEntity, item.document_id)
        effective_status = RequestStatus.EXPIRED.value if item.status == RequestStatus.OPEN.value and item.expires_at <= DateTimeService.utc_now() else item.status
        child_request_id = db.scalar(select(SignatureRequestEntity.id).where(SignatureRequestEntity.parent_request_id == item.id, SignatureRequestEntity.deleted_at.is_(None)))
        return SignatureRequestRead(id=item.id, document_id=item.document_id, document_version=item.document_version, document_sha256=item.document_sha256, status=effective_status, expires_at=item.expires_at, created_by=item.created_by, created_at=item.created_at, opened_at=item.opened_at, completed_at=item.completed_at, signer_count=signer_count + item.preserved_signature_count, signed_count=signed_count + item.preserved_signature_count, document_title=document.title if document else "", original_filename=document.original_filename if document else "", signature_mode=item.signature_mode, issuer_snapshot=item.issuer_snapshot, has_custom_stamp_placement=bool(item.stamp_placements), has_custom_stamp_branding=bool(item.stamp_customization_snapshot), parent_request_id=item.parent_request_id, round_number=item.round_number, reopened_reason=item.reopened_reason, reopened_by=item.reopened_by, reopened_at=item.reopened_at, preserved_signature_count=item.preserved_signature_count, child_request_id=child_request_id)

    @staticmethod
    def _document_read(db, x: DocumentEntity) -> DocumentRead:
        size_bytes = db.scalar(select(DocumentVersionEntity.size_bytes).where(DocumentVersionEntity.document_id == x.id, DocumentVersionEntity.version == x.version))
        request_count = db.scalar(select(func.count()).select_from(SignatureRequestEntity).where(SignatureRequestEntity.document_id == x.id, SignatureRequestEntity.deleted_at.is_(None))) or 0
        completed_signature_count = db.scalar(select(func.count()).select_from(SignerEntity).join(SignatureRequestEntity, SignatureRequestEntity.id == SignerEntity.signature_request_id).where(SignatureRequestEntity.document_id == x.id, SignatureRequestEntity.deleted_at.is_(None), SignerEntity.status == SignerStatus.SIGNED.value)) or 0
        return DocumentRead(id=x.id, organization_id=x.organization_id, title=x.title, original_filename=x.original_filename, content_type=x.content_type, sha256=x.sha256, version=x.version, status=x.status, created_by=x.created_by, created_at=x.created_at, updated_at=x.updated_at, size_bytes=size_bytes, signature_request_count=request_count, completed_signature_count=completed_signature_count)

    @staticmethod
    def _version_read(x: DocumentVersionEntity) -> DocumentVersionRead:
        return DocumentVersionRead(document_id=x.document_id, version=x.version, original_filename=x.original_filename, content_type=x.content_type, sha256=x.sha256, size_bytes=x.size_bytes, created_by=x.created_by, created_at=x.created_at)

    @staticmethod
    def _signer_read(x: SignerEntity) -> SignerRead:
        return SignerRead(id=x.id, signature_request_id=x.signature_request_id, auth_user_id=x.auth_user_id, name=x.name, email=x.email, preferred_locale=x.preferred_locale, status=x.status, token_expires_at=x.token_expires_at, link_revoked_at=x.link_revoked_at, signed_at=x.signed_at, participant_role=x.participant_role, represented_tenant_id=x.represented_tenant_id, representation_snapshot=x.representation_snapshot, signature_mode=x.signature_mode)

    @staticmethod
    def _signing_url(request_id: str) -> str:
        return f"{settings.SIGNING_APP_URL.rstrip('/')}/{request_id}"

    @staticmethod
    def _audit(db, request_id: UUID | None, actor_id: str, action: str, entity_type: str, entity_id: object, metadata: dict[str, object]) -> None:
        db.add(AuditEventEntity(signature_request_id=request_id, occurred_at=DateTimeService.utc_now(), actor_type="user", actor_id=actor_id, action=action, entity_type=entity_type, entity_id=UUID(str(entity_id)), correlation_id=uuid4(), metadata_sanitized=metadata))


database_workflow_service = DatabaseSignatureWorkflowService(configured_document_storage(settings))
