"""Create the local development administrator only when explicitly requested."""

import os

from sqlalchemy import select

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.modules.access_control.access_control_entity import UserRoleEntity
from auth_api.modules.users.passwords import hash_password
from auth_api.modules.users.user_entity import UserEntity


def main() -> None:
    email = os.getenv("AUTH_SEED_ADMIN_EMAIL", "admin@example.local").strip().lower()
    password = os.getenv("AUTH_SEED_ADMIN_PASSWORD", "")
    if len(password) < 8:
        raise ValueError("AUTH_SEED_ADMIN_PASSWORD must be set and have at least 8 characters")
    with SessionLocal.begin() as database:
        user = database.scalar(select(UserEntity).where(UserEntity.email == email))
        if user is None:
            user = UserEntity(email=email, password_hash=hash_password(password), is_active=True)
            database.add(user)
            database.flush()
        role = database.scalar(select(UserRoleEntity).where(UserRoleEntity.user_id == user.id, UserRoleEntity.role == "signature_admin"))
        if role is None:
            database.add(UserRoleEntity(user_id=user.id, role="signature_admin"))
    print(f"[ok] local signature administrator is ready: {email}")


if __name__ == "__main__":
    main()
