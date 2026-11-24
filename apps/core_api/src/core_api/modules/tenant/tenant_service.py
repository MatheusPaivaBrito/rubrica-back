from datetime import datetime, timedelta
from secrets import token_urlsafe

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from uuid import UUID, uuid4

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.auth_context import active_auth_context
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.document.document_entity import DocumentEntity
from core_api.modules.signature_request.signature_request_entity import (
    AuditEventEntity, SignatureRequestEntity, SignerEntity,
)
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import (
    TenantEntity,
    TenantMemberEntity,
    TenantSeatRosterEntity,
)
from core_api.modules.tenant.tenant_identity import InvalidBusinessIdentifierError, protect_cnpj
from core_api.modules.tenant.user_client import invite_auth_user, resolve_auth_user
from shared_kernel.time.datetime_service import DateTimeService
from core_api.modules.tenant.tenant_schema import (
    TenantBusinessConversion,
    TenantCreate,
    TenantMemberCreate,
    TenantMemberInvitation,
    TenantMemberRead,
    TenantTeamRead,
    TenantTeamUpdate,
    TenantSeatRosterUpdate,
    TenantProvision,
    TenantPreferencesUpdate,
    TenantRead,
    SuspendedTenantAccess,
    TenantAccessState,
)

WORKSPACE_EXPORT_WINDOW = timedelta(days=30)

EURO_COUNTRY_CODES = frozenset(
    {
        "AD", "AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR",
        "IE", "IT", "LT", "LU", "LV", "MC", "ME", "MT", "NL", "PT", "SI",
        "SK", "SM", "VA", "XK",
    }
)


def _public_slug() -> str:
    """Return an opaque, URL-safe identifier with 144 bits of entropy."""
    return token_urlsafe(18)


def billing_currency_for_country(country_code: str | None) -> str:
    code = (country_code or "").upper()
    if code == "BR":
        return "BRL"
    if code == "JP":
        return "JPY"
    if code in EURO_COUNTRY_CODES:
        return "EUR"
    return "USD"


class TenantService:
    def provision_owner(self, payload: TenantProvision) -> TenantRead:
        owner = payload.owner_email.strip().lower()
        with SessionLocal.begin() as db:
            existing = db.execute(
                select(TenantEntity, TenantMemberEntity.role)
                .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
                .where(
                    self.membership_identity_filter(owner, payload.owner_user_id),
                    TenantMemberEntity.role == "admin",
                    TenantEntity.kind == "personal",
                    TenantEntity.deleted_at.is_(None),
                )
                .order_by(TenantEntity.created_at)
            ).first()
            if existing is not None:
                member = db.scalar(
                    select(TenantMemberEntity).where(
                        TenantMemberEntity.tenant_id == existing[0].id,
                        self.membership_identity_filter(owner, payload.owner_user_id),
                    )
                )
                if member is not None and member.auth_user_uuid is None:
                    member.auth_user_uuid = payload.owner_user_id
                    db.flush()
                return self._read(existing[0], existing[1])

            tenant = TenantEntity(
                name=payload.name.strip(),
                slug=_public_slug(),
                status="active",
                default_locale=payload.default_locale,
                country_code=payload.country_code,
                timezone="UTC",
                currency=billing_currency_for_country(payload.country_code),
            )
            db.add(tenant)
            db.flush()
            db.add(
                TenantMemberEntity(
                    tenant_id=tenant.id,
                    auth_user_id=owner,
                    auth_user_uuid=payload.owner_user_id,
                    role="admin",
                    status="active",
                    joined_at=DateTimeService.utc_now(),
                )
            )
            db.add(BillingAccountEntity(tenant_id=tenant.id, status="not_configured"))
            db.flush()
            return self._read(tenant, "admin")

    def list_for(self, subject: str) -> list[TenantRead]:
        with SessionLocal() as db:
            rows = db.execute(
                select(TenantEntity, TenantMemberEntity.role, BillingAccountEntity)
                .join_from(TenantEntity, TenantMemberEntity, or_(
                    TenantMemberEntity.tenant_id == TenantEntity.id,
                    and_(TenantMemberEntity.role == "admin", self.organization_parent(TenantEntity.id) == TenantMemberEntity.tenant_id),
                ))
                .outerjoin(
                    BillingAccountEntity,
                    and_(
                        BillingAccountEntity.tenant_id == TenantEntity.id,
                        BillingAccountEntity.deleted_at.is_(None),
                    ),
                )
                .where(
                    self.membership_identity_filter(subject),
                    TenantEntity.deleted_at.is_(None),
                    TenantMemberEntity.deleted_at.is_(None),
                    TenantMemberEntity.status == "active",
                )
                .order_by(TenantEntity.name, (TenantMemberEntity.role == "admin").desc())
            ).all()
            unique_workspaces = {}
            for tenant, role, account in rows:
                unique_workspaces.setdefault(tenant.id, (tenant, role, account))
            return [
                self._read(
                    tenant,
                    role,
                    workspace_selectable=tenant.status == "active" and (
                        tenant.workspace_closed_at is not None
                        or tenant.kind == "personal"
                        or bool(account and (account.status == "active" or account.complimentary_lifetime))
                    ),
                )
                for tenant, role, account in unique_workspaces.values()
                if tenant.workspace_closed_at is None or (
                    role == "admin" and self.export_open(tenant)
                )
            ]

    def access_state(self, subject: str) -> TenantAccessState:
        with SessionLocal() as db:
            memberships = db.execute(
                select(TenantEntity, TenantMemberEntity)
                .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
                .where(
                    self.membership_identity_filter(subject),
                    TenantEntity.deleted_at.is_(None),
                    TenantMemberEntity.deleted_at.is_(None),
                )
                .order_by(TenantEntity.name)
            ).all()
            active_count = sum(member.status == "active" for _, member in memberships)
            suspended = [
                SuspendedTenantAccess(
                    tenant_id=tenant.id,
                    tenant_name=tenant.name,
                    tenant_kind=tenant.kind,
                    role=member.role,
                    default_locale=tenant.default_locale,
                    country_code=tenant.country_code,
                    currency=tenant.currency,
                )
                for tenant, member in memberships
                if member.status == "suspended"
            ]
            return TenantAccessState(
                active_tenant_count=active_count,
                suspended_tenants=suspended,
                can_create_personal_tenant=not any(
                    tenant.kind == "personal" and member.status == "active"
                    for tenant, member in memberships
                ),
            )

    def create_personal_after_suspension(
        self,
        payload: TenantCreate,
        subject: str,
        user_id: str | None,
    ) -> TenantRead:
        try:
            auth_user_uuid = UUID(user_id) if user_id else None
        except ValueError:
            auth_user_uuid = None
        with SessionLocal.begin() as db:
            if db.get_bind().dialect.name == "postgresql":
                identity = str(auth_user_uuid) if auth_user_uuid else subject.strip().lower()
                db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"personal-workspace:{identity}"))))
            memberships = db.execute(
                select(TenantEntity, TenantMemberEntity)
                .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
                .where(
                    self.membership_identity_filter(subject, auth_user_uuid),
                    TenantEntity.deleted_at.is_(None),
                    TenantMemberEntity.deleted_at.is_(None),
                )
                .with_for_update()
            ).all()
            for workspace, member in memberships:
                if workspace.kind == "personal" and member.status == "active":
                    return self._read(workspace, member.role)
            if not payload.country_code:
                raise WorkflowError("Choose the country for your personal workspace", 422)
            tenant = TenantEntity(
                name=payload.name.strip(),
                slug=_public_slug(),
                status="active",
                default_locale=payload.default_locale,
                country_code=payload.country_code,
                timezone=payload.timezone,
                currency=billing_currency_for_country(payload.country_code),
                kind="personal",
            )
            db.add(tenant)
            db.flush()
            member = TenantMemberEntity(
                tenant_id=tenant.id,
                auth_user_id=subject.lower(),
                auth_user_uuid=auth_user_uuid,
                role="admin",
                status="active",
                joined_at=DateTimeService.utc_now(),
            )
            db.add(member)
            db.add(BillingAccountEntity(tenant_id=tenant.id, status="not_configured"))
            self._audit(
                db,
                tenant.id,
                subject,
                "tenant.personal_workspace_recovered",
                {},
            )
            db.flush()
            return self._read(tenant, member.role)

    def create(self, payload: TenantCreate, subject: str) -> TenantRead:
        with SessionLocal.begin() as db:
            tenant = TenantEntity(
                name=payload.name.strip(),
                slug=_public_slug(),
                status="active",
                default_locale=payload.default_locale,
                country_code=payload.country_code,
                timezone=payload.timezone,
                currency=payload.currency,
            )
            db.add(tenant)
            try:
                db.flush()
            except IntegrityError as exc:
                raise WorkflowError("Tenant slug is already in use", 409) from exc
            member = TenantMemberEntity(tenant_id=tenant.id, auth_user_id=subject.lower(), role="admin")
            db.add(member)
            db.add(BillingAccountEntity(tenant_id=tenant.id, status="not_configured"))
            db.flush()
            return self._read(tenant, "admin")

    def add_member(self, tenant_id: UUID, payload: TenantMemberCreate, subject: str) -> None:
        with SessionLocal.begin() as db:
            self._lock_team(db, tenant_id)
            self.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True)
            tenant = db.get(TenantEntity, tenant_id)
            if tenant is None or tenant.deleted_at is not None:
                raise WorkflowError("Tenant not found", 404)
            from core_api.modules.billing.billing_service import billing_service

            if not billing_service.business_features_enabled(db, tenant_id):
                raise WorkflowError("A Professional or Team plan is required for business members", 403)
            member_limit = self.member_limit(db, tenant_id)
            active_members = db.scalar(
                select(func.count(TenantMemberEntity.id)).where(
                    TenantMemberEntity.tenant_id == tenant_id,
                    TenantMemberEntity.deleted_at.is_(None),
                    TenantMemberEntity.status == "active",
                )
            ) or 0
            initial_status = (
                "without_seat"
                if member_limit is not None and active_members >= member_limit
                else "active"
            )
            member_user_uuid = resolve_auth_user(payload.auth_user_id.lower())
            db.add(TenantMemberEntity(tenant_id=tenant_id, auth_user_id=payload.auth_user_id.lower(), auth_user_uuid=member_user_uuid, role=payload.role, status=initial_status, joined_at=DateTimeService.utc_now()))
            try:
                db.flush()
            except IntegrityError as exc:
                raise WorkflowError("User is already a tenant member", 409) from exc
            self._audit(db, tenant_id, subject, "tenant.member_added", {"member_role": payload.role, "member_count": active_members + 1})

    def invite_member(self, tenant_id: UUID, payload: TenantMemberInvitation, subject: str) -> None:
        with SessionLocal.begin() as db:
            self._lock_team(db, tenant_id)
            self.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True)
            tenant = db.get(TenantEntity, tenant_id)
            if tenant is None or tenant.deleted_at is not None:
                raise WorkflowError("Tenant not found", 404)
            from core_api.modules.billing.billing_service import billing_service
            if not billing_service.business_features_enabled(db, tenant_id):
                raise WorkflowError("A Professional or Team plan is required for business members", 403)
            limit = self.member_limit(db, tenant_id)
            active_members = db.scalar(select(func.count(TenantMemberEntity.id)).where(
                TenantMemberEntity.tenant_id == tenant_id,
                TenantMemberEntity.deleted_at.is_(None),
                TenantMemberEntity.status == "active",
            )) or 0
            initial_status = (
                "without_seat"
                if limit is not None and active_members >= limit
                else "active"
            )
            email = payload.email.strip().lower()
            existing = db.scalar(select(TenantMemberEntity).where(
                TenantMemberEntity.tenant_id == tenant_id,
                TenantMemberEntity.auth_user_id == email,
                TenantMemberEntity.deleted_at.is_(None),
            ))
            if existing:
                raise WorkflowError("User is already a tenant member", 409)
            user_uuid = invite_auth_user(
                name=payload.name.strip(), email=email, document=payload.document,
                locale=tenant.default_locale, country=tenant.country_code or "BR",
            )
            db.add(TenantMemberEntity(
                tenant_id=tenant_id, auth_user_id=email, auth_user_uuid=user_uuid,
                role=payload.role, status=initial_status, joined_at=DateTimeService.utc_now(),
            ))
            self._audit(db, tenant_id, subject, "tenant.member_invited", {"member_role": payload.role, "member_count": active_members + 1})

    def list_members(self, tenant_id: UUID, subject: str) -> list[TenantMemberRead]:
        with SessionLocal() as db:
            self.require_role(db, tenant_id, subject, {"admin", "auditor"}, allow_over_limit=True)
            members = db.scalars(
                select(TenantMemberEntity)
                .where(
                    TenantMemberEntity.tenant_id == tenant_id,
                    TenantMemberEntity.deleted_at.is_(None),
                )
                .order_by(TenantMemberEntity.joined_at, TenantMemberEntity.created_at)
            ).all()
            return [
                TenantMemberRead.model_validate(member, from_attributes=True)
                for member in members
            ]

    @staticmethod
    def _lock_team(db, tenant_id: UUID) -> BillingAccountEntity:
        # Same row lock as billing webhooks: plan changes and member changes serialize.
        account = db.scalar(select(BillingAccountEntity).where(
            BillingAccountEntity.tenant_id == tenant_id,
            BillingAccountEntity.deleted_at.is_(None),
        ).with_for_update())
        if account is None:
            raise WorkflowError("Tenant not found", 404)
        return account

    @staticmethod
    def member_limit(db, tenant_id: UUID) -> int | None:
        from core_api.modules.billing.billing_service import BillingService
        account = db.scalar(select(BillingAccountEntity).where(
            BillingAccountEntity.tenant_id == tenant_id, BillingAccountEntity.deleted_at.is_(None)))
        if account is None:
            return 1
        return BillingService.contracted_seat_count(account)

    @staticmethod
    def team_over_limit(db, tenant_id: UUID) -> bool:
        count = db.scalar(select(func.count(TenantMemberEntity.id)).where(
            TenantMemberEntity.tenant_id == tenant_id,
            TenantMemberEntity.deleted_at.is_(None), TenantMemberEntity.status == "active")) or 0
        limit = TenantService.member_limit(db, tenant_id)
        return limit is not None and count > limit

    def _team_read(self, db, tenant_id: UUID, member: TenantMemberEntity) -> TenantTeamRead:
        members = db.scalars(select(TenantMemberEntity).where(
            TenantMemberEntity.tenant_id == tenant_id, TenantMemberEntity.deleted_at.is_(None)
        ).order_by(TenantMemberEntity.role, TenantMemberEntity.auth_user_id, TenantMemberEntity.id)).all()
        limit = self.member_limit(db, tenant_id)
        active_count = sum(m.status == "active" for m in members)
        account = db.scalar(
            select(BillingAccountEntity).where(
                BillingAccountEntity.tenant_id == tenant_id,
                BillingAccountEntity.deleted_at.is_(None),
            )
        )
        next_cycle = None
        if account and account.current_period_ends_at:
            next_cycle = db.scalar(
                select(TenantSeatRosterEntity).where(
                    TenantSeatRosterEntity.tenant_id == tenant_id,
                    TenantSeatRosterEntity.cycle_starts_at
                    == account.current_period_ends_at,
                    TenantSeatRosterEntity.status == "scheduled",
                    TenantSeatRosterEntity.deleted_at.is_(None),
                )
            )
        eligible_ids = {str(item.id) for item in members if item.status not in {"offboarded", "pending"}}
        tenant = db.get(TenantEntity, tenant_id)
        return TenantTeamRead(
            export_until=(
                DateTimeService.to_utc(tenant.workspace_closed_at) + WORKSPACE_EXPORT_WINDOW
                if tenant and tenant.workspace_closed_at else None
            ),
            closure_requested_at=(
                DateTimeService.to_utc(tenant.closure_requested_at)
                if tenant and tenant.closure_requested_at else None
            ),
            members=[TenantMemberRead.model_validate(m, from_attributes=True) for m in members],
            member_limit=limit,
            active_count=active_count,
            requires_selection=limit is not None and active_count > limit,
            can_manage=member.role == "admin", current_member_id=member.id,
            organization_root=bool(tenant and tenant.kind == "business" and tenant.parent_workspace_id is None),
            can_request_branch=bool(
                tenant and tenant.workspace_closed_at is None and
                member.role == "admin" and tenant and tenant.kind == "business"
                and tenant.parent_workspace_id is None and tenant.status == "active"
                and account and account.status == "active"
                and account.current_product_code == "rubrica_team"
            ),
            current_seat_member_ids=[m.id for m in members if m.status == "active"],
            next_cycle_member_ids=(
                [UUID(value) for value in next_cycle.member_ids if value in eligible_ids]
                if next_cycle
                else [m.id for m in members if m.status == "active"]
            ),
            next_cycle_starts_at=(
                account.current_period_ends_at if account else None
            ),
            seat_roster_locked=True,
        )

    def team(self, tenant_id: UUID, subject: str) -> TenantTeamRead:
        with SessionLocal.begin() as db:
            member = self.require_role(
                db, tenant_id, subject, {"admin"}, allow_over_limit=True, allow_export=True
            )
            tenant = db.get(TenantEntity, tenant_id)
            if tenant.workspace_closed_at is None:
                self.apply_due_seat_roster(db, tenant_id)
                member = self.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True)
                self.reconcile_single_member_plan(db, tenant_id)
            return self._team_read(db, tenant_id, member)

    def update_closure_request(self, tenant_id: UUID, subject: str, *, requested: bool) -> TenantTeamRead:
        with SessionLocal.begin() as db:
            self._lock_team(db, tenant_id)
            actor = self.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True)
            tenant = db.get(TenantEntity, tenant_id, with_for_update=True)
            if tenant is None or tenant.deleted_at is not None or tenant.kind != "business" or tenant.status != "active":
                raise WorkflowError("Only an active business workspace can request closure", 409)
            if (tenant.closure_requested_at is not None) != requested:
                tenant.closure_requested_at = DateTimeService.utc_now() if requested else None
                self._audit(db, tenant_id, subject, "tenant.closure_requested" if requested else "tenant.closure_withdrawn", {})
                db.flush()
            return self._team_read(db, tenant_id, actor)

    def close_workspace(self, tenant_id: UUID, subject: str) -> TenantTeamRead:
        with SessionLocal.begin() as db:
            account = self._lock_team(db, tenant_id)
            actor = self.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True, allow_export=True)
            tenant = db.get(TenantEntity, tenant_id, with_for_update=True)
            if tenant.workspace_closed_at is not None:
                return self._team_read(db, tenant_id, actor)
            if tenant.kind != "business" or tenant.status != "active" or tenant.closure_requested_at is None:
                raise WorkflowError("Request closure before confirming", 409)
            if account.provider_subscription_id and account.status in {"active", "pending", "past_due", "unpaid", "paused"}:
                raise WorkflowError("Cancel the Stripe subscription before confirming closure", 409)
            if db.scalar(select(TenantEntity.id).where(
                TenantEntity.parent_workspace_id == tenant_id,
                TenantEntity.deleted_at.is_(None),
                TenantEntity.workspace_closed_at.is_(None),
            ).limit(1)) is not None:
                raise WorkflowError("Close the organization's branches before closing its main workspace", 409)
            tenant.workspace_closed_at = DateTimeService.utc_now()
            document_ids = select(DocumentEntity.id).where(DocumentEntity.tenant_id == tenant_id)
            request_ids = select(SignatureRequestEntity.id).where(SignatureRequestEntity.document_id.in_(document_ids))
            db.execute(update(SignerEntity).where(
                SignerEntity.signature_request_id.in_(request_ids),
                SignerEntity.link_revoked_at.is_(None),
            ).values(link_revoked_at=tenant.workspace_closed_at))
            cancelled = db.execute(update(SignatureRequestEntity).where(
                SignatureRequestEntity.document_id.in_(document_ids),
                SignatureRequestEntity.status.in_(("draft", "open")),
            ).values(status="cancelled"))
            self._audit(db, tenant_id, subject, "tenant.closed", {
                "cancelled_request_count": cancelled.rowcount,
            })
            db.flush()
            return self._team_read(db, tenant_id, actor)

    def schedule_seat_roster(
        self,
        tenant_id: UUID,
        payload: TenantSeatRosterUpdate,
        subject: str,
    ) -> TenantTeamRead:
        with SessionLocal.begin() as db:
            self._lock_team(db, tenant_id)
            self.apply_due_seat_roster(db, tenant_id)
            actor = self.require_role(
                db, tenant_id, subject, {"admin"}, allow_over_limit=True
            )
            account = db.scalar(
                select(BillingAccountEntity)
                .where(
                    BillingAccountEntity.tenant_id == tenant_id,
                    BillingAccountEntity.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if account is None or account.current_period_ends_at is None:
                raise WorkflowError(
                    "A billing cycle is required to schedule seat occupants", 409
                )
            members = db.scalars(
                select(TenantMemberEntity).where(
                    TenantMemberEntity.tenant_id == tenant_id,
                    TenantMemberEntity.deleted_at.is_(None), TenantMemberEntity.status.notin_(("offboarded", "pending")),
                )
            ).all()
            selected = set(payload.member_ids)
            by_id = {member.id: member for member in members}
            if not selected.issubset(by_id):
                raise WorkflowError("Member does not belong to this tenant", 422)
            limit = self.member_limit(db, tenant_id)
            if limit is not None and len(selected) > limit:
                raise WorkflowError(
                    f"The current plan allows up to {limit} seat occupants", 409
                )
            if actor.tenant_id == tenant_id and actor.id not in selected:
                raise WorkflowError("Keep your administrator account in a seat", 409)
            if not any(by_id[member_id].role == "admin" for member_id in selected):
                raise WorkflowError("Keep at least one administrator in a seat", 409)
            roster = db.scalar(
                select(TenantSeatRosterEntity)
                .where(
                    TenantSeatRosterEntity.tenant_id == tenant_id,
                    TenantSeatRosterEntity.cycle_starts_at
                    == account.current_period_ends_at,
                    TenantSeatRosterEntity.deleted_at.is_(None),
                )
                .with_for_update()
            )
            member_ids = sorted(str(member_id) for member_id in selected)
            if roster is None:
                roster = TenantSeatRosterEntity(
                    tenant_id=tenant_id,
                    cycle_starts_at=account.current_period_ends_at,
                    seat_limit=limit or len(member_ids),
                    member_ids=member_ids,
                    status="scheduled",
                    created_by=subject.lower(),
                )
                db.add(roster)
            else:
                if roster.status != "scheduled":
                    raise WorkflowError("The current cycle roster is locked", 409)
                roster.seat_limit = limit or len(member_ids)
                roster.member_ids = member_ids
                roster.created_by = subject.lower()
            self._audit(
                db,
                tenant_id,
                subject,
                "tenant.seat_roster_scheduled",
                {
                    "cycle_starts_at": account.current_period_ends_at.isoformat(),
                    "seat_limit": limit,
                    "member_ids": member_ids,
                },
            )
            db.flush()
            return self._team_read(db, tenant_id, actor)

    @staticmethod
    def apply_due_seat_roster(db, tenant_id: UUID, *, through: datetime | None = None) -> None:
        now = DateTimeService.utc_now()
        rosters = db.scalars(
            select(TenantSeatRosterEntity)
            .where(
                TenantSeatRosterEntity.tenant_id == tenant_id,
                TenantSeatRosterEntity.status == "scheduled",
                TenantSeatRosterEntity.cycle_starts_at <= (through or now),
                TenantSeatRosterEntity.deleted_at.is_(None),
            )
            .order_by(TenantSeatRosterEntity.cycle_starts_at)
            .with_for_update()
        ).all()
        for roster in rosters:
            selected = {UUID(value) for value in roster.member_ids}
            members = db.scalars(
                select(TenantMemberEntity)
                .where(
                    TenantMemberEntity.tenant_id == tenant_id,
                    TenantMemberEntity.deleted_at.is_(None), TenantMemberEntity.status.notin_(("offboarded", "pending")),
                )
                .with_for_update()
            ).all()
            for member in members:
                member.status = (
                    "active" if member.id in selected else "without_seat"
                )
            roster.status = "applied"
            roster.applied_at = now

    def reconcile_single_member_plan(self, db, tenant_id: UUID) -> None:
        """Keep only the administrator active when the current plan has one seat."""
        if self.member_limit(db, tenant_id) != 1:
            return
        active_members = db.scalars(
            select(TenantMemberEntity)
            .where(
                TenantMemberEntity.tenant_id == tenant_id,
                TenantMemberEntity.deleted_at.is_(None),
                TenantMemberEntity.status == "active",
            )
            .order_by(
                TenantMemberEntity.joined_at,
                TenantMemberEntity.created_at,
                TenantMemberEntity.id,
            )
        ).all()
        administrator = next(
            (member for member in active_members if member.role == "admin"),
            None,
        )
        if administrator is None:
            return
        suspended = []
        for member in active_members:
            if member.id == administrator.id:
                continue
            member.status = "suspended"
            suspended.append(str(member.id))
        if suspended:
            self._audit(
                db,
                tenant_id,
                administrator.auth_user_id,
                "tenant.team_reconciled_after_downgrade",
                {"active_member_id": str(administrator.id), "suspended_member_ids": suspended},
            )

    def update_team(self, tenant_id: UUID, payload: TenantTeamUpdate, subject: str) -> TenantTeamRead:
        with SessionLocal.begin() as db:
            self._lock_team(db, tenant_id)
            actor = self.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True)
            members = db.scalars(select(TenantMemberEntity).where(
                TenantMemberEntity.tenant_id == tenant_id, TenantMemberEntity.deleted_at.is_(None), TenantMemberEntity.status.notin_(("offboarded", "pending"))
            )).all()
            selected = set(payload.active_member_ids)
            if not selected.issubset({m.id for m in members}):
                raise WorkflowError("Member does not belong to this tenant", 422)
            if actor.tenant_id == tenant_id and actor.id not in selected:
                raise WorkflowError("Keep your administrator account active", 409)
            if not any(member.id in selected and member.role == "admin" for member in members):
                raise WorkflowError("Keep at least one workspace administrator active", 409)
            limit = self.member_limit(db, tenant_id)
            if limit is not None and len(selected) > limit:
                raise WorkflowError(f"The current plan allows up to {limit} tenant members", 409)
            changed = []
            for member in members:
                status = "active" if member.id in selected else "suspended"
                if member.status != status:
                    changed.append({"member_id": str(member.id), "previous_status": member.status, "status": status})
                    member.status = status
            if changed:
                self._audit(db, tenant_id, subject, "tenant.team_updated", {"changes": changed, "member_limit": limit})
            db.flush()
            return self._team_read(db, tenant_id, actor)

    def update_member_role(
        self, tenant_id: UUID, member_id: UUID, role: str, subject: str,
        *, scope: str | None = None, sign_company_only: bool | None = None,
    ) -> TenantTeamRead:
        with SessionLocal.begin() as db:
            self._lock_team(db, tenant_id)
            self.apply_due_seat_roster(db, tenant_id)
            actor = self.require_role(
                db, tenant_id, subject, {"admin"}, allow_over_limit=True
            )
            member = db.scalar(
                select(TenantMemberEntity)
                .where(
                    TenantMemberEntity.id == member_id,
                    TenantMemberEntity.tenant_id == tenant_id,
                    TenantMemberEntity.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if member is None:
                raise WorkflowError("Member does not belong to this tenant", 404)
            if member.id == actor.id:
                raise WorkflowError("Another administrator must change your role", 409)
            previous_role = member.role
            if role == "admin" and previous_role != "admin":
                tenant = db.get(TenantEntity, tenant_id)
                if tenant.kind != "business" or member.status != "active":
                    raise WorkflowError("Only an active business workspace member can become administrator", 409)
            if previous_role == "admin" and role != "admin":
                rosters = db.scalars(select(TenantSeatRosterEntity).where(
                    TenantSeatRosterEntity.tenant_id == tenant_id,
                    TenantSeatRosterEntity.status == "scheduled",
                    TenantSeatRosterEntity.deleted_at.is_(None),
                ))
                for roster in rosters:
                    other_administrator = db.scalar(select(TenantMemberEntity.id).where(
                        TenantMemberEntity.tenant_id == tenant_id,
                        TenantMemberEntity.id != member.id,
                        TenantMemberEntity.id.in_([UUID(value) for value in roster.member_ids]),
                        TenantMemberEntity.role == "admin",
                        TenantMemberEntity.status.notin_(("offboarded", "pending")),
                        TenantMemberEntity.deleted_at.is_(None),
                    ).limit(1))
                    if other_administrator is None:
                        raise WorkflowError("Schedule a successor in the next cycle before changing this role", 409)
            member.role = role
            if previous_role != role:
                self._audit(
                    db,
                    tenant_id,
                    subject,
                    "tenant.member_role_updated",
                    {
                        "member_id": str(member.id),
                        "previous_role": previous_role,
                        "role": role,
                    },
                )
            if scope is not None or sign_company_only is not None:
                self._apply_member_document_scope(db, member, subject, scope, sign_company_only)
            db.flush()
            return self._team_read(db, tenant_id, actor)

    def update_member_access(
        self, tenant_id: UUID, member_id: UUID, action: str, subject: str
    ) -> TenantTeamRead:
        with SessionLocal.begin() as db:
            self._lock_team(db, tenant_id)
            actor = self.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True)
            member = db.scalar(select(TenantMemberEntity).where(
                TenantMemberEntity.id == member_id,
                TenantMemberEntity.tenant_id == tenant_id,
                TenantMemberEntity.deleted_at.is_(None),
            ).with_for_update())
            if member is None:
                raise WorkflowError("Member does not belong to this tenant", 404)
            if member.role == "admin":
                raise WorkflowError("An administrator cannot be offboarded through this action", 409)

            now = DateTimeService.utc_now()
            if action == "offboard":
                if member.status == "offboarded":
                    return self._team_read(db, tenant_id, actor)
                member.status = "offboarded"
                workspace_requests = select(SignatureRequestEntity.id).join(
                    DocumentEntity, DocumentEntity.id == SignatureRequestEntity.document_id
                ).where(DocumentEntity.tenant_id == tenant_id)
                db.execute(update(SignerEntity).where(
                    SignerEntity.signature_request_id.in_(workspace_requests),
                    or_(
                        func.lower(SignerEntity.auth_user_id) == member.auth_user_id.lower(),
                        func.lower(SignerEntity.email) == member.auth_user_id.lower(),
                    ),
                    SignerEntity.link_revoked_at.is_(None),
                ).values(link_revoked_at=now))
                rosters = db.scalars(select(TenantSeatRosterEntity).where(
                    TenantSeatRosterEntity.tenant_id == tenant_id,
                    TenantSeatRosterEntity.status == "scheduled",
                    TenantSeatRosterEntity.deleted_at.is_(None),
                ).with_for_update())
                for roster in rosters:
                    roster.member_ids = [value for value in roster.member_ids if value != str(member.id)]
            else:
                if member.status != "offboarded":
                    raise WorkflowError("Only an offboarded member can be readmitted", 409)
                limit = self.member_limit(db, tenant_id)
                active = db.scalar(select(func.count(TenantMemberEntity.id)).where(
                    TenantMemberEntity.tenant_id == tenant_id,
                    TenantMemberEntity.status == "active",
                    TenantMemberEntity.deleted_at.is_(None),
                )) or 0
                member.status = "without_seat" if limit is not None and active >= limit else "active"
                if action == "fresh":
                    member.role = "member"
                    member.joined_at = now
                    member.own_files_since = now
                    member.document_scope = "own"
                    member.sign_company_only = False
            self._audit(db, tenant_id, subject, "tenant.member_access_changed", {
                "member_id": str(member.id), "action": action, "status": member.status,
            })
            db.flush()
            return self._team_read(db, tenant_id, actor)

    def update_document_scope(
        self, tenant_id: UUID, member_id: UUID, scope: str | None, subject: str, *, sign_company_only: bool | None = None
    ) -> TenantTeamRead:
        with SessionLocal.begin() as db:
            self._lock_team(db, tenant_id)
            actor = self.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True)
            member = db.scalar(
                select(TenantMemberEntity).where(
                    TenantMemberEntity.id == member_id,
                    TenantMemberEntity.tenant_id == tenant_id,
                    TenantMemberEntity.deleted_at.is_(None),
                ).with_for_update()
            )
            if member is None:
                raise WorkflowError("Member does not belong to this tenant", 404)
            self._apply_member_document_scope(db, member, subject, scope, sign_company_only)
            db.flush()
            return self._team_read(db, tenant_id, actor)

    def _apply_member_document_scope(
        self, db, member: TenantMemberEntity, subject: str,
        scope: str | None, sign_company_only: bool | None,
    ) -> None:
        tenant_id = member.tenant_id
        if member.role == "admin":
            raise WorkflowError("Administrators already have full workspace access", 409)
        previous = member.document_scope
        previous_signing = member.sign_company_only
        if scope is not None:
            member.document_scope = scope
        if sign_company_only is not None:
            tenant = db.get(TenantEntity, tenant_id)
            if tenant is None or tenant.kind != "business":
                raise WorkflowError("Company signing restrictions require a business workspace", 409)
            member.sign_company_only = sign_company_only
        if previous != member.document_scope or previous_signing != member.sign_company_only:
            self._audit(db, tenant_id, subject, "tenant.member_permissions_updated", {
                "member_id": str(member.id), "previous_scope": previous, "scope": member.document_scope,
                "previous_sign_company_only": previous_signing, "sign_company_only": member.sign_company_only,
            })

    def convert_to_business(
        self,
        tenant_id: UUID,
        payload: TenantBusinessConversion,
        subject: str,
    ) -> TenantRead:
        with SessionLocal.begin() as db:
            member = self.require_role(db, tenant_id, subject, {"admin"})
            tenant = db.scalar(
                select(TenantEntity)
                .where(TenantEntity.id == tenant_id, TenantEntity.deleted_at.is_(None))
                .with_for_update()
            )
            if tenant is None:
                raise WorkflowError("Tenant not found", 404)
            if tenant.kind == "business":
                raise WorkflowError("Tenant is already a business tenant", 409)
            from core_api.modules.billing.billing_service import billing_service

            if not billing_service.business_features_enabled(db, tenant_id):
                raise WorkflowError("A Professional or Team plan is required for a business tenant", 403)
            try:
                encrypted, lookup, masked = protect_cnpj(payload.cnpj)
            except InvalidBusinessIdentifierError as exc:
                raise WorkflowError(str(exc), 422) from exc
            conflict = db.scalar(
                select(TenantEntity.id).where(
                    TenantEntity.registration_lookup_hmac == lookup,
                    TenantEntity.deleted_at.is_(None),
                    TenantEntity.id != tenant_id,
                )
            )
            if conflict is not None:
                raise WorkflowError("This CNPJ is already associated with another tenant", 409)
            tenant.kind = "business"
            tenant.name = payload.legal_name.strip()
            tenant.legal_name = payload.legal_name.strip()
            tenant.registration_country = "BR"
            tenant.registration_type = "BR_CNPJ"
            tenant.registration_value_encrypted = encrypted
            tenant.registration_lookup_hmac = lookup
            tenant.registration_masked = masked
            tenant.registration_verification_status = "format_valid"
            db.flush()
            self._audit(db, tenant.id, subject, "tenant.converted_to_business", {"registration_country": "BR", "registration_type": "BR_CNPJ", "registration_masked": masked, "verification_status": "format_valid"})
            return self._read(tenant, member.role)

    def apply_billing_business_identity(
        self,
        db,
        tenant_id: UUID,
        *,
        legal_name: str | None,
        cnpj: str | None,
        provider_reference: str | None,
    ) -> str:
        tenant = db.scalar(
            select(TenantEntity)
            .where(
                TenantEntity.id == tenant_id,
                TenantEntity.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if tenant is None:
            raise WorkflowError("Tenant not found", 404)
        if tenant.registration_source == "manual_review":
            return tenant.registration_verification_status or "format_valid"
        tenant.registration_source = "stripe"
        tenant.registration_provider_reference = provider_reference
        if not cnpj:
            tenant.registration_verification_status = "stripe_cnpj_required"
            return tenant.registration_verification_status
        try:
            encrypted, lookup, masked = protect_cnpj(cnpj)
        except InvalidBusinessIdentifierError:
            tenant.registration_verification_status = "stripe_cnpj_invalid"
            return tenant.registration_verification_status
        if tenant.kind == "business" and tenant.registration_lookup_hmac != lookup:
            tenant.registration_verification_status = "stripe_cnpj_mismatch"
            return tenant.registration_verification_status
        conflict = db.scalar(
            select(TenantEntity.id).where(
                TenantEntity.registration_lookup_hmac == lookup,
                TenantEntity.deleted_at.is_(None),
                TenantEntity.id != tenant_id,
            )
        )
        if conflict is not None:
            tenant.registration_verification_status = "stripe_cnpj_conflict"
            return tenant.registration_verification_status
        normalized_name = (legal_name or "").strip()
        if not normalized_name:
            tenant.registration_verification_status = "stripe_name_required"
            return tenant.registration_verification_status
        was_personal = tenant.kind == "personal"
        tenant.kind = "business"
        tenant.name = normalized_name
        tenant.legal_name = normalized_name
        tenant.registration_country = "BR"
        tenant.registration_type = "BR_CNPJ"
        tenant.registration_value_encrypted = encrypted
        tenant.registration_lookup_hmac = lookup
        tenant.registration_masked = masked
        tenant.registration_verification_status = "stripe_format_valid"
        if was_personal:
            self._audit(
                db,
                tenant.id,
                "stripe",
                "tenant.converted_to_business_from_billing",
                {
                    "registration_country": "BR",
                    "registration_type": "BR_CNPJ",
                    "registration_masked": masked,
                    "verification_status": tenant.registration_verification_status,
                    "provider_reference": provider_reference,
                },
            )
        return tenant.registration_verification_status

    @staticmethod
    def issuer_snapshot(tenant: TenantEntity) -> dict[str, object]:
        return {
            "tenant_id": str(tenant.id),
            "tenant_kind": tenant.kind,
            "display_name": tenant.name,
            "legal_name": tenant.legal_name,
            "registration_country": tenant.registration_country,
            "registration_type": tenant.registration_type,
            "registration_masked": tenant.registration_masked,
            "registration_verification_status": tenant.registration_verification_status,
        }

    def update_preferences(
        self,
        tenant_id: UUID,
        payload: TenantPreferencesUpdate,
        subject: str,
    ) -> TenantRead:
        with SessionLocal.begin() as db:
            member = self.require_role(db, tenant_id, subject, {"admin"})
            tenant = db.get(TenantEntity, tenant_id)
            if tenant is None or tenant.deleted_at is not None:
                raise WorkflowError("Tenant not found", 404)
            tenant.default_locale = payload.default_locale
            tenant.country_code = payload.country_code
            tenant.timezone = payload.timezone
            tenant.currency = payload.currency
            db.flush()
            return self._read(tenant, member.role)

    @staticmethod
    def organization_parent(tenant_id):
        branch = aliased(TenantEntity)
        parent = aliased(TenantEntity)
        return select(parent.id).join_from(parent, branch, branch.parent_workspace_id == parent.id).where(
            branch.id == tenant_id,
            branch.kind == "business",
            branch.status == "active",
            branch.deleted_at.is_(None),
            parent.kind == "business",
            parent.status == "active",
            parent.deleted_at.is_(None),
            parent.parent_workspace_id.is_(None),
        ).correlate(TenantEntity, DocumentEntity).scalar_subquery()

    @staticmethod
    def organization_admin_access(tenant_id, subject: str):
        return select(TenantMemberEntity.id).where(
            TenantMemberEntity.tenant_id == TenantService.organization_parent(tenant_id),
            TenantMemberEntity.role == "admin",
            TenantMemberEntity.status == "active",
            TenantMemberEntity.deleted_at.is_(None),
            TenantService.membership_identity_filter(subject),
        ).correlate_except(TenantMemberEntity).exists()

    @staticmethod
    def export_open(tenant: TenantEntity) -> bool:
        closed_at = tenant.workspace_closed_at
        return closed_at is not None and DateTimeService.utc_now() < (
            DateTimeService.to_utc(closed_at) + WORKSPACE_EXPORT_WINDOW
        )

    @staticmethod
    def require_role(db, tenant_id: UUID, subject: str, roles: set[str] | None = None, *, allow_over_limit: bool = False, allow_export: bool = False) -> TenantMemberEntity:
        member = db.scalar(select(TenantMemberEntity).where(
            or_(
                TenantMemberEntity.tenant_id == tenant_id,
                and_(
                    TenantMemberEntity.tenant_id == TenantService.organization_parent(tenant_id),
                    TenantMemberEntity.role == "admin",
                ),
            ),
            TenantService.membership_identity_filter(subject),
            TenantMemberEntity.deleted_at.is_(None),
            TenantMemberEntity.status == "active",
        ).order_by((TenantMemberEntity.role == "admin").desc(), (TenantMemberEntity.tenant_id == tenant_id).desc()).limit(1))
        if member is None or (roles is not None and member.role not in roles):
            raise WorkflowError("Tenant access denied", 403)
        tenant = db.get(TenantEntity, tenant_id)
        if tenant is not None and tenant.workspace_closed_at is not None:
            if allow_export and member.role == "admin" and TenantService.export_open(tenant):
                return member
            raise WorkflowError("Workspace is closed", 410)
        if not allow_over_limit and TenantService.team_over_limit(db, tenant_id):
            raise WorkflowError("Select the active team members for the current plan", 409)
        return member

    @staticmethod
    def membership_identity_filter(subject: str, user_id: UUID | None = None):
        context = active_auth_context()
        resolved_user_id = user_id
        if resolved_user_id is None and context is not None and context.user_id:
            try:
                resolved_user_id = UUID(context.user_id)
            except ValueError:
                resolved_user_id = None
        legacy = and_(
            TenantMemberEntity.auth_user_uuid.is_(None),
            TenantMemberEntity.auth_user_id == subject.lower(),
        )
        return or_(TenantMemberEntity.auth_user_uuid == resolved_user_id, legacy) if resolved_user_id else legacy

    @staticmethod
    def _read(tenant: TenantEntity, role: str, *, workspace_selectable: bool = False) -> TenantRead:
        return TenantRead(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            status=tenant.status,
            role=role,
            created_at=tenant.created_at,
            default_locale=tenant.default_locale,
            country_code=tenant.country_code,
            timezone=tenant.timezone,
            currency=tenant.currency,
            kind=tenant.kind,
            workspace_selectable=workspace_selectable,
            legal_name=tenant.legal_name,
            registration_country=tenant.registration_country,
            registration_type=tenant.registration_type,
            registration_masked=tenant.registration_masked,
            registration_verification_status=tenant.registration_verification_status,
        )

    @staticmethod
    def _audit(db, tenant_id: UUID, actor_id: str, action: str, metadata: dict[str, object]) -> None:
        db.add(AuditEventEntity(signature_request_id=None, occurred_at=DateTimeService.utc_now(), actor_type="user", actor_id=actor_id, action=action, entity_type="tenant", entity_id=tenant_id, correlation_id=uuid4(), metadata_sanitized=metadata))


tenant_service = TenantService()
