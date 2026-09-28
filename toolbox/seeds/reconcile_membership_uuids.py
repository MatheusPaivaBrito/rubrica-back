"""Backfill Core tenant memberships with stable UUIDs from Auth.

Dry-run is the default. Use ``--apply`` only during the final migration window.
"""

import argparse

from sqlalchemy import select

from auth_api.infrastructure.database.connection import SessionLocal as AuthSessionLocal
from auth_api.modules.users.user_entity import UserEntity
from core_api.infrastructure.database.connection import SessionLocal as CoreSessionLocal
from core_api.modules.tenant.tenant_entity import TenantMemberEntity


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill stable Auth UUIDs in tenant memberships.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with AuthSessionLocal() as auth_database:
        users = {
            email.lower(): user_id
            for email, user_id in auth_database.execute(
                select(UserEntity.email, UserEntity.id).where(UserEntity.deleted_at.is_(None))
            )
        }

    missing_users: list[str] = []
    changed = 0
    with CoreSessionLocal.begin() as core_database:
        memberships = core_database.scalars(
            select(TenantMemberEntity).where(TenantMemberEntity.deleted_at.is_(None))
        ).all()
        for membership in memberships:
            expected = users.get(membership.auth_user_id.lower())
            if expected is None:
                missing_users.append(membership.auth_user_id)
                continue
            if membership.auth_user_uuid == expected:
                continue
            if membership.auth_user_uuid is not None and membership.auth_user_uuid != expected:
                raise RuntimeError(
                    f"Membership {membership.id} UUID conflicts with Auth for {membership.auth_user_id}"
                )
            print(f"[backfill] membership={membership.id} email={membership.auth_user_id}")
            if args.apply:
                membership.auth_user_uuid = expected
            changed += 1
        if not args.apply:
            core_database.rollback()

    for email in sorted(set(missing_users)):
        print(f"[missing-auth-user] {email}")
    print(
        f"[ok] candidates={changed} missing_auth_users={len(set(missing_users))} applied={args.apply}"
    )


if __name__ == "__main__":
    main()
