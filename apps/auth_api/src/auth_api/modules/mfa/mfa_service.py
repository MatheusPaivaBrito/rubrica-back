from secrets import token_hex

import pyotp
from sqlalchemy import delete, func, select

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.infrastructure.settings import settings
from auth_api.modules.mfa.mfa_crypto import decrypt_secret, encrypt_secret
from auth_api.modules.users.passwords import hash_password, verify_password
from auth_api.modules.access_control.access_control_service import access_control_service
from auth_api.modules.users.user_entity import (
    MfaRecoveryCodeEntity,
    MfaSecurityEventEntity,
    UserEntity,
)
from shared_kernel.time.datetime_service import DateTimeService


class MfaError(Exception):
    pass


class MfaService:
    def setup(self, subject: str) -> tuple[str, str]:
        secret = pyotp.random_base32()
        with SessionLocal.begin() as database:
            user = self._user(database, subject)
            user.mfa_pending_secret_ciphertext = encrypt_secret(secret)
            self.audit(database, user, "mfa.setup_started")
        uri = pyotp.TOTP(secret).provisioning_uri(
            name=subject,
            issuer_name=settings.AUTH_MFA_ISSUER,
        )
        return secret, uri

    def confirm(self, subject: str, code: str) -> list[str]:
        with SessionLocal.begin() as database:
            user = self._user(database, subject)
            if not user.mfa_pending_secret_ciphertext:
                raise MfaError("MFA setup has not been started")
            secret = decrypt_secret(user.mfa_pending_secret_ciphertext)
            if not self._verify_totp(secret, code):
                raise MfaError("MFA code is invalid")
            user.mfa_secret_ciphertext = user.mfa_pending_secret_ciphertext
            user.mfa_pending_secret_ciphertext = None
            user.mfa_enabled = True
            user.mfa_last_used_step = pyotp.TOTP(secret).timecode(DateTimeService.utc_now())
            database.execute(
                delete(MfaRecoveryCodeEntity).where(MfaRecoveryCodeEntity.user_id == user.id)
            )
            recovery_codes = [token_hex(5).upper() for _ in range(8)]
            database.add_all(
                [
                    MfaRecoveryCodeEntity(user_id=user.id, code_hash=hash_password(item))
                    for item in recovery_codes
                ]
            )
            self.audit(database, user, "mfa.enabled")
        return recovery_codes

    def status(self, subject: str) -> tuple[bool, bool, bool, int]:
        with SessionLocal() as database:
            user = self._user(database, subject)
            roles, _ = access_control_service.context_for_user(user.id)
            remaining = database.scalar(
                select(func.count(MfaRecoveryCodeEntity.id)).where(
                    MfaRecoveryCodeEntity.user_id == user.id,
                    MfaRecoveryCodeEntity.consumed_at.is_(None),
                    MfaRecoveryCodeEntity.deleted_at.is_(None),
                )
            )
            required = bool({"signature_admin", "signature_operator"} & set(roles))
            return user.mfa_enabled, required, required and not user.mfa_enabled, int(remaining or 0)

    def regenerate_recovery_codes(self, subject: str, password: str, code: str) -> list[str]:
        with SessionLocal.begin() as database:
            user = self._user(database, subject)
            if not verify_password(password, user.password_hash):
                raise MfaError("Password is invalid")
            if not user.mfa_enabled or not self.verify_user_code(database, user, code):
                raise MfaError("MFA code is invalid")
            database.execute(
                delete(MfaRecoveryCodeEntity).where(MfaRecoveryCodeEntity.user_id == user.id)
            )
            recovery_codes = [token_hex(5).upper() for _ in range(8)]
            database.add_all(
                [MfaRecoveryCodeEntity(user_id=user.id, code_hash=hash_password(item)) for item in recovery_codes]
            )
            self.audit(database, user, "mfa.recovery_codes_regenerated")
            return recovery_codes

    def disable(self, subject: str, password: str, code: str) -> None:
        with SessionLocal.begin() as database:
            user = self._user(database, subject)
            roles, _ = access_control_service.context_for_user(user.id)
            if {"signature_admin", "signature_operator"} & set(roles):
                raise MfaError("MFA is required for this role")
            if not verify_password(password, user.password_hash):
                raise MfaError("Password is invalid")
            if not user.mfa_enabled or not self.verify_user_code(database, user, code):
                raise MfaError("MFA code is invalid")
            user.mfa_enabled = False
            user.mfa_secret_ciphertext = None
            user.mfa_pending_secret_ciphertext = None
            user.mfa_last_used_step = None
            database.execute(
                delete(MfaRecoveryCodeEntity).where(MfaRecoveryCodeEntity.user_id == user.id)
            )
            self.audit(database, user, "mfa.disabled")

    def verify_user_code(self, database, user: UserEntity, code: str) -> bool:
        normalized = code.replace("-", "").replace(" ", "").upper()
        if user.mfa_secret_ciphertext:
            secret = decrypt_secret(user.mfa_secret_ciphertext)
            totp = pyotp.TOTP(secret)
            if totp.verify(normalized, valid_window=1):
                step = totp.timecode(DateTimeService.utc_now())
                if user.mfa_last_used_step is not None and step <= user.mfa_last_used_step:
                    return False
                user.mfa_last_used_step = step
                return True
        recovery_codes = database.scalars(
            select(MfaRecoveryCodeEntity).where(
                MfaRecoveryCodeEntity.user_id == user.id,
                MfaRecoveryCodeEntity.consumed_at.is_(None),
                MfaRecoveryCodeEntity.deleted_at.is_(None),
            )
        ).all()
        for recovery in recovery_codes:
            if verify_password(normalized, recovery.code_hash):
                recovery.consumed_at = DateTimeService.utc_now()
                return True
        return False

    @staticmethod
    def audit(database, user: UserEntity, action: str) -> None:
        database.add(
            MfaSecurityEventEntity(
                user_id=user.id,
                action=action,
                metadata_sanitized={},
            )
        )

    @staticmethod
    def _verify_totp(secret: str, code: str) -> bool:
        return pyotp.TOTP(secret).verify(code.replace(" ", ""), valid_window=1)

    @staticmethod
    def _user(database, subject: str) -> UserEntity:
        user = database.scalar(
            select(UserEntity)
            .where(UserEntity.email == subject.lower(), UserEntity.deleted_at.is_(None))
            .limit(1)
        )
        if user is None:
            raise MfaError("User not found")
        return user


mfa_service = MfaService()
