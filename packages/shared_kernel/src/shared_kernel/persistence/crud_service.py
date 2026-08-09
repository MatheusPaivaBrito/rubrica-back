from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select


@dataclass(frozen=True)
class ManyToManyConfig:
    attribute: str
    model: type[Any]


class SqlAlchemyCrudService:
    def __init__(
        self,
        *,
        model: type[Any],
        read_schema: type[BaseModel],
        session_factory: Any,
        parent_field: str | None = None,
        relations: dict[str, ManyToManyConfig] | None = None,
    ) -> None:
        self.model = model
        self.read_schema = read_schema
        self.session_factory = session_factory
        self.parent_field = parent_field
        self.relations = relations or {}

    def list(self, *, include_deleted: bool = False) -> list[BaseModel]:
        with self.session_factory() as session:
            statement = select(self.model).order_by(self.model.id)
            if not include_deleted:
                statement = statement.where(self.model.deleted_at.is_(None))
            return [self._read(item) for item in session.scalars(statement).unique().all()]

    def get(self, item_id: str) -> BaseModel | None:
        with self.session_factory() as session:
            item = session.get(self.model, self._identifier(item_id))
            return self._read(item) if item is not None else None

    def create(self, payload: BaseModel) -> BaseModel:
        values = payload.model_dump()
        relation_values = self._pop_relation_values(values)
        with self.session_factory() as session:
            item = self.model(**values)
            self._apply_relations(session, item, relation_values)
            session.add(item)
            session.commit()
            session.refresh(item)
            return self._read(item)

    def update(self, item_id: str, payload: BaseModel) -> BaseModel | None:
        values = payload.model_dump(exclude_unset=True)
        relation_values = self._pop_relation_values(values)
        with self.session_factory() as session:
            item = session.get(self.model, self._identifier(item_id))
            if item is None:
                return None
            for field_name, value in values.items():
                setattr(item, field_name, value)
            self._apply_relations(session, item, relation_values)
            session.commit()
            session.refresh(item)
            return self._read(item)

    def delete(self, item_id: str) -> BaseModel | None:
        return self._set_deleted_at(item_id, datetime.now(UTC))

    def restore(self, item_id: str) -> BaseModel | None:
        return self._set_deleted_at(item_id, None)

    def list_by_parent(
        self,
        *,
        parent_field: str,
        parent_id: str,
        include_deleted: bool = False,
    ) -> list[BaseModel]:
        with self.session_factory() as session:
            statement = select(self.model).where(
                getattr(self.model, parent_field) == self._identifier(parent_id)
            )
            if not include_deleted:
                statement = statement.where(self.model.deleted_at.is_(None))
            return [self._read(item) for item in session.scalars(statement).unique().all()]

    def get_by_parent(
        self,
        *,
        parent_field: str,
        parent_id: str,
        item_id: str,
    ) -> BaseModel | None:
        item = self.get(item_id)
        if item is None or getattr(item, parent_field, None) != self._identifier(parent_id):
            return None
        return item

    def create_for_parent(
        self,
        *,
        parent_field: str,
        parent_id: str,
        payload: BaseModel,
    ) -> BaseModel:
        return self.create(
            payload.model_copy(update={parent_field: self._identifier(parent_id)})
        )

    def update_by_parent(
        self,
        *,
        parent_field: str,
        parent_id: str,
        item_id: str,
        payload: BaseModel,
    ) -> BaseModel | None:
        if self.get_by_parent(
            parent_field=parent_field,
            parent_id=parent_id,
            item_id=item_id,
        ) is None:
            return None
        return self.update(item_id, payload)

    def delete_by_parent(
        self,
        *,
        parent_field: str,
        parent_id: str,
        item_id: str,
    ) -> BaseModel | None:
        if self.get_by_parent(
            parent_field=parent_field,
            parent_id=parent_id,
            item_id=item_id,
        ) is None:
            return None
        return self.delete(item_id)

    def restore_by_parent(
        self,
        *,
        parent_field: str,
        parent_id: str,
        item_id: str,
    ) -> BaseModel | None:
        if self.get_by_parent(
            parent_field=parent_field,
            parent_id=parent_id,
            item_id=item_id,
        ) is None:
            return None
        return self.restore(item_id)

    def list_related(self, *, item_id: str, related_field: str) -> list[int] | None:
        item = self.get(item_id)
        if item is None:
            return None
        return list(getattr(item, related_field, []))

    def link_related(
        self,
        *,
        item_id: str,
        related_field: str,
        related_id: str,
    ) -> BaseModel | None:
        config = self._relation(related_field)
        with self.session_factory() as session:
            item = session.get(self.model, self._identifier(item_id))
            related = session.get(config.model, self._identifier(related_id))
            if item is None or related is None:
                return None
            values = getattr(item, config.attribute)
            if related not in values:
                values.append(related)
            session.commit()
            session.refresh(item)
            return self._read(item)

    def unlink_related(
        self,
        *,
        item_id: str,
        related_field: str,
        related_id: str,
    ) -> BaseModel | None:
        config = self._relation(related_field)
        with self.session_factory() as session:
            item = session.get(self.model, self._identifier(item_id))
            if item is None:
                return None
            identifier = self._identifier(related_id)
            values = getattr(item, config.attribute)
            values[:] = [related for related in values if related.id != identifier]
            session.commit()
            session.refresh(item)
            return self._read(item)

    def _set_deleted_at(self, item_id: str, value: datetime | None) -> BaseModel | None:
        with self.session_factory() as session:
            item = session.get(self.model, self._identifier(item_id))
            if item is None:
                return None
            item.deleted_at = value
            session.commit()
            session.refresh(item)
            return self._read(item)

    def _pop_relation_values(self, values: dict[str, Any]) -> dict[str, list[int]]:
        return {
            field_name: values.pop(field_name)
            for field_name in self.relations
            if field_name in values and values[field_name] is not None
        }

    def _apply_relations(
        self,
        session: Any,
        item: Any,
        relation_values: dict[str, list[int]],
    ) -> None:
        for field_name, identifiers in relation_values.items():
            config = self._relation(field_name)
            unique_ids = tuple(dict.fromkeys(self._identifier(value) for value in identifiers))
            related = (
                list(session.scalars(select(config.model).where(config.model.id.in_(unique_ids))).all())
                if unique_ids
                else []
            )
            if len(related) != len(unique_ids):
                found = {value.id for value in related}
                missing = [value for value in unique_ids if value not in found]
                raise ValueError(f"{field_name} references missing ids: {missing}")
            setattr(item, config.attribute, related)

    def _relation(self, related_field: str) -> ManyToManyConfig:
        try:
            return self.relations[related_field]
        except KeyError as exc:
            raise ValueError(f"unknown relation field: {related_field}") from exc

    def _read(self, item: Any) -> BaseModel:
        return self.read_schema.model_validate(item, from_attributes=True)

    @staticmethod
    def _identifier(value: str | int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid integer resource id: {value!r}") from exc
