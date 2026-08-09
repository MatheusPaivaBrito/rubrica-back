import hmac


def verify_service_token(received: str, expected: str) -> bool:
    return hmac.compare_digest(received, expected)
