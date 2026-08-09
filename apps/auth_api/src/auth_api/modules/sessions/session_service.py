from __future__ import annotations

import json
from hashlib import sha256
from secrets import token_urlsafe

from redis import Redis
from sqlalchemy import select

from auth_api.infrastructure.database.connection import SessionLocal
from auth_api.infrastructure.settings import settings
from auth_api.modules.sessions.session_schema import (
    LoginRequest,
    LoginResponse,
    SessionRead,
    UiContextResponse,
)
from auth_api.modules.access_control.access_control_service import access_control_service
from auth_api.modules.users.passwords import verify_password
from auth_api.modules.users.user_entity import UserEntity


class SessionService:
    def __init__(self) -> None:
        self._redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )

    def login(self, payload: LoginRequest) -> LoginResponse | None:
        with SessionLocal() as database:
            user = database.scalar(
                select(UserEntity)
                .where(UserEntity.email == payload.email.strip().lower())
                .limit(1)
            )
            if user is None or not user.is_active:
                return None
            if not verify_password(payload.password, user.password_hash):
                return None
            return self._create_session(user)

    def refresh(self, refresh_token: str) -> LoginResponse | None:
        state = self._state_for_token("refresh", refresh_token)
        if state is None or not self._user_is_active(state["user_id"]):
            return None
        self._redis.delete(state["access_key"], state["refresh_key"])
        return self._create_session_from_state(state)

    def current_session(self, access_token: str) -> SessionRead | None:
        state = self._state_for_token("access", access_token)
        if state is None or not self._user_is_active(state["user_id"]):
            return None
        return SessionRead(session_id=state["session_id"], subject=state["subject"])

    def logout(self, access_token: str) -> bool:
        state = self._state_for_token("access", access_token)
        if state is None:
            return False
        self._revoke_state(state)
        return True

    def logout_all(self, access_token: str) -> bool:
        state = self._state_for_token("access", access_token)
        if state is None:
            return False
        for session_id in self._redis.smembers(self._user_sessions_key(state["user_id"])):
            stored = self._load_state(session_id)
            if stored is not None:
                self._revoke_state(stored)
        self._redis.delete(self._user_sessions_key(state["user_id"]))
        return True

    def ui_context(self, token: str) -> UiContextResponse | None:
        session = self.current_session(token)
        if session is None:
            return None
        state = self._state_for_token("access", token)
        if state is None:
            return None
        roles, permission_keys = access_control_service.context_for_user(int(state["user_id"]))
        fingerprint = sha256(f"{session.subject}:{session.session_id}".encode("utf-8")).hexdigest()
        return UiContextResponse(
            subject=session.subject,
            roles=roles,
            permission_keys=permission_keys,
            capability_hash=fingerprint,
        )

    def _create_session(self, user: UserEntity) -> LoginResponse:
        return self._store_session(
            session_id=token_urlsafe(18),
            user_id=user.id,
            subject=user.email,
        )

    def _create_session_from_state(self, state: dict[str, object]) -> LoginResponse:
        self._redis.delete(self._session_key(str(state["session_id"])))
        return self._store_session(
            session_id=str(state["session_id"]),
            user_id=int(state["user_id"]),
            subject=str(state["subject"]),
        )

    def _store_session(self, *, session_id: str, user_id: int, subject: str) -> LoginResponse:
        access_token = self._new_token("access")
        refresh_token = self._new_token("refresh")
        state = {
            "session_id": session_id,
            "user_id": user_id,
            "subject": subject,
            "access_key": self._token_key("access", access_token),
            "refresh_key": self._token_key("refresh", refresh_token),
        }
        payload = json.dumps(state)
        self._redis.set(self._session_key(session_id), payload, ex=settings.AUTH_SESSION_TTL_SECONDS)
        self._redis.set(state["access_key"], session_id, ex=settings.AUTH_ACCESS_TTL_SECONDS)
        self._redis.set(state["refresh_key"], session_id, ex=settings.AUTH_SESSION_TTL_SECONDS)
        self._redis.sadd(self._user_sessions_key(user_id), session_id)
        self._redis.expire(self._user_sessions_key(user_id), settings.AUTH_SESSION_TTL_SECONDS)
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            session_id=session_id,
        )

    def _state_for_token(self, kind: str, token: str) -> dict[str, object] | None:
        session_id = self._redis.get(self._token_key(kind, token))
        return self._load_state(session_id) if session_id else None

    def _load_state(self, session_id: str | None) -> dict[str, object] | None:
        if not session_id:
            return None
        value = self._redis.get(self._session_key(session_id))
        return json.loads(value) if value else None

    def _revoke_state(self, state: dict[str, object]) -> None:
        self._redis.delete(
            str(state["access_key"]),
            str(state["refresh_key"]),
            self._session_key(str(state["session_id"])),
        )
        self._redis.srem(self._user_sessions_key(int(state["user_id"])), str(state["session_id"]))

    @staticmethod
    def _new_token(kind: str) -> str:
        return f"{kind}_{token_urlsafe(32)}"

    @staticmethod
    def _session_key(session_id: str) -> str:
        return f"{settings.AUTH_REDIS_KEY_PREFIX}:session:{session_id}"

    @staticmethod
    def _user_sessions_key(user_id: int) -> str:
        return f"{settings.AUTH_REDIS_KEY_PREFIX}:user:{user_id}:sessions"

    @staticmethod
    def _token_key(kind: str, token: str) -> str:
        digest = sha256(token.encode("utf-8")).hexdigest()
        return f"{settings.AUTH_REDIS_KEY_PREFIX}:{kind}:{digest}"

    @staticmethod
    def _user_is_active(user_id: object) -> bool:
        with SessionLocal() as database:
            user = database.get(UserEntity, int(user_id))
            return user is not None and user.is_active


session_service = SessionService()
