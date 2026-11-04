from uuid import uuid4

from core_api.modules.enterprise.telemetry import record_operational


def measured_chunks(stream, context, expected_size):
    """Measure bytes yielded by the server, not client acknowledgement of delivery."""
    sent = 0
    source = uuid4()
    try:
        while chunk := stream.read(256 * 1024):
            sent += len(chunk)
            yield chunk
    finally:
        stream.close()
        record_operational(context, "download.completed" if sent == expected_size else "download.partial",
                           source, bytes_count=sent)
