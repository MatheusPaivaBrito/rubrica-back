"""Audit Auth accounts and provision a personal tenant when membership is missing.

The command is dry-run by default. Run it with ``--apply`` from an environment
that can reach both the Auth and Core PostgreSQL databases.
"""

import argparse

from sqlalchemy import select

from auth_api.infrastructure.database.connection import SessionLocal as AuthSessionLocal
from auth_api.modules.users.user_entity import UserEntity
from core_api.infrastructure.database.connection import SessionLocal as CoreSessionLocal
from core_api.modules.tenant.tenant_entity import TenantMemberEntity
from core_api.modules.tenant.tenant_schema import TenantProvision
from core_api.modules.tenant.tenant_service import tenant_service


def accounts_without_tenant() -> list[tuple[str, str, object, str, str | None]]:
    with AuthSessionLocal() as auth_database:
        users = auth_database.execute(
            select(
                UserEntity.email,
                UserEntity.name,
                UserEntity.id,
                UserEntity.preferred_locale,
            ).where(UserEntity.deleted_at.is_(None))
        ).all()

    emails = [email.lower() for email, *_ in users]
    with CoreSessionLocal() as core_database:
        existing = set(
            core_database.scalars(
                select(TenantMemberEntity.auth_user_id).where(
                    TenantMemberEntity.auth_user_id.in_(emails),
                    TenantMemberEntity.deleted_at.is_(None),
                )
            )
        )
    return [
        (email.lower(), name or email.split("@", 1)[0], user_id, locale, None)
        for email, name, user_id, locale in users
        if email.lower() not in existing
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ensure every Rubrica Auth account belongs to at least one tenant."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Provision missing personal tenants. Without this flag, only report them.",
    )
    args = parser.parse_args()

    missing = accounts_without_tenant()
    for email, name, user_id, locale, country_code in missing:
        print(f"[missing] {email}")
        if args.apply:
            tenant = tenant_service.provision_owner(
                TenantProvision(
                    owner_user_id=user_id,
                    owner_email=email,
                    name=name,
                    default_locale=locale,
                    country_code=country_code,
                )
            )
            print(f"[created] tenant={tenant.slug}")
    print(f"[ok] missing={len(missing)} applied={args.apply}")


if __name__ == "__main__":
    main()
