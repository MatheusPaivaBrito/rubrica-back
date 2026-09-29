"""Reset MFA for an existing account without deleting the user or its data."""

import argparse

from sqlalchemy import delete, select

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.modules.users.user_entity import (
    MfaRecoveryCodeEntity,
    MfaSecurityEventEntity,
    UserEntity,
)


def _required(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must have at most {maximum} characters")
    return normalized


def reset_mfa(*, email: str, actor: str, reason: str) -> bool:
    email = _required(email, "email", 255).lower()
    actor = _required(actor, "actor", 255).lower()
    reason = _required(reason, "reason", 500)
    with SessionLocal.begin() as database:
        user = database.scalar(
            select(UserEntity)
            .where(
                UserEntity.email == email,
                UserEntity.deleted_at.is_(None),
                UserEntity.is_active.is_(True),
            )
            .with_for_update()
        )
        if user is None:
            raise ValueError(f"Active user {email} was not found")
        changed = bool(
            user.mfa_enabled
            or user.mfa_secret_ciphertext
            or user.mfa_pending_secret_ciphertext
            or user.mfa_last_used_step is not None
        )
        user.mfa_enabled = False
        user.mfa_exempt = False
        user.mfa_secret_ciphertext = None
        user.mfa_pending_secret_ciphertext = None
        user.mfa_last_used_step = None
        user.token_version += 1
        database.execute(
            delete(MfaRecoveryCodeEntity).where(MfaRecoveryCodeEntity.user_id == user.id)
        )
        database.add(
            MfaSecurityEventEntity(
                user_id=user.id,
                action="mfa.operator_reset",
                metadata_sanitized={"actor": actor, "reason": reason},
            )
        )
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset MFA and require enrollment again without deleting the account."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        changed = reset_mfa(email=args.email, actor=args.actor, reason=args.reason)
    except ValueError as exc:
        parser.error(str(exc))
    result = "reset" if changed else "already disabled; sessions rotated"
    print(f"[ok] MFA {result} for {args.email.strip().lower()}; enrollment required")


if __name__ == "__main__":
    main()
