"""Origin check for browser requests authenticated by cookies."""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def require_same_origin(request: Request, public_web_url: str, environment: str) -> None:
    if environment.lower() not in {"production", "prod"}:
        return
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    expected = urlsplit(public_web_url)
    actual = urlsplit(origin)
    if actual.scheme != expected.scheme or actual.netloc != expected.netloc:
        raise HTTPException(status_code=403, detail="Cross-origin cookie request is forbidden")
