import asyncio
from dataclasses import dataclass
import json
import ssl

import httpx


@dataclass
class Result:
    code: int | None
    reason: str
    payload: dict | None = None
    retry_after: str | None = None
    server_date: str | None = None


def failure_reason(code, headers, *, query=False):
    if 300 <= code < 400 or (code in {401, 403} and ("text/html" in headers.get("content-type", "") or "cf-mitigated" in headers)):
        return "access_denied"
    if code == 401:
        return "credential_denied"
    if code == 403:
        return "scope_denied"
    return "http_error"


async def exchange(client, method, url, headers, *, body=None, query=False, limit=2*1024*1024):
    code = None
    try:
        async with asyncio.timeout(10):
            async with client.stream(method, url, headers=headers, content=body) as response:
                code = response.status_code
                if not 200 <= code < 300:
                    return Result(code, failure_reason(code, response.headers, query=query),
                        retry_after=response.headers.get("retry-after"), server_date=response.headers.get("date"))
                if "text/html" in response.headers.get("content-type", ""):
                    return Result(code, "access_denied")
                content = bytearray()
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content) > limit:
                        return Result(code, "response_limit")
                if not content:
                    return Result(code, "ok", {})
                value = json.loads(content)
                return Result(code, "ok", value if isinstance(value, dict) else None)
    except (TimeoutError, httpx.TimeoutException):
        return Result(None, "timeout")
    except (httpx.RequestError, ssl.SSLError) as error:
        current = error
        while current:
            if isinstance(current, ssl.SSLError):
                return Result(None, "tls_error")
            current = current.__cause__
        return Result(None, "connection")
    except (ValueError, UnicodeError):
        return Result(code, "invalid_response")
