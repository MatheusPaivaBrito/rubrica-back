"""Interactive staging-only shortcuts for seat and entitlement tests."""

from argparse import ArgumentParser
from datetime import timedelta

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.billing.plan_catalog import CATALOG, ESSENTIAL, FREE, PROFESSIONAL, TEAM
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantSeatRosterEntity
from core_api.modules.tenant.tenant_service import tenant_service
from shared_kernel.time.datetime_service import DateTimeService

TEST_PLANS = {
    "Gratuito": FREE,
    "Essencial": ESSENTIAL,
    "Profissional": PROFESSIONAL,
    "Equipe": TEAM,
}
ACTOR = "staging-billing-tool"


def choose[T](title: str, options: dict[str, T]) -> T:
    if not options:
        raise SystemExit("Nenhuma opção disponível para esta operação.")
    choices = list(options.items())
    print(title)
    for number, (label, _) in enumerate(choices, 1):
        print(f"  {number}. {label}")
    choice = input("Número (Enter cancela): ").strip()
    if not choice.isascii() or not choice.isdecimal() or not 1 <= int(choice) <= len(choices):
        raise SystemExit("Operação cancelada.")
    return choices[int(choice) - 1][1]


def pending_roster(db, account: BillingAccountEntity) -> TenantSeatRosterEntity | None:
    return db.scalar(
        select(TenantSeatRosterEntity)
        .where(
            TenantSeatRosterEntity.tenant_id == account.tenant_id,
            TenantSeatRosterEntity.cycle_starts_at == account.current_period_ends_at,
            TenantSeatRosterEntity.status == "scheduled",
            TenantSeatRosterEntity.deleted_at.is_(None),
        )
        .with_for_update()
    )


def apply_cycle(db, account: BillingAccountEntity) -> None:
    roster = pending_roster(db, account)
    if roster is None:
        raise SystemExit("Esse workspace não tem seleção pendente para o próximo ciclo.")
    tenant_service.apply_due_seat_roster(db, account.tenant_id, through=roster.cycle_starts_at)
    tenant_service._audit(
        db, account.tenant_id, ACTOR, "tenant.staging_seat_roster_applied",
        {"cycle_starts_at": roster.cycle_starts_at.isoformat()},
    )


def set_test_plan(db, account: BillingAccountEntity, plan: str) -> None:
    if (
        account.provider not in (None, "fake")
        or account.provider_customer_id
        or account.provider_subscription_id
        or account.pending_change_kind
        or account.pending_provider_invoice_id
        or account.complimentary_lifetime
    ):
        raise SystemExit("Use um workspace de teste sem vínculo Stripe, mudança pendente ou plano vitalício.")
    if pending_roster(db, account) is not None:
        raise SystemExit("Aplique a seleção pendente de assentos antes de trocar o plano de teste.")

    previous = account.current_product_code
    now = DateTimeService.utc_now()
    account.provider = "fake"
    account.status = "not_configured" if plan == FREE else "active"
    account.current_product_code = None if plan == FREE else plan
    account.contracted_seats = CATALOG[plan].included_seats
    account.usage_period_starts_at = account.usage_period_starts_at or now
    account.current_period_ends_at = account.current_period_ends_at or now + timedelta(days=30)
    db.flush()
    tenant_service.reconcile_single_member_plan(db, account.tenant_id)
    tenant_service._audit(
        db, account.tenant_id, ACTOR, "billing.staging_test_plan_changed",
        {"previous_plan": previous, "plan": plan},
    )


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("operation", choices=("staging-apply-next-cycle", "staging-set-test-plan"))
    operation = parser.parse_args().operation
    if settings.ENVIRONMENT != "staging":
        raise SystemExit("Operação exclusiva de staging.")

    cycle = operation == "staging-apply-next-cycle"
    accounts = select(TenantEntity, BillingAccountEntity).join(
        BillingAccountEntity, BillingAccountEntity.tenant_id == TenantEntity.id
    ).where(TenantEntity.deleted_at.is_(None), BillingAccountEntity.deleted_at.is_(None))
    candidates = accounts
    if cycle:
        candidates = candidates.join(
            TenantSeatRosterEntity,
            TenantSeatRosterEntity.tenant_id == TenantEntity.id,
        ).where(
            TenantSeatRosterEntity.cycle_starts_at == BillingAccountEntity.current_period_ends_at,
            TenantSeatRosterEntity.status == "scheduled",
            TenantSeatRosterEntity.deleted_at.is_(None),
        )

    with SessionLocal() as db:
        rows = db.execute(candidates.order_by(TenantEntity.name, TenantEntity.id)).all()
        options = {f"{tenant.name} · {tenant.slug}": tenant.id for tenant, _ in rows}

    tenant_id = choose("Escolha o workspace de staging:", options)
    plan = None if cycle else choose("Escolha o plano de teste:", TEST_PLANS)
    with SessionLocal.begin() as db:
        row = db.execute(
            accounts.where(TenantEntity.id == tenant_id).with_for_update(of=BillingAccountEntity)
        ).one_or_none()
        if row is None:
            raise SystemExit("Workspace não encontrado.")
        _, account = row
        if plan is None:
            apply_cycle(db, account)
        else:
            set_test_plan(db, account, plan)
    print("[ok] Alteração aplicada no staging.")


if __name__ == "__main__":
    main()
