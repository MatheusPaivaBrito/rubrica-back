from uuid import uuid4

from core_api.modules.signature_request.signature_request_schema import (
    SignatureRequestCreate,
    SignatureRequestRead,
    SignatureRequestUpdate,
)
from shared_kernel.time.datetime_service import DateTimeService


class SignatureRequestService:
    def __init__(self) -> None:
        self._items: dict[str, SignatureRequestRead] = {}

    def list(self, *, include_deleted: bool = False) -> list[SignatureRequestRead]:
        items = list(self._items.values())
        if include_deleted:
            return items
        return [item for item in items if item.deleted_at is None]

    def get(self, item_id: str) -> SignatureRequestRead | None:
        return self._items.get(item_id)

    def create(self, payload: SignatureRequestCreate) -> SignatureRequestRead:
        now = DateTimeService.utc_now()
        item = SignatureRequestRead(
            id=str(uuid4()),
            name=payload.name,
            code=payload.code,

            created_at=now,
            updated_at=now,
        )
        self._items[item.id] = item
        return item

    def update(self, item_id: str, payload: SignatureRequestUpdate) -> SignatureRequestRead | None:
        current = self._items.get(item_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={
                "name": payload.name if payload.name is not None else current.name,
                "code": payload.code if payload.code is not None else current.code,

                "updated_at": DateTimeService.utc_now(),
            }
        )
        self._items[item_id] = updated
        return updated

    def delete(self, item_id: str) -> SignatureRequestRead | None:
        current = self._items.get(item_id)
        if current is None:
            return None
        deleted = current.model_copy(
            update={
                "deleted_at": DateTimeService.utc_now(),
                "updated_at": DateTimeService.utc_now(),
            }
        )
        self._items[item_id] = deleted
        return deleted

    def restore(self, item_id: str) -> SignatureRequestRead | None:
        current = self._items.get(item_id)
        if current is None:
            return None
        restored = current.model_copy(
            update={
                "deleted_at": None,
                "updated_at": DateTimeService.utc_now(),
            }
        )
        self._items[item_id] = restored
        return restored

    def list_by_parent(self, *, parent_field: str, parent_id: str, include_deleted: bool = False) -> list[SignatureRequestRead]:
        return [
            item
            for item in self.list(include_deleted=include_deleted)
            if getattr(item, parent_field, None) == parent_id
        ]

    def get_by_parent(self, *, parent_field: str, parent_id: str, item_id: str) -> SignatureRequestRead | None:
        item = self.get(item_id)
        if item is None or getattr(item, parent_field, None) != parent_id:
            return None
        return item

    def create_for_parent(self, *, parent_field: str, parent_id: str, payload: SignatureRequestCreate) -> SignatureRequestRead:
        return self.create(payload.model_copy(update={parent_field: parent_id}))

    def update_by_parent(self, *, parent_field: str, parent_id: str, item_id: str, payload: SignatureRequestUpdate) -> SignatureRequestRead | None:
        if self.get_by_parent(parent_field=parent_field, parent_id=parent_id, item_id=item_id) is None:
            return None
        return self.update(item_id, payload)

    def delete_by_parent(self, *, parent_field: str, parent_id: str, item_id: str) -> SignatureRequestRead | None:
        if self.get_by_parent(parent_field=parent_field, parent_id=parent_id, item_id=item_id) is None:
            return None
        return self.delete(item_id)

    def restore_by_parent(self, *, parent_field: str, parent_id: str, item_id: str) -> SignatureRequestRead | None:
        if self.get_by_parent(parent_field=parent_field, parent_id=parent_id, item_id=item_id) is None:
            return None
        return self.restore(item_id)

    def list_related(self, *, item_id: str, related_field: str) -> list[str] | None:
        current = self.get(item_id)
        if current is None:
            return None
        return list(getattr(current, related_field, []))

    def link_related(self, *, item_id: str, related_field: str, related_id: str) -> SignatureRequestRead | None:
        current = self.get(item_id)
        if current is None:
            return None
        related_ids = list(getattr(current, related_field, []))
        if related_id not in related_ids:
            related_ids.append(related_id)
        updated = current.model_copy(
            update={related_field: related_ids, "updated_at": DateTimeService.utc_now()}
        )
        self._items[item_id] = updated
        return updated

    def unlink_related(self, *, item_id: str, related_field: str, related_id: str) -> SignatureRequestRead | None:
        current = self.get(item_id)
        if current is None:
            return None
        related_ids = [value for value in getattr(current, related_field, []) if value != related_id]
        updated = current.model_copy(
            update={related_field: related_ids, "updated_at": DateTimeService.utc_now()}
        )
        self._items[item_id] = updated
        return updated


signature_request_service = SignatureRequestService()
