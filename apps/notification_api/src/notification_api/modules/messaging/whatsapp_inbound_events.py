from __future__ import annotations

import orjson
from aiokafka import AIOKafkaProducer

from notification_api.infrastructure.settings import settings


class WhatsappInboundPublisher:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        if not settings.NOTIFICATION_KAFKA_ENABLED or self._producer is not None:
            return
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.NOTIFICATION_KAFKA_BOOTSTRAP_SERVERS,
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, payload: dict[str, object]) -> None:
        if self._producer is None:
            raise RuntimeError("WhatsApp event publisher is unavailable")
        await self._producer.send_and_wait(
            settings.NOTIFICATION_WHATSAPP_INBOUND_TOPIC,
            orjson.dumps(payload),
        )


whatsapp_inbound_publisher = WhatsappInboundPublisher()
