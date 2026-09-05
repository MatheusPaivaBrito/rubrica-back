from datetime import UTC, datetime
from uuid import uuid4

from http_client import print_result, request_json, service_url


def main() -> None:
    base_url = service_url("EVENTING_API_URL", "EVENTING_API_PORT", "8102")
    payload = {
        "event_id": str(uuid4()),
        "event_type": "example.event",
        "occurred_at": datetime.now(UTC).isoformat(),
        "source": "smoke",
        "version": 1,
        "payload": {
            "message": "hello from smoke-eventing-events",
        },
    }
    status_code, body = request_json("POST", f"{base_url}/events", payload=payload)
    print_result("eventing register event", status_code, body)


if __name__ == "__main__":
    main()
