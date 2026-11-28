"""Auth QA with synthetic users, PostgreSQL and namespaced Redis."""

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from http.cookies import SimpleCookie
from statistics import median
from threading import Barrier, Event
from time import perf_counter
from types import SimpleNamespace
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete, event, select
from sqlalchemy.exc import OperationalError

from auth_api.infrastructure.database.connection import SessionLocal, engine
from auth_api.infrastructure.settings import settings
from auth_api.main import app
from auth_api.modules.access_control.access_control_entity import UserRoleEntity
from auth_api.modules.accounts import account_service as accounts
from auth_api.modules.sessions import session_service as sessions
from auth_api.modules.sessions.session_schema import LoginRequest
from auth_api.modules.users.passwords import hash_password
from auth_api.modules.users.user_entity import AccountTokenEntity, UserEntity
from core_api.infrastructure import auth_context
from core_api.infrastructure.database.connection import SessionLocal as CoreSession
from core_api.main import app as core_app
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_identity import protect_cnpj
from shared_kernel.time.datetime_service import DateTimeService


pytestmark = pytest.mark.skipif(
    os.getenv("RUBRICA_DATABASE_TESTS") != "1" or not os.getenv("RUBRICA_TEST_REDIS_URL"),
    reason="requires isolated PostgreSQL and Redis",
)
PASSWORD = "Synthetic-Login-9"
NEW_PASSWORD = "Synthetic-Changed-8"


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def qa(monkeypatch, password_hash):
    prefix = f"rubrica-qa-auth-{uuid4().hex}"
    redis = Redis.from_url(os.environ["RUBRICA_TEST_REDIS_URL"], decode_responses=True)
    monkeypatch.setattr(settings, "AUTH_REDIS_KEY_PREFIX", prefix)
    monkeypatch.setattr(settings, "AUTH_MFA_REQUIRED", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(sessions.session_service, "_redis", redis)
    with SessionLocal.begin() as db:
        users = [UserEntity(email=f"qa-{uuid4().hex}@example.test", password_hash=password_hash,
                            is_active=True, email_verified=True) for _ in range(2)]
        db.add_all(users)
        db.flush()
    try:
        with TestClient(app, base_url="https://qa.example.test", raise_server_exceptions=False) as http:
            yield SimpleNamespace(redis=redis, prefix=prefix, users=users, http=http, service=sessions.session_service)
    finally:
        keys = list(redis.scan_iter(f"{prefix}:*"))
        if keys:
            redis.delete(*keys)
        redis.close()
        with SessionLocal.begin() as db:
            db.execute(delete(UserEntity).where(UserEntity.id.in_([user.id for user in users])))


def login(qa, email=None, password=PASSWORD, **kwargs):
    return qa.http.post("/auth/login", json={"email": email or qa.users[0].email, "password": password}, **kwargs)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def issue_reset(user, *, deadline=None):
    with SessionLocal.begin() as db:
        token = accounts.account_service._issue_token(db, user, "reset_password", 120)
        if deadline is not None:
            db.flush()
            row = db.scalar(select(AccountTokenEntity).filter_by(token_hash=accounts.AccountService._digest(token)))
            row.expires_at = deadline
    return token


def reset(qa, token, **extra):
    return qa.http.post("/auth/password-reset", json={"token": token, "new_password": NEW_PASSWORD, **extra})


@pytest.mark.parametrize("case", ["01", "02", "04", "08", "09", "10-soft", "10-deleted"])
def test_denied_login_preserves_identity_and_sessions(qa, case):
    user = qa.users[0]
    email, password = user.email, PASSWORD
    if case == "01":
        password = "Synthetic-Wrong-9"
    elif case == "02":
        email = "missing@example.test"
    elif case == "04":
        email = "qa'quoted;literal@example.test"
    elif case == "08":
        email = email.replace("@example", "@exаmple")  # Cyrillic a
    elif case in {"09", "10-soft", "10-deleted"}:
        with SessionLocal.begin() as db:
            row = db.get(UserEntity, user.id)
            if case == "09":
                row.is_active = False
            elif case == "10-soft":
                row.deleted_at = DateTimeService.utc_now()
            else:
                db.delete(row)
    response = login(qa, email, password)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert not list(qa.redis.scan_iter(f"{qa.prefix}:session:*"))
    with SessionLocal() as db:
        rows = list(db.scalars(select(UserEntity).where(UserEntity.id.in_([u.id for u in qa.users]))))
        assert len(rows) == (1 if case == "10-deleted" else 2)
        assert all(row.password_hash == user.password_hash and row.token_version == 1 for row in rows)


def test_login_timing_exercises_bcrypt_for_known_and_unknown_identity(qa, monkeypatch, record_property):
    original = sessions.verify_password
    checks = []

    def checked(password, stored_hash):
        checks.append(True)
        return original(password, stored_hash)

    monkeypatch.setattr(sessions, "verify_password", checked)
    times = {"known": [], "unknown": []}
    for _ in range(5):
        for state, email in (("known", qa.users[0].email), ("unknown", "missing@example.test")):
            start = perf_counter()
            response = login(qa, email, "Synthetic-Wrong-9")
            times[state].append((perf_counter() - start) * 1000)
            assert response.status_code == 401
    for state, samples in times.items():
        record_property(f"{state}_median_ms", round(median(samples), 1))
    assert len(checks) == 10
    assert not list(qa.redis.scan_iter(f"{qa.prefix}:session:*"))


@pytest.mark.parametrize("field", ["email", "password"])
def test_oversized_login_is_rejected_without_session_or_input_echo(qa, field):
    marker = "synthetic-private-value-" * 150
    body = {"email": qa.users[0].email, "password": PASSWORD, field: marker}
    response = qa.http.post("/auth/login", json=body)
    assert response.status_code == 422
    assert marker[:40] not in response.text
    assert all("input" not in error for error in response.json()["detail"])
    assert not list(qa.redis.scan_iter(f"{qa.prefix}:*"))


@pytest.mark.parametrize("case", ["uppercase", "whitespace"])
def test_normalized_login_maps_to_the_original_identity(qa, case):
    user = qa.users[0]
    response = login(qa, user.email.upper() if case == "uppercase" else f" {user.email} ")
    assert response.status_code == 200
    state = qa.service._state_for_token("access", response.json()["access_token"])
    assert state["user_id"] == str(user.id)


@pytest.mark.parametrize("header", ["x-forwarded-for", "x-real-ip", "cf-connecting-ip"])
def test_changing_origin_header_cannot_reset_account_limit(qa, header):
    email = qa.users[0].email
    rate_key = qa.service._token_key("login-attempts", email)
    qa.redis.set(rate_key, "9", ex=300)
    assert login(qa, email, "Synthetic-Wrong-9", headers={header: "192.0.2.2"}).status_code == 401
    assert login(qa, email.upper(), headers={header: "198.51.100.2"}).status_code == 401
    assert qa.redis.get(rate_key) == "11"
    assert not list(qa.redis.scan_iter(f"{qa.prefix}:session:*"))


def test_redis_failure_does_not_fall_back_to_unlimited_login(qa, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RedisConnectionError("synthetic Redis connection failure")

    def forbidden_db():
        pytest.fail("Login continued to PostgreSQL without the rate limiter")

    with monkeypatch.context() as changes:
        changes.setattr(qa.service, "_redis", SimpleNamespace(incr=unavailable, eval=unavailable))
        changes.setattr(sessions, "SessionLocal", forbidden_db)
        assert login(qa).status_code == 500
    assert not list(qa.redis.scan_iter(f"{qa.prefix}:session:*"))
    assert login(qa).status_code == 200


def test_rate_limit_has_a_deadline_after_legacy_interrupted_increment(qa):
    key = qa.service._token_key("login-attempts", qa.users[0].email)
    qa.redis.set(key, "10")
    assert login(qa).status_code == 401
    assert 0 < qa.redis.ttl(key) <= 300


def test_login_recovers_after_window_expires(qa):
    key = qa.service._token_key("login-attempts", qa.users[0].email)
    qa.redis.set(key, "10", ex=300)
    assert login(qa).status_code == 401
    qa.redis.pexpireat(key, 1)
    assert login(qa).status_code == 200
    assert not qa.redis.exists(key)


def test_two_login_instances_share_the_rate_limit(qa):
    email = qa.users[0].email
    key = qa.service._token_key("login-attempts", email)
    qa.redis.set(key, "9", ex=300)
    start = Barrier(2)

    def attempt():
        service = sessions.SessionService()
        service._redis = qa.redis
        start.wait(timeout=5)
        return service.login(LoginRequest(email=email, password=PASSWORD))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sum(bool(result) for result in results) == 1
    assert len(list(qa.redis.scan_iter(f"{qa.prefix}:session:*"))) == 1


@pytest.mark.parametrize("variant", ["subject", "permissions", "unknown", "refresh"])
def test_altered_or_wrong_purpose_token_cannot_authenticate(qa, variant):
    tokens = qa.service._create_session(qa.users[0])
    supplied = {
        "subject": tokens.access_token + str(qa.users[1].id),
        "permissions": tokens.access_token + ".signature_admin",
        "unknown": qa.service._new_token("access"),
        "refresh": tokens.refresh_token,
    }[variant]
    assert qa.http.get("/sessions/me", headers=bearer(supplied)).status_code == 401
    assert qa.http.get("/sessions/me", headers=bearer(tokens.access_token)).status_code == 200


def test_expired_access_index_cannot_use_live_session_state(qa):
    tokens = qa.service._create_session(qa.users[0])
    key = qa.service._token_key("access", tokens.access_token)
    assert 0 < qa.redis.ttl(key) <= settings.AUTH_ACCESS_TTL_SECONDS
    qa.redis.pexpireat(key, 1)
    assert qa.redis.exists(qa.service._session_key(tokens.session_id))
    assert qa.http.get("/sessions/me", headers=bearer(tokens.access_token)).status_code == 401
    assert qa.service.refresh(tokens.refresh_token) is not None


def test_environment_storage_separates_staging_and_simulated_production(qa):
    tokens = qa.service._create_session(qa.users[0])
    assert qa.service.current_session(tokens.access_token) is not None
    production = sessions.SessionService()
    connection = qa.redis.connection_pool.connection_kwargs
    db = (int(connection.get("db", 0)) + 1) % 16
    with Redis(host=connection["host"], port=connection["port"], db=db, decode_responses=True) as redis:
        production._redis = redis
        assert production.current_session(tokens.access_token) is None
        assert production.refresh(tokens.refresh_token) is None
    assert qa.service.current_session(tokens.access_token) is not None


def test_parallel_refresh_issues_at_most_one_new_session_pair(qa, monkeypatch):
    tokens = qa.service._create_session(qa.users[0])
    start = Barrier(2)
    evaluate = qa.redis.eval

    def simultaneous(*args):
        start.wait(timeout=5)
        return evaluate(*args)

    with monkeypatch.context() as changes:
        changes.setattr(qa.redis, "eval", simultaneous)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(qa.service.refresh, [tokens.refresh_token] * 2))
    winner, = (result for result in results if result is not None)
    assert winner.session_id == tokens.session_id
    assert qa.service.current_session(winner.access_token) is not None
    assert qa.service.current_session(tokens.access_token) is None
    assert len(qa.redis.smembers(qa.service._user_sessions_key(qa.users[0].id))) == 1


@pytest.mark.parametrize("scheme", ["Bearer", "bearer"])
def test_logout_revokes_access_and_refresh_with_either_bearer_case(qa, scheme):
    tokens = qa.service._create_session(qa.users[0])
    assert qa.http.post("/auth/logout", headers={"Authorization": f"{scheme} {tokens.access_token}"}).status_code == 200
    assert qa.service.current_session(tokens.access_token) is None
    assert qa.service.refresh(tokens.refresh_token) is None
    assert not qa.redis.smembers(qa.service._user_sessions_key(qa.users[0].id))


@pytest.mark.parametrize("lifecycle", ["deactivated", "soft_deleted", "unverified"])
def test_session_resolves_current_account_lifecycle(qa, lifecycle):
    tokens = qa.service._create_session(qa.users[0])
    with SessionLocal.begin() as db:
        row = db.get(UserEntity, qa.users[0].id)
        if lifecycle == "deactivated":
            row.is_active = False
        elif lifecycle == "soft_deleted":
            row.deleted_at = DateTimeService.utc_now()
        else:
            row.email_verified = False
    assert qa.http.get("/sessions/me", headers=bearer(tokens.access_token)).status_code == 401
    assert qa.service.refresh(tokens.refresh_token) is None


def test_password_reset_revokes_two_prior_sessions_and_leaves_other_user_active(qa):
    user, other = qa.users
    stale = [qa.service._create_session(user) for _ in range(2)]
    unaffected = qa.service._create_session(other)
    assert reset(qa, issue_reset(user)).status_code == 200
    for tokens in stale:
        assert qa.service.current_session(tokens.access_token) is None
        assert qa.service.refresh(tokens.refresh_token) is None
    assert qa.service.current_session(unaffected.access_token) is not None
    assert login(qa).status_code == 401
    assert login(qa, password=NEW_PASSWORD).status_code == 200


def test_authentication_does_not_adopt_a_prelogin_cookie(qa):
    unrelated = qa.service._create_session(qa.users[1])
    qa.http.cookies.set("access_token", unrelated.access_token)
    response = login(qa)
    assert response.status_code == 200
    assert response.json()["session_id"] != unrelated.session_id
    assert qa.service.current_session(response.json()["access_token"]).subject == qa.users[0].email
    assert qa.service.current_session(unrelated.access_token).subject == qa.users[1].email


def test_consumed_recovery_link_cannot_be_used_twice(qa):
    user = qa.users[0]
    token = issue_reset(user)
    assert reset(qa, token).status_code == 200
    assert reset(qa, token).status_code == 422
    with SessionLocal() as db:
        assert db.get(UserEntity, user.id).token_version == 2
        assert db.scalar(select(AccountTokenEntity).filter_by(user_id=user.id)).consumed_at is not None


def test_expired_recovery_link_does_not_change_password_or_consume_link(qa):
    user = qa.users[0]
    token = issue_reset(user, deadline=DateTimeService.utc_now() - timedelta(seconds=1))
    assert reset(qa, token).status_code == 422
    with SessionLocal() as db:
        stored = db.get(UserEntity, user.id)
        assert stored.token_version == 1 and stored.password_hash == user.password_hash
        assert db.scalar(select(AccountTokenEntity).filter_by(user_id=user.id)).consumed_at is None


def test_two_password_resets_with_one_token_update_once(qa):
    user = qa.users[0]
    token = issue_reset(user)
    start = Barrier(2)

    def attempt():
        start.wait(timeout=5)
        try:
            accounts.account_service.reset_password(token, NEW_PASSWORD)
        except accounts.InvalidAccountTokenError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == [False, True]
    with SessionLocal() as db:
        assert db.get(UserEntity, user.id).token_version == 2
        assert db.scalar(select(AccountTokenEntity).filter_by(user_id=user.id)).consumed_at is not None


def test_concurrent_recovery_issuance_leaves_only_one_unused_token(qa, monkeypatch):
    user = qa.users[0]
    first_issued, let_first_commit = Event(), Event()
    issue = accounts.AccountService._issue_token

    def pause_first(db, identity, purpose, ttl_seconds):
        token = issue(db, identity, purpose, ttl_seconds)
        if not first_issued.is_set():
            first_issued.set()
            assert let_first_commit.wait(5)
        return token

    monkeypatch.setattr(accounts.AccountService, "_issue_token", staticmethod(pause_first))
    deliveries = []
    monkeypatch.setattr(accounts, "request_account_email", lambda **message: deliveries.append(message["recipient"]))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(accounts.account_service.request_password_recovery, user.email)
        try:
            assert first_issued.wait(5)
            second = pool.submit(accounts.account_service.request_password_recovery, user.email)
            try:
                second.result(timeout=0.5)
            except TimeoutError:
                pass
        finally:
            let_first_commit.set()
        first.result(timeout=5)
        second.result(timeout=5)
    with SessionLocal() as db:
        records = list(db.scalars(select(AccountTokenEntity).filter_by(user_id=user.id)))
        assert len(records) == 2 and sum(record.consumed_at is None for record in records) == 1
    assert deliveries == [user.email, user.email]


def test_recovery_request_cannot_override_token_owner(qa):
    user, other = qa.users
    response = reset(qa, issue_reset(user), email=other.email, user_id=str(other.id))
    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.get(UserEntity, user.id).token_version == 2
        assert db.get(UserEntity, other.id).token_version == 1
        assert db.get(UserEntity, other.id).password_hash == other.password_hash


def test_production_cookie_scope_and_flags(qa, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr("auth_api.modules.sessions.session_router.verify_login_turnstile", lambda *_args: None)
    response = login(qa)
    assert response.status_code == 200
    assert "refresh_token" not in response.json()
    cookies = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        cookies.load(header)
    assert set(cookies) == {"access_token", "refresh_token"}
    for cookie in cookies.values():
        assert cookie["secure"] and cookie["httponly"]
        assert cookie["samesite"].lower() == "lax"
        assert cookie["path"] == "/" and not cookie["domain"]


def test_cross_origin_cookie_request_cannot_revoke_a_valid_session(qa, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_PUBLIC_WEB_URL", "https://qa.example.test")
    tokens = qa.service._create_session(qa.users[0])
    qa.http.cookies.set("access_token", tokens.access_token)
    assert qa.http.post("/auth/logout", headers={"Origin": "https://outside.example.test"}).status_code == 403
    assert qa.service.current_session(tokens.access_token) is not None
    assert qa.http.post("/auth/logout", headers={"Origin": "https://qa.example.test"}).status_code == 200
    assert qa.service.current_session(tokens.access_token) is None


def test_postgres_connection_failure_does_not_issue_session(qa):
    engine.dispose()

    def unavailable(*_args):
        raise OperationalError(None, None, ConnectionRefusedError("synthetic PostgreSQL outage"))

    event.listen(engine, "do_connect", unavailable)
    try:
        assert login(qa).status_code == 500
    finally:
        event.remove(engine, "do_connect", unavailable)
    assert not list(qa.redis.scan_iter(f"{qa.prefix}:session:*"))
    assert not list(qa.redis.scan_iter(f"{qa.prefix}:access:*"))
    assert login(qa).status_code == 200


def test_interrupted_session_write_leaves_no_partial_indexes(qa, monkeypatch):
    original_set, original_pipeline = qa.redis.set, qa.redis.pipeline

    def interrupt_second_write(key, *args, **kwargs):
        if ":access:" in key:
            raise RedisConnectionError("synthetic interruption before access write")
        return original_set(key, *args, **kwargs)

    def interrupted_transaction(*args, **kwargs):
        pipeline = original_pipeline(*args, **kwargs)

        def unavailable():
            raise RedisConnectionError("synthetic interruption before EXEC")

        pipeline.execute = unavailable
        return pipeline

    with monkeypatch.context() as changes:
        changes.setattr(qa.redis, "set", interrupt_second_write)
        changes.setattr(qa.redis, "pipeline", interrupted_transaction)
        assert login(qa).status_code == 500
    for kind in ("session", "access", "refresh", "user"):
        assert not list(qa.redis.scan_iter(f"{qa.prefix}:{kind}:*"))
    replacement = sessions.SessionService()
    replacement._redis = qa.redis
    tokens = replacement.login(LoginRequest(email=qa.users[0].email, password=PASSWORD))
    assert replacement.current_session(tokens.access_token) is not None


@pytest.mark.parametrize(("path", "body"), [
    ("/auth/login", {"email": "qa@example.test", "password": "Q-9"}),
    ("/auth/password-reset", {"token": "short-reset", "new_password": "weak"}),
    ("/auth/mfa/challenge", {"mfa_ticket": "short-ticket", "code": "123"}),
    ("/auth/refresh", {"refresh_token": "short-refresh"}),
])
def test_auth_validation_does_not_echo_secrets_or_log_request_bodies(qa, monkeypatch, path, body):
    messages = []
    monkeypatch.setattr("logging.Logger.info", lambda _logger, message, *_args: messages.append(str(message)))
    response = qa.http.post(path, json=body)
    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])
    for key, supplied in body.items():
        if key != "email":
            assert supplied not in response.text
            assert all(supplied not in message for message in messages)


def test_new_password_beyond_bcrypt_byte_limit_is_rejected_before_consuming_token(qa):
    user = qa.users[0]
    token = issue_reset(user)
    password = "Aa1!" + "á" * 36
    response = qa.http.post("/auth/password-reset", json={"token": token, "new_password": password})
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.get(UserEntity, user.id).token_version == 1
        assert db.scalar(select(AccountTokenEntity).filter_by(user_id=user.id)).consumed_at is None
    assert reset(qa, token).status_code == 200


@pytest.fixture
def workspace_qa(qa, monkeypatch):
    first, second = qa.users
    with SessionLocal.begin() as db:
        db.add_all(UserRoleEntity(user_id=user.id, role="signature_admin") for user in qa.users)
    with CoreSession.begin() as db:
        workspaces = [TenantEntity(name=f"QA workspace {position}", slug=f"qa-auth-{uuid4().hex}",
                                   country_code="BR") for position in (1, 2)]
        db.add_all(workspaces)
        db.flush()
        memberships = [TenantMemberEntity(tenant_id=tenant.id, auth_user_id=user.email, role="admin", status="active")
                       for tenant, user in zip(workspaces, qa.users, strict=True)]
        db.add_all(memberships)
        db.flush()
    tokens = [qa.service._create_session(user) for user in (first, second)]

    class AuthTransport:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return json.dumps(self.payload).encode()

    def resolve(request, **_kwargs):
        response = qa.http.get("/access-control/context", headers={"Authorization": request.headers["Authorization"]})
        if response.status_code != 200:
            raise HTTPError(request.full_url, response.status_code, "QA Auth refused", {}, None)
        return AuthTransport(response.json())

    monkeypatch.setattr(auth_context, "urlopen", resolve)
    try:
        with TestClient(core_app, raise_server_exceptions=False) as http:
            yield SimpleNamespace(http=http, workspaces=workspaces, memberships=memberships, tokens=tokens)
    finally:
        with CoreSession.begin() as db:
            ids = [tenant.id for tenant in workspaces]
            db.execute(delete(BillingAccountEntity).where(BillingAccountEntity.tenant_id.in_(ids)))
            db.execute(delete(TenantMemberEntity).where(TenantMemberEntity.tenant_id.in_(ids)))
            db.execute(delete(TenantEntity).where(TenantEntity.id.in_(ids)))


def test_same_session_loses_workspace_access_after_offboarding(workspace_qa):
    tenant = workspace_qa.workspaces[0]
    account = workspace_qa.tokens[0]
    request = f"/tenants/{tenant.id}/members"
    assert workspace_qa.http.get(request, headers=bearer(account.access_token)).status_code == 200
    with CoreSession.begin() as db:
        db.get(TenantMemberEntity, workspace_qa.memberships[0].id).status = "offboarded"
    assert workspace_qa.http.get(request, headers=bearer(account.access_token)).status_code == 403
    assert workspace_qa.http.get("/tenants", headers=bearer(account.access_token)).status_code == 200


def test_same_session_loses_admin_permission_after_role_change(workspace_qa):
    tenant = workspace_qa.workspaces[0]
    account = workspace_qa.tokens[0]
    request = f"/tenants/{tenant.id}/members"
    assert workspace_qa.http.get(request, headers=bearer(account.access_token)).status_code == 200
    with CoreSession.begin() as db:
        db.get(TenantMemberEntity, workspace_qa.memberships[0].id).role = "member"
    assert workspace_qa.http.get(request, headers=bearer(account.access_token)).status_code == 403
    assert workspace_qa.http.get("/tenants", headers=bearer(account.access_token)).status_code == 200


def test_valid_session_cannot_select_another_workspace(workspace_qa):
    first, second = workspace_qa.workspaces
    first_token, second_token = workspace_qa.tokens
    for tenant, owner, outsider in ((first, first_token, second_token), (second, second_token, first_token)):
        endpoint = f"/tenants/{tenant.id}/members"
        assert workspace_qa.http.get(endpoint, headers=bearer(owner.access_token)).status_code == 200
        assert workspace_qa.http.get(endpoint, headers=bearer(outsider.access_token)).status_code == 403


def test_parallel_workspace_writes_keep_destinations_separate(workspace_qa, qa):
    first, second = workspace_qa.workspaces
    encrypted, lookup, masked = protect_cnpj("11.222.333/0001-81")
    with CoreSession.begin() as db:
        business = db.get(TenantEntity, second.id)
        business.kind = "business"
        business.legal_name = "Synthetic QA Company"
        business.registration_country = "BR"
        business.registration_type = "BR_CNPJ"
        business.registration_value_encrypted = encrypted
        business.registration_lookup_hmac = lookup
        business.registration_masked = masked
        db.add(BillingAccountEntity(tenant_id=second.id, status="active", current_product_code="rubrica_team"))
        db.add(TenantMemberEntity(tenant_id=second.id, auth_user_id=qa.users[0].email, role="admin", status="active"))
    access = workspace_qa.tokens[0].access_token
    together = Barrier(2)

    def write(tenant, locale):
        together.wait(timeout=5)
        with TestClient(core_app, raise_server_exceptions=False) as http:
            return http.patch(f"/tenants/{tenant.id}/preferences", headers=bearer(access), json={
                "default_locale": locale, "country_code": "BR", "timezone": "UTC", "currency": "BRL",
            })

    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(write, first, "pt-BR"), pool.submit(write, second, "ja-JP")]
        assert [result.result(timeout=10).status_code for result in requests] == [200, 200]
    with CoreSession() as db:
        assert db.get(TenantEntity, first.id).default_locale == "pt-BR"
        assert db.get(TenantEntity, second.id).default_locale == "ja-JP"
