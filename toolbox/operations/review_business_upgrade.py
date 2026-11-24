"""Review CNPJ requests from a trusted operator shell."""

from argparse import ArgumentParser
from uuid import UUID

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.business_upgrade_review import (
    BusinessUpgradeReviewEntity,
    record_decision,
)


def main() -> None:
    parser = ArgumentParser()
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list-pending")
    decision = actions.add_parser("decide")
    decision.add_argument("review_id", type=UUID)
    decision.add_argument("decision", choices=("approved", "rejected"))
    decision.add_argument("--operator", required=True)
    args = parser.parse_args()
    if args.action == "list-pending":
        with SessionLocal() as db:
            rows = db.execute(
                select(
                    BusinessUpgradeReviewEntity.id,
                    BusinessUpgradeReviewEntity.legal_name,
                    BusinessUpgradeReviewEntity.cnpj_masked,
                ).where(
                    BusinessUpgradeReviewEntity.status == "pending",
                    BusinessUpgradeReviewEntity.deleted_at.is_(None),
                ).order_by(BusinessUpgradeReviewEntity.created_at)
            )
            for review_id, name, masked in rows:
                print(f"{review_id}\t{name!r}\t{masked}")
        return
    operator = args.operator.strip()
    if not operator or len(operator) > 255:
        parser.error("Informe a identificação do operador.")
    try:
        record_decision(args.review_id, args.decision, operator)
    except WorkflowError as exc:
        raise SystemExit(str(exc)) from exc
    print("[ok] Decisão registrada.")


if __name__ == "__main__":
    main()
