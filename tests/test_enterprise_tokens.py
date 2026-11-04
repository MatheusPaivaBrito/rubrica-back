from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from auth_api.modules.machine_credentials.tokens import IntegrationCredential, issue_token


def test_credentials_are_scoped_revocable_and_not_recoverable():
    token = issue_token(environment="production", sandbox=False)
    now = datetime.now(UTC)
    credential = IntegrationCredential(
        tenant_id=uuid4(), integration_id=uuid4(), compartment_id=uuid4(),
        environment="production", sandbox=False, digest=token.digest,
        scopes=frozenset({"documents:create"}), expires_at=now + timedelta(days=15),
    )
    arguments = dict(secret=token.secret, environment="production", sandbox=False,
                     permission="documents:create", now=now)
    assert credential.authorize(**arguments)
    assert token.secret not in repr(token)
    assert token.digest not in repr(credential)
    for changes in (
        {"environment": "staging"}, {"sandbox": True},
        {"permission": "documents:download"}, {"permission": "*"},
        {"secret": "invalid"}, {"now": credential.expires_at},
    ):
        assert not credential.authorize(**(arguments | changes))
    assert not replace(credential, enabled=False).authorize(**arguments)
    replacement = issue_token(environment="production", sandbox=False)
    rotated = replace(credential, digest=replacement.digest)
    assert not rotated.authorize(**arguments)
    assert rotated.authorize(**(arguments | {"secret": replacement.secret}))


def test_compartment_boundaries_cannot_be_crossed():
    credential = IntegrationCredential(
        tenant_id=uuid4(), integration_id=uuid4(), compartment_id=uuid4(),
        environment="staging", sandbox=True, digest="digest", scopes=frozenset(),
    )
    resource = dict(tenant_id=credential.tenant_id,
                    integration_id=credential.integration_id,
                    compartment_id=credential.compartment_id)
    assert credential.permits_resource(**resource)
    for key in resource:
        assert not credential.permits_resource(**(resource | {key: uuid4()}))


def test_unknown_environment_is_rejected():
    with pytest.raises(ValueError):
        issue_token(environment="unknown", sandbox=True)


def test_rotation_persists_only_digest_and_rolls_back_atomically(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from auth_api.modules.machine_credentials.entity import (
        MachineCredentialEntity, MachineCredentialAuditEntity,
    )
    from auth_api.modules.machine_credentials.service import CredentialError, rotate_token

    engine = create_engine("sqlite://")
    MachineCredentialEntity.__table__.create(engine)
    MachineCredentialAuditEntity.__table__.create(engine)
    tenant_id, integration_id = uuid4(), uuid4()
    with Session(engine) as db:
        db.add(MachineCredentialEntity(
            id=integration_id, integration_id=integration_id, tenant_id=tenant_id,
            environment="staging", sandbox=True,
        ))
        db.commit()
        args = dict(tenant_id=tenant_id, integration_id=integration_id,
                    subject="admin@example.com", scopes=frozenset({"usage:read"}),
                    environment="staging", sandbox=True,
                    expires_at=None, now=datetime.now(UTC))
        first = rotate_token(db, **args)
        db.commit()
        second = rotate_token(db, **args)
        assert db.get(MachineCredentialEntity, integration_id).digest == second.digest
        db.rollback()
        assert db.get(MachineCredentialEntity, integration_id).digest == first.digest
        second = rotate_token(db, **args)
        db.commit()
        from sqlalchemy import select
        audits = db.scalars(select(MachineCredentialAuditEntity)).all()
        assert len(audits) == 2
        assert all(not hasattr(audit, "digest") for audit in audits)
        with pytest.raises(CredentialError, match="not found"):
            rotate_token(db, **(args | {"tenant_id": uuid4()}))
        db.rollback()
        from auth_api.modules.machine_credentials.service import authenticate_token, revoke_token
        authentication = dict(secret=second.secret, environment="staging",
                              sandbox=True, permission="usage:read", now=args["now"])
        context = authenticate_token(db, **authentication)
        assert context.tenant_id == tenant_id
        assert context.integration_id == integration_id
        for changes in ({"secret": first.secret}, {"sandbox": False},
                        {"environment": "production"},
                        {"permission": "documents:download"},
                        {"secret": "invalid"},
                        {"secret": second.secret[:-1] + "!"}):
            with pytest.raises(CredentialError):
                authenticate_token(db, **(authentication | changes))
        revocation = dict(tenant_id=tenant_id, integration_id=integration_id,
                          environment="staging", sandbox=True, subject=args["subject"])
        with pytest.raises(CredentialError):
            revoke_token(db, **(revocation | {"tenant_id": uuid4()}))
        revoke_token(db, **revocation)
        db.commit()
        with pytest.raises(CredentialError):
            authenticate_token(db, **authentication)
        revoke_token(db, **revocation)
        db.commit()
        assert len(db.scalars(select(MachineCredentialAuditEntity)).all()) == 3
