"""Record the result of an operator's manual review of a CNPJ request."""

from argparse import ArgumentParser
from uuid import UUID

from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.business_upgrade_review import record_decision


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("review_id", type=UUID)
    parser.add_argument("decision", choices=("approved", "rejected"))
    parser.add_argument("--operator", required=True)
    args = parser.parse_args()
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
