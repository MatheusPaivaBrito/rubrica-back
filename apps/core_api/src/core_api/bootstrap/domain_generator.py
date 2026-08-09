import re
import textwrap
from pathlib import Path


SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class DomainGeneratorError(RuntimeError):
    pass


def _normalize_snake(value: str, *, label: str) -> str:
    normalized = value.strip().replace("-", "_").lower()
    if not SNAKE_CASE_PATTERN.match(normalized):
        raise DomainGeneratorError(f"{label} must use snake_case: {value!r}")
    return normalized


def _singular(value: str) -> str:
    if value.endswith("ies") and len(value) > 3:
        return f"{value[:-3]}y"
    if value.endswith("ves") and len(value) > 3:
        return f"{value[:-3]}f"
    if value.endswith("s") and len(value) > 1:
        return value[:-1]
    return value


def _class_name(value: str) -> str:
    return value.replace("_", " ").title().replace(" ", "")


def _write(path: Path, content: str) -> None:
    if path.exists():
        raise DomainGeneratorError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _parse_many_to_many(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(
        _normalize_snake(item.strip(), label="many_to_many")
        for item in value.split(",")
        if item.strip()
    )


def _register_routes(*, package_root: Path, domain_name: str, entity_name: str) -> None:
    routes_path = package_root / "bootstrap/routes.py"
    content = routes_path.read_text(encoding="utf-8")
    import_line = f"from core_api.modules.{domain_name}.{entity_name}_router import router as {entity_name}_router"
    include_line = f"    app.include_router({entity_name}_router)"

    if import_line not in content:
        marker = "\n\ndef register_routes"
        content = content.replace(marker, f"\n{import_line}\n\ndef register_routes")
    if include_line not in content:
        content = content.replace(
            "    app.include_router(ui_manifest_router)\n",
            f"    app.include_router(ui_manifest_router)\n{include_line}\n",
        )

    routes_path.write_text(content, encoding="utf-8")


def _register_loader(*, package_root: Path, domain_name: str, entity_class: str, entity_name: str) -> None:
    loader_path = package_root / "infrastructure/database/loader.py"
    content = loader_path.read_text(encoding="utf-8")
    import_line = f"from core_api.modules.{domain_name}.{entity_name}_entity import {entity_class}Entity  # noqa: F401"
    if import_line not in content:
        content = f"{content.rstrip()}\n{import_line}\n"
    loader_path.write_text(content, encoding="utf-8")


def generate_core_domain(
    *,
    project_root: Path,
    name: str,
    belongs_to: str | None = None,
    many_to_many: str | None = None,
    relationship_notes: str | None = None,
    persistence: str = "memory",
) -> list[Path]:
    domain_name = _normalize_snake(name, label="domain")
    parent_domain = _normalize_snake(belongs_to, label="belongs_to") if belongs_to else None
    related_domains = _parse_many_to_many(many_to_many)
    entity_name = _singular(domain_name)
    entity_class = _class_name(entity_name)
    package_root = project_root / "apps/core_api/src/core_api"
    domain_dir = package_root / "modules" / domain_name
    if persistence not in {"memory", "relational"}:
        raise DomainGeneratorError(
            "persistence must be one of: memory, relational"
        )
    if persistence == "relational":
        from core_api.bootstrap.relational_domain import (
            RelationalDomainError,
            generate_relational_core_domain,
        )

        try:
            created = generate_relational_core_domain(
                project_root=project_root,
                domain_name=domain_name,
                parent_domain=parent_domain,
                related_domains=related_domains,
                relationship_notes=relationship_notes,
            )
        except RelationalDomainError as exc:
            raise DomainGeneratorError(str(exc)) from exc

        _register_routes(
            package_root=package_root,
            domain_name=domain_name,
            entity_name=entity_name,
        )
        _register_loader(
            package_root=package_root,
            domain_name=domain_name,
            entity_class=entity_class,
            entity_name=entity_name,
        )
        created.extend(
            [
                package_root / "bootstrap/routes.py",
                package_root / "infrastructure/database/loader.py",
            ]
        )
        return created

    parent_entity = _singular(parent_domain) if parent_domain else None
    parent_field = f"{parent_entity}_id" if parent_entity else None
    related_fields = tuple((domain, f"{_singular(domain)}_ids") for domain in related_domains)
    parent_route_prefix = (
        f"/{parent_domain.replace('_', '-')}/{{{parent_field}}}/{domain_name.replace('_', '-')}"
        if parent_domain and parent_field
        else None
    )
    related_relations = {domain: field for domain, field in related_fields}

    create_fields = []
    update_fields = []
    read_fields = []
    create_kwargs = []
    update_kwargs = []
    relationship_lines = []

    if parent_domain and parent_field:
        create_fields.append(f"    {parent_field}: str | None = None")
        update_fields.append(f"    {parent_field}: str | None = None")
        read_fields.append(f"    {parent_field}: str | None = None")
        create_kwargs.append(f"            {parent_field}=payload.{parent_field},")
        update_kwargs.append(
            f'                "{parent_field}": payload.{parent_field} if payload.{parent_field} is not None else current.{parent_field},'
        )
        relationship_lines.extend(
            [
                "## Hierarchy",
                "",
                f"- `{domain_name}` belongs to `{parent_domain}`.",
                f"- Suggested field: `{parent_field}`.",
                "",
            ]
        )

    if related_fields:
        relationship_lines.extend(["## Many To Many", ""])
        for related_domain, related_field in related_fields:
            create_fields.append(f"    {related_field}: list[str] = Field(default_factory=list)")
            update_fields.append(f"    {related_field}: list[str] | None = None")
            read_fields.append(f"    {related_field}: list[str] = Field(default_factory=list)")
            create_kwargs.append(f"            {related_field}=payload.{related_field},")
            update_kwargs.append(
                f'                "{related_field}": payload.{related_field} if payload.{related_field} is not None else current.{related_field},'
            )
            relationship_lines.append(
                f"- `{domain_name}` can relate to many `{related_domain}` records via `{related_field}`."
            )
        relationship_lines.append("")

    if relationship_notes:
        relationship_lines.extend(["## Notes", "", relationship_notes.strip(), ""])

    schema_template_indent = " " * 12
    call_template_indent = " " * 12
    create_fields_text = "\n".join(f"{schema_template_indent}{line}" for line in create_fields)
    update_fields_text = "\n".join(f"{schema_template_indent}{line}" for line in update_fields)
    read_fields_text = "\n".join(f"{schema_template_indent}{line}" for line in read_fields)
    create_kwargs_text = "\n".join(f"{call_template_indent}{line}" for line in create_kwargs)
    update_kwargs_text = "\n".join(f"{call_template_indent}{line}" for line in update_kwargs)

    files = {
        domain_dir / "README.md": f'''
            # {domain_name.replace("_", " ").title()}

            Generated Core CRUD domain.

            Use `RELATIONSHIPS.md` when cross-domain metadata is present.
        ''',
        domain_dir / "__init__.py": "",
        domain_dir / f"{entity_name}_entity.py": f'''
            from sqlalchemy import String
            from sqlalchemy.orm import Mapped, mapped_column

            from core_api.infrastructure.database.connection import BaseEntity


            class {entity_class}Entity(BaseEntity):
                __tablename__ = "{domain_name}"

                name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
                code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
        ''',
        domain_dir / f"{entity_name}_schema.py": f'''
            from datetime import datetime

            from pydantic import BaseModel, Field


            class {entity_class}Create(BaseModel):
                name: str = Field(min_length=1, max_length=120)
                code: str = Field(min_length=1, max_length=80)
{create_fields_text}


            class {entity_class}Update(BaseModel):
                name: str | None = Field(default=None, min_length=1, max_length=120)
                code: str | None = Field(default=None, min_length=1, max_length=80)
{update_fields_text}


            class {entity_class}Read(BaseModel):
                id: str
                name: str
                code: str
{read_fields_text}
                created_at: datetime
                updated_at: datetime
                deleted_at: datetime | None = None
        ''',
        domain_dir / f"{entity_name}_service.py": f'''
            from uuid import uuid4

            from core_api.modules.{domain_name}.{entity_name}_schema import (
                {entity_class}Create,
                {entity_class}Read,
                {entity_class}Update,
            )
            from shared_kernel.time.datetime_service import DateTimeService


            class {entity_class}Service:
                def __init__(self) -> None:
                    self._items: dict[str, {entity_class}Read] = {{}}

                def list(self, *, include_deleted: bool = False) -> list[{entity_class}Read]:
                    items = list(self._items.values())
                    if include_deleted:
                        return items
                    return [item for item in items if item.deleted_at is None]

                def get(self, item_id: str) -> {entity_class}Read | None:
                    return self._items.get(item_id)

                def create(self, payload: {entity_class}Create) -> {entity_class}Read:
                    now = DateTimeService.utc_now()
                    item = {entity_class}Read(
                        id=str(uuid4()),
                        name=payload.name,
                        code=payload.code,
{create_kwargs_text}
                        created_at=now,
                        updated_at=now,
                    )
                    self._items[item.id] = item
                    return item

                def update(self, item_id: str, payload: {entity_class}Update) -> {entity_class}Read | None:
                    current = self._items.get(item_id)
                    if current is None:
                        return None
                    updated = current.model_copy(
                        update={{
                            "name": payload.name if payload.name is not None else current.name,
                            "code": payload.code if payload.code is not None else current.code,
{update_kwargs_text}
                            "updated_at": DateTimeService.utc_now(),
                        }}
                    )
                    self._items[item_id] = updated
                    return updated

                def delete(self, item_id: str) -> {entity_class}Read | None:
                    current = self._items.get(item_id)
                    if current is None:
                        return None
                    deleted = current.model_copy(
                        update={{
                            "deleted_at": DateTimeService.utc_now(),
                            "updated_at": DateTimeService.utc_now(),
                        }}
                    )
                    self._items[item_id] = deleted
                    return deleted

                def restore(self, item_id: str) -> {entity_class}Read | None:
                    current = self._items.get(item_id)
                    if current is None:
                        return None
                    restored = current.model_copy(
                        update={{
                            "deleted_at": None,
                            "updated_at": DateTimeService.utc_now(),
                        }}
                    )
                    self._items[item_id] = restored
                    return restored

                def list_by_parent(self, *, parent_field: str, parent_id: str, include_deleted: bool = False) -> list[{entity_class}Read]:
                    return [
                        item
                        for item in self.list(include_deleted=include_deleted)
                        if getattr(item, parent_field, None) == parent_id
                    ]

                def get_by_parent(self, *, parent_field: str, parent_id: str, item_id: str) -> {entity_class}Read | None:
                    item = self.get(item_id)
                    if item is None or getattr(item, parent_field, None) != parent_id:
                        return None
                    return item

                def create_for_parent(self, *, parent_field: str, parent_id: str, payload: {entity_class}Create) -> {entity_class}Read:
                    return self.create(payload.model_copy(update={{parent_field: parent_id}}))

                def update_by_parent(self, *, parent_field: str, parent_id: str, item_id: str, payload: {entity_class}Update) -> {entity_class}Read | None:
                    if self.get_by_parent(parent_field=parent_field, parent_id=parent_id, item_id=item_id) is None:
                        return None
                    return self.update(item_id, payload)

                def delete_by_parent(self, *, parent_field: str, parent_id: str, item_id: str) -> {entity_class}Read | None:
                    if self.get_by_parent(parent_field=parent_field, parent_id=parent_id, item_id=item_id) is None:
                        return None
                    return self.delete(item_id)

                def restore_by_parent(self, *, parent_field: str, parent_id: str, item_id: str) -> {entity_class}Read | None:
                    if self.get_by_parent(parent_field=parent_field, parent_id=parent_id, item_id=item_id) is None:
                        return None
                    return self.restore(item_id)

                def list_related(self, *, item_id: str, related_field: str) -> list[str] | None:
                    current = self.get(item_id)
                    if current is None:
                        return None
                    return list(getattr(current, related_field, []))

                def link_related(self, *, item_id: str, related_field: str, related_id: str) -> {entity_class}Read | None:
                    current = self.get(item_id)
                    if current is None:
                        return None
                    related_ids = list(getattr(current, related_field, []))
                    if related_id not in related_ids:
                        related_ids.append(related_id)
                    updated = current.model_copy(
                        update={{related_field: related_ids, "updated_at": DateTimeService.utc_now()}}
                    )
                    self._items[item_id] = updated
                    return updated

                def unlink_related(self, *, item_id: str, related_field: str, related_id: str) -> {entity_class}Read | None:
                    current = self.get(item_id)
                    if current is None:
                        return None
                    related_ids = [value for value in getattr(current, related_field, []) if value != related_id]
                    updated = current.model_copy(
                        update={{related_field: related_ids, "updated_at": DateTimeService.utc_now()}}
                    )
                    self._items[item_id] = updated
                    return updated


            {entity_name}_service = {entity_class}Service()
        ''',
        domain_dir / f"{entity_name}_router.py": f'''
            from fastapi import APIRouter, HTTPException, Path, status

            from core_api.modules.{domain_name}.{entity_name}_schema import (
                {entity_class}Create,
                {entity_class}Read,
                {entity_class}Update,
            )
            from core_api.modules.{domain_name}.{entity_name}_service import {entity_name}_service
            from shared_kernel.http.crud.route_factory import create_crud_router


            DOMAIN_TAG = "{domain_name.replace("_", "-")}"
            PARENT_FIELD: str | None = {parent_field!r}
            PARENT_ROUTE_PREFIX: str | None = {parent_route_prefix!r}
            RELATED_RELATIONS: dict[str, str] = {related_relations!r}

            router = APIRouter()
            router.include_router(
                create_crud_router(
                    prefix="/{domain_name.replace("_", "-")}",
                    tags=[DOMAIN_TAG],
                    query_tag=f"{{DOMAIN_TAG}} - query",
                    command_tag=f"{{DOMAIN_TAG}} - command",
                    service={entity_name}_service,
                    create_schema={entity_class}Create,
                    update_schema={entity_class}Update,
                    read_schema={entity_class}Read,
                    not_found_message="{entity_class} not found",
                )
            )

            def _not_found() -> None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="{entity_class} not found")


            if PARENT_FIELD and PARENT_ROUTE_PREFIX:
                @router.get(PARENT_ROUTE_PREFIX, response_model=list[{entity_class}Read], tags=[f"{{DOMAIN_TAG}} - query"])
                async def list_by_parent(parent_id: str = Path(alias=PARENT_FIELD), include_deleted: bool = False) -> list[{entity_class}Read]:
                    return {entity_name}_service.list_by_parent(parent_field=PARENT_FIELD, parent_id=parent_id, include_deleted=include_deleted)

                @router.get(f"{{PARENT_ROUTE_PREFIX}}/{{{{resource_id}}}}", response_model={entity_class}Read, tags=[f"{{DOMAIN_TAG}} - query"])
                async def get_by_parent(resource_id: str, parent_id: str = Path(alias=PARENT_FIELD)) -> {entity_class}Read:
                    resource = {entity_name}_service.get_by_parent(parent_field=PARENT_FIELD, parent_id=parent_id, item_id=resource_id)
                    if resource is None:
                        _not_found()
                    return resource

                @router.post(PARENT_ROUTE_PREFIX, response_model={entity_class}Read, status_code=status.HTTP_201_CREATED, tags=[f"{{DOMAIN_TAG}} - command"])
                async def create_for_parent(payload: {entity_class}Create, parent_id: str = Path(alias=PARENT_FIELD)) -> {entity_class}Read:
                    return {entity_name}_service.create_for_parent(parent_field=PARENT_FIELD, parent_id=parent_id, payload=payload)

                @router.patch(f"{{PARENT_ROUTE_PREFIX}}/{{{{resource_id}}}}", response_model={entity_class}Read, tags=[f"{{DOMAIN_TAG}} - command"])
                async def update_by_parent(resource_id: str, payload: {entity_class}Update, parent_id: str = Path(alias=PARENT_FIELD)) -> {entity_class}Read:
                    resource = {entity_name}_service.update_by_parent(parent_field=PARENT_FIELD, parent_id=parent_id, item_id=resource_id, payload=payload)
                    if resource is None:
                        _not_found()
                    return resource

                @router.delete(f"{{PARENT_ROUTE_PREFIX}}/{{{{resource_id}}}}", response_model={entity_class}Read, tags=[f"{{DOMAIN_TAG}} - command"])
                async def delete_by_parent(resource_id: str, parent_id: str = Path(alias=PARENT_FIELD)) -> {entity_class}Read:
                    resource = {entity_name}_service.delete_by_parent(parent_field=PARENT_FIELD, parent_id=parent_id, item_id=resource_id)
                    if resource is None:
                        _not_found()
                    return resource

                @router.post(f"{{PARENT_ROUTE_PREFIX}}/{{{{resource_id}}}}/restore", response_model={entity_class}Read, tags=[f"{{DOMAIN_TAG}} - command"])
                async def restore_by_parent(resource_id: str, parent_id: str = Path(alias=PARENT_FIELD)) -> {entity_class}Read:
                    resource = {entity_name}_service.restore_by_parent(parent_field=PARENT_FIELD, parent_id=parent_id, item_id=resource_id)
                    if resource is None:
                        _not_found()
                    return resource


            def _list_related_endpoint(related_field: str):
                async def endpoint(resource_id: str) -> list[str]:
                    related_ids = {entity_name}_service.list_related(item_id=resource_id, related_field=related_field)
                    if related_ids is None:
                        _not_found()
                    return related_ids
                return endpoint


            def _link_related_endpoint(related_field: str):
                async def endpoint(resource_id: str, related_id: str) -> {entity_class}Read:
                    resource = {entity_name}_service.link_related(item_id=resource_id, related_field=related_field, related_id=related_id)
                    if resource is None:
                        _not_found()
                    return resource
                return endpoint


            def _unlink_related_endpoint(related_field: str):
                async def endpoint(resource_id: str, related_id: str) -> {entity_class}Read:
                    resource = {entity_name}_service.unlink_related(item_id=resource_id, related_field=related_field, related_id=related_id)
                    if resource is None:
                        _not_found()
                    return resource
                return endpoint


            for related_domain, related_field in RELATED_RELATIONS.items():
                related_tag = f"{{DOMAIN_TAG}}-{{related_domain.replace('_', '-')}}"
                relation_prefix = f"/{domain_name.replace("_", "-")}/{{{{resource_id}}}}/{{related_domain.replace('_', '-')}}"
                router.add_api_route(relation_prefix, _list_related_endpoint(related_field), methods=["GET"], response_model=list[str], tags=[f"{{related_tag}} - query"])
                router.add_api_route(f"{{relation_prefix}}/{{{{related_id}}}}", _link_related_endpoint(related_field), methods=["POST"], response_model={entity_class}Read, tags=[f"{{related_tag}} - command"])
                router.add_api_route(f"{{relation_prefix}}/{{{{related_id}}}}", _unlink_related_endpoint(related_field), methods=["DELETE"], response_model={entity_class}Read, tags=[f"{{related_tag}} - command"])
        ''',
    }

    if relationship_lines:
        files[domain_dir / "RELATIONSHIPS.md"] = f'''
            # {domain_name.replace("_", " ").title()} Relationships

            This file records cross-domain intent for the generated module.

            {"\n".join(relationship_lines)}
        '''

    created = []
    for path, content in files.items():
        _write(path, content)
        created.append(path)

    _register_routes(package_root=package_root, domain_name=domain_name, entity_name=entity_name)
    _register_loader(package_root=package_root, domain_name=domain_name, entity_class=entity_class, entity_name=entity_name)
    created.extend([package_root / "bootstrap/routes.py", package_root / "infrastructure/database/loader.py"])
    return created
