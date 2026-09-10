from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from shared_kernel.media import MediaReference
else:
    MediaReference = Any


class ProviderDelivery(BaseModel):
    provider_message_id: str
    status: str


class MessageProvider(Protocol):
    name: str

    def deliver(
        self,
        *,
        recipient: str,
        content: str,
        media: MediaReference | None,
    ) -> ProviderDelivery: ...

    def verify(self) -> dict[str, object]: ...
