from starlette.requests import Request

from core_api.modules.signature_request.signature_request_router import _client_ip


def test_signature_ip_uses_normalized_proxy_address_not_forwarded_chain() -> None:
    request = Request({
        "type": "http", "method": "POST", "path": "/signing/links/token/sign",
        "headers": [(b"x-real-ip", b"2001:db8::42"), (b"x-forwarded-for", b"10.0.0.1, 172.18.0.2")],
        "client": ("172.18.0.3", 1234),
    })
    assert _client_ip(request) == "2001:db8::42"


def test_signature_ip_ignores_invalid_header() -> None:
    request = Request({
        "type": "http", "method": "POST", "path": "/signing/links/token/sign",
        "headers": [(b"x-real-ip", b"not-an-ip"), (b"x-forwarded-for", b"203.0.113.9")],
        "client": ("172.18.0.3", 1234),
    })
    assert _client_ip(request) == "unknown"
