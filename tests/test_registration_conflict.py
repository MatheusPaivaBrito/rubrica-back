import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from auth_api.modules.accounts import account_router
from auth_api.modules.accounts.account_service import AccountConflictError


def test_public_registration_returns_shared_conflict_message(monkeypatch):
    def duplicate(_payload):
        raise AccountConflictError("private conflict detail")

    monkeypatch.setattr(account_router, "verify_turnstile", lambda *_args: None)
    monkeypatch.setattr(account_router.account_service, "register", duplicate)
    app = FastAPI()
    app.include_router(account_router.router)

    async def register():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                "/auth/register",
                json={"name": "Example User", "email": "user@example.test"},
            )

    response = asyncio.run(register())

    assert response.status_code == 409
    assert response.json() == {"detail": "E-mail or identity document is already registered"}
