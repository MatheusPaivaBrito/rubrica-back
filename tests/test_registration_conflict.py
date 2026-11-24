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
                json={
                    "name": "Example User", "email": "user@example.test",
                    "country_code": "BR", "identity_document_country": "PT",
                    "identity_document_type": "PASSPORT", "identity_document_value": "TR1234567",
                },
            )

    response = asyncio.run(register())

    assert response.status_code == 409
    assert response.json() == {"detail": "E-mail or identity document is already registered"}

def test_registration_rejects_missing_country_or_document_before_service(monkeypatch):
    def unexpected_registration(_payload):
        raise AssertionError("Invalid registration must not call the service")

    monkeypatch.setattr(account_router.account_service, "register", unexpected_registration)
    app = FastAPI()
    app.include_router(account_router.router)
    payload = {
        "name": "Example User", "email": "user@example.test",
        "country_code": "BR", "identity_document_country": "PT",
        "identity_document_type": "PASSPORT", "identity_document_value": "TR1234567",
    }

    async def register():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for field in ("country_code", "identity_document_country", "identity_document_type", "identity_document_value"):
                response = await client.post("/auth/register", json=payload | {field: None})
                assert response.status_code == 422

    asyncio.run(register())
