from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class GrafanaStatus:
    available: bool
    version: str | None = None
    reason: str | None = None


class GrafanaClient:
    def __init__(self, *, base_url: str, timeout_seconds: float, service_token: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._service_token = service_token

    async def status(self) -> GrafanaStatus:
        headers = {"Authorization": f"Bearer {self._service_token}"} if self._service_token else {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(f"{self._base_url}/api/health", headers=headers)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            return GrafanaStatus(available=False, reason=f"http_{exc.response.status_code}")
        except httpx.TimeoutException:
            return GrafanaStatus(available=False, reason="timeout")
        except httpx.RequestError:
            return GrafanaStatus(available=False, reason="connection")
        except ValueError:
            return GrafanaStatus(available=False, reason="invalid_response")
        version = payload.get("version")
        return GrafanaStatus(
            available=True,
            version=version if isinstance(version, str) else None,
        )
