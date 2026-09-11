from datetime import timedelta
from hashlib import sha256
from secrets import token_urlsafe

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.infrastructure.settings import settings
from auth_api.modules.access_control.access_control_entity import UserRoleEntity
from auth_api.modules.accounts.account_schema import PublicRegistration
from auth_api.modules.accounts.tenant_client import provision_account_tenant
from auth_api.modules.accounts.notification_client import request_account_email
from auth_api.modules.users.passwords import hash_password
from auth_api.modules.users.user_entity import AccountTokenEntity, UserEntity
from auth_api.modules.users.user_identifier_service import add_identifier
from shared_kernel.time.datetime_service import DateTimeService


class AccountConflictError(Exception):
    pass


class InvalidAccountTokenError(Exception):
    pass


class AccountService:
    def register(self, payload: PublicRegistration) -> None:
        with SessionLocal.begin() as database:
            user = UserEntity(
                name=payload.name.strip(),
                email=payload.email.strip().lower(),
                password_hash=hash_password(payload.password),
                preferred_locale=payload.preferred_locale,
                email_verified=False,
                is_active=True,
            )
            database.add(user)
            try:
                database.flush()
            except IntegrityError as exc:
                raise AccountConflictError from exc
            database.add(UserRoleEntity(user_id=user.id, role="signature_admin"))
            if (
                payload.identity_document_type
                and payload.identity_document_country
                and payload.identity_document_value
            ):
                add_identifier(
                    database,
                    user_id=user.id,
                    issuing_country=payload.identity_document_country,
                    identifier_type=payload.identity_document_type,
                    value=payload.identity_document_value,
                )
                try:
                    database.flush()
                except IntegrityError as exc:
                    raise AccountConflictError from exc
            token = self._issue_token(
                database,
                user,
                "verify_email",
                settings.AUTH_EMAIL_VERIFICATION_TTL_SECONDS,
            )
            provision_account_tenant(payload)
            self._send_verification(user.email, token)

    def request_email_verification(self, email: str) -> None:
        with SessionLocal.begin() as database:
            user = self._user_by_email(database, email)
            if user is None or user.email_verified or not user.is_active:
                return
            token = self._issue_token(
                database,
                user,
                "verify_email",
                settings.AUTH_EMAIL_VERIFICATION_TTL_SECONDS,
            )
        self._send_verification(user.email, token)

    def verify_email(self, raw_token: str) -> None:
        with SessionLocal.begin() as database:
            token = self._consume_token(database, raw_token, "verify_email")
            user = database.get(UserEntity, token.user_id)
            if user is None:
                raise InvalidAccountTokenError
            user.email_verified = True

    def request_password_recovery(self, email: str) -> None:
        with SessionLocal.begin() as database:
            user = self._user_by_email(database, email)
            if user is None or not user.is_active:
                return
            token = self._issue_token(
                database,
                user,
                "reset_password",
                settings.AUTH_PASSWORD_RESET_TTL_SECONDS,
            )
        url = f"{settings.AUTH_PUBLIC_WEB_URL.rstrip('/')}/reset-password?token={token}"
        request_account_email(
            recipient=user.email,
            subject="Reset your Rubrica password",
            body=f"Use this link to reset your password: {url}",
            idempotency_key=f"password-reset:{self._digest(token)}",
            metadata={"template": "password_recovery", "recovery_url": url},
        )

    def reset_password(self, raw_token: str, new_password: str) -> None:
        with SessionLocal.begin() as database:
            token = self._consume_token(database, raw_token, "reset_password")
            user = database.get(UserEntity, token.user_id)
            if user is None:
                raise InvalidAccountTokenError
            user.password_hash = hash_password(new_password)
            user.token_version += 1

    def _send_verification(self, email: str, token: str) -> None:
        url = f"{settings.AUTH_PUBLIC_WEB_URL.rstrip('/')}/verify-email?token={token}"
        request_account_email(
            recipient=email,
            subject="Verify your Rubrica email",
            body=f"Use this link to verify your email: {url}",
            idempotency_key=f"email-verification:{self._digest(token)}",
            metadata={"template": "email_verification", "verification_url": url},
        )

    @staticmethod
    def _issue_token(database, user: UserEntity, purpose: str, ttl_seconds: int) -> str:
        database.execute(
            update(AccountTokenEntity)
            .where(
                AccountTokenEntity.user_id == user.id,
                AccountTokenEntity.purpose == purpose,
                AccountTokenEntity.consumed_at.is_(None),
            )
            .values(consumed_at=DateTimeService.utc_now())
        )
        raw_token = token_urlsafe(48)
        database.add(
            AccountTokenEntity(
                user_id=user.id,
                purpose=purpose,
                token_hash=AccountService._digest(raw_token),
                expires_at=DateTimeService.utc_now() + timedelta(seconds=ttl_seconds),
            )
        )
        return raw_token

    @staticmethod
    def _consume_token(database, raw_token: str, purpose: str) -> AccountTokenEntity:
        token = database.scalar(
            select(AccountTokenEntity)
            .where(
                AccountTokenEntity.token_hash == AccountService._digest(raw_token),
                AccountTokenEntity.purpose == purpose,
                AccountTokenEntity.consumed_at.is_(None),
                AccountTokenEntity.expires_at > DateTimeService.utc_now(),
                AccountTokenEntity.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if token is None:
            raise InvalidAccountTokenError
        token.consumed_at = DateTimeService.utc_now()
        return token

    @staticmethod
    def _user_by_email(database, email: str) -> UserEntity | None:
        return database.scalar(
            select(UserEntity)
            .where(
                UserEntity.email == email.strip().lower(),
                UserEntity.deleted_at.is_(None),
            )
            .limit(1)
        )

    @staticmethod
    def _digest(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()


account_service = AccountService()
