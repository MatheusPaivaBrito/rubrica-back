from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from auth_api.modules.users.user_entity import (
    MfaRecoveryCodeEntity,
    MfaSecurityEventEntity,
    UserEntity,
)
from toolbox.seeds import reset_mfa as module


def test_operator_reset_preserves_user_and_requires_new_enrollment(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    for entity in (UserEntity, MfaRecoveryCodeEntity, MfaSecurityEventEntity):
        entity.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(module, "SessionLocal", factory)
    with factory.begin() as database:
        user = UserEntity(
            email="owner@example.com",
            name="Owner",
            password_hash="unchanged",
            is_active=True,
            email_verified=True,
            mfa_enabled=True,
            mfa_exempt=False,
            mfa_secret_ciphertext="encrypted-secret",
            mfa_pending_secret_ciphertext="pending-secret",
            mfa_last_used_step=10,
            token_version=4,
        )
        database.add(user)
        database.flush()
        database.add(MfaRecoveryCodeEntity(user_id=user.id, code_hash="hash"))
        user_id = user.id

    assert module.reset_mfa(
        email=" OWNER@example.com ",
        actor="operator@example.com",
        reason="Lost authenticator",
    )

    with factory() as database:
        user = database.get(UserEntity, user_id)
        assert user is not None
        assert user.password_hash == "unchanged"
        assert user.is_active and user.email_verified
        assert not user.mfa_enabled and not user.mfa_exempt
        assert user.mfa_secret_ciphertext is None
        assert user.mfa_pending_secret_ciphertext is None
        assert user.mfa_last_used_step is None
        assert user.token_version == 5
        assert database.scalar(select(MfaRecoveryCodeEntity)) is None
        event = database.scalar(select(MfaSecurityEventEntity))
        assert event.action == "mfa.operator_reset"
        assert event.metadata_sanitized == {
            "actor": "operator@example.com",
            "reason": "Lost authenticator",
        }
