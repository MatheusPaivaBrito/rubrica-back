from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path


SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class RelationalDomainError(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrationState:
    revision: str
    down_revision: str | None
    tables: tuple[str, ...]


def _normalize_snake(value: str, *, label: str) -> str:
    normalized = value.strip().replace("-", "_").lower()
    if not SNAKE_CASE_PATTERN.match(normalized):
        raise RelationalDomainError(f"{label} must use snake_case: {value!r}")
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


def _clean(source: str) -> str:
    return textwrap.dedent(source).lstrip()


def _assignment_value(node: ast.stmt, name: str) -> object:
    if isinstance(node, ast.Assign):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == name:
                return ast.literal_eval(node.value)
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        if node.target.id == name and node.value is not None:
            return ast.literal_eval(node.value)
    return ...


def _read_migration(path: Path) -> MigrationState:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise RelationalDomainError(f"cannot inspect Core migration {path}: {exc}") from exc

    revision: str | None = None
    down_revision: str | None = None
    tables: list[str] = []
    for node in tree.body:
        revision_value = _assignment_value(node, "revision")
        if revision_value is not ...:
            revision = revision_value if isinstance(revision_value, str) else None
        down_revision_value = _assignment_value(node, "down_revision")
        if down_revision_value is not ...:
            if down_revision_value is not None and not isinstance(down_revision_value, str):
                raise RelationalDomainError(
                    f"down_revision must be a string or None in {path}"
                )
            down_revision = down_revision_value

        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or not child.args:
                continue
            function = child.func
            if not (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "op"
                and function.attr == "create_table"
            ):
                continue
            table_name = ast.literal_eval(child.args[0])
            if isinstance(table_name, str):
                tables.append(table_name)

    if revision is None:
        raise RelationalDomainError(f"Core migration does not define revision: {path}")
    return MigrationState(
        revision=revision,
        down_revision=down_revision,
        tables=tuple(tables),
    )


def _migration_states(project_root: Path) -> tuple[MigrationState, ...]:
    versions = project_root / "apps/core_api/alembic/versions"
    if not versions.exists():
        return ()
    return tuple(
        _read_migration(path)
        for path in sorted(versions.glob("*.py"))
        if path.name != "__init__.py"
    )


def _next_migration(
    project_root: Path,
    *,
    domain_name: str,
    required_tables: tuple[str, ...],
    created_tables: tuple[str, ...],
) -> tuple[Path, str, str | None]:
    states = _migration_states(project_root)
    existing_tables = {table for state in states for table in state.tables}
    missing = sorted(set(required_tables) - existing_tables)
    if missing:
        raise RelationalDomainError(
            "relational domain references tables without a Core migration: "
            f"{', '.join(missing)}; generate those domains in relational mode first"
        )

    duplicates = sorted(set(created_tables) & existing_tables)
    if duplicates:
        raise RelationalDomainError(
            f"Core migrations already create table(s): {', '.join(duplicates)}"
        )

    revisions = {state.revision for state in states}
    referenced = {
        state.down_revision
        for state in states
        if state.down_revision is not None
    }
    heads = sorted(revisions - referenced)
    if len(heads) > 1:
        raise RelationalDomainError(
            f"Core Alembic has multiple heads: {', '.join(heads)}"
        )

    revision = f"{len(states) + 1:04d}_{domain_name}_relational"
    path = project_root / "apps/core_api/alembic/versions" / f"{revision}.py"
    return path, revision, heads[0] if heads else None


def _association_table(domain_name: str, related_domain: str) -> str:
    return "_".join(sorted((domain_name, related_domain)))


def _entity_source(
    *,
    domain_name: str,
    entity_name: str,
    entity_class: str,
    parent_domain: str | None,
    related_domains: tuple[str, ...],
) -> str:
    imports: list[str] = []
    definitions: list[str] = []
    fields: list[str] = [
        '    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)',
        (
            "    code: Mapped[str] = mapped_column("
            "String(80), nullable=False, unique=True, index=True)"
        ),
    ]
    properties: list[str] = []

    if parent_domain:
        parent_entity = _singular(parent_domain)
        parent_class = _class_name(parent_entity)
        parent_field = f"{parent_entity}_id"
        imports.append(
            f"from core_api.modules.{parent_domain}.{parent_entity}_entity "
            f"import {parent_class}Entity"
        )
        fields.extend(
            [
                f"    {parent_field}: Mapped[int | None] = mapped_column(",
                (
                    f'        ForeignKey("{parent_domain}.id", ondelete="RESTRICT"), '
                    "nullable=True, index=True"
                ),
                "    )",
                (
                    f"    {parent_entity}: Mapped[{parent_class}Entity | None] = "
                    'relationship(lazy="joined")'
                ),
            ]
        )

    for related_domain in related_domains:
        related_entity = _singular(related_domain)
        related_class = _class_name(related_entity)
        association_name = f"{entity_name}_{related_entity}_association"
        table_name = _association_table(domain_name, related_domain)
        imports.append(
            f"from core_api.modules.{related_domain}.{related_entity}_entity "
            f"import {related_class}Entity"
        )
        definitions.append(
            "\n".join(
                [
                    f"{association_name} = Table(",
                    f'    "{table_name}",',
                    "    Base.metadata,",
                    "    Column(",
                    f'        "{entity_name}_id",',
                    f'        ForeignKey("{domain_name}.id", ondelete="CASCADE"),',
                    "        primary_key=True,",
                    "    ),",
                    "    Column(",
                    f'        "{related_entity}_id",',
                    f'        ForeignKey("{related_domain}.id", ondelete="CASCADE"),',
                    "        primary_key=True,",
                    "    ),",
                    ")",
                ]
            )
        )
        fields.append(
            f"    {related_domain}: Mapped[list[{related_class}Entity]] = "
            f'relationship(secondary={association_name}, lazy="selectin")'
        )
        properties.append(
            "\n".join(
                [
                    "    @property",
                    f"    def {related_entity}_ids(self) -> list[int]:",
                    f"        return [item.id for item in self.{related_domain}]",
                ]
            )
        )

    sqlalchemy_imports = ["String"]
    if parent_domain or related_domains:
        sqlalchemy_imports.append("ForeignKey")
    if related_domains:
        sqlalchemy_imports.extend(["Column", "Table"])
    sqlalchemy_imports.sort()
    orm_imports = ["Mapped", "mapped_column"]
    if parent_domain or related_domains:
        orm_imports.append("relationship")
    connection_imports = ["BaseEntity"]
    if related_domains:
        connection_imports.insert(0, "Base")

    lines = [
        "from __future__ import annotations",
        "",
        f"from sqlalchemy import {', '.join(sqlalchemy_imports)}",
        f"from sqlalchemy.orm import {', '.join(orm_imports)}",
        "",
        (
            "from core_api.infrastructure.database.connection import "
            f"{', '.join(connection_imports)}"
        ),
        *imports,
        "",
        "",
    ]
    if definitions:
        lines.extend(["\n\n".join(definitions), "", ""])
    lines.extend(
        [
            f"class {entity_class}Entity(BaseEntity):",
            f'    __tablename__ = "{domain_name}"',
            "",
            *fields,
        ]
    )
    if properties:
        lines.extend(["", *properties])
    return "\n".join(lines).rstrip() + "\n"


def _schema_source(
    *,
    entity_class: str,
    parent_field: str | None,
    related_domains: tuple[str, ...],
) -> str:
    create_fields = [f"    {parent_field}: int | None = None"] if parent_field else []
    update_fields = [f"    {parent_field}: int | None = None"] if parent_field else []
    read_fields = [f"    {parent_field}: int | None = None"] if parent_field else []
    for related_domain in related_domains:
        field = f"{_singular(related_domain)}_ids"
        create_fields.append(f"    {field}: list[int] = Field(default_factory=list)")
        update_fields.append(f"    {field}: list[int] | None = None")
        read_fields.append(f"    {field}: list[int] = Field(default_factory=list)")

    lines = [
        "from datetime import datetime",
        "",
        "from pydantic import BaseModel, Field",
        "",
        "",
        f"class {entity_class}Create(BaseModel):",
        "    name: str = Field(min_length=1, max_length=120)",
        "    code: str = Field(min_length=1, max_length=80)",
        *create_fields,
        "",
        "",
        f"class {entity_class}Update(BaseModel):",
        "    name: str | None = Field(default=None, min_length=1, max_length=120)",
        "    code: str | None = Field(default=None, min_length=1, max_length=80)",
        *update_fields,
        "",
        "",
        f"class {entity_class}Read(BaseModel):",
        "    id: int",
        "    name: str",
        "    code: str",
        *read_fields,
        "    created_at: datetime",
        "    updated_at: datetime",
        "    deleted_at: datetime | None = None",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _service_source(
    *,
    domain_name: str,
    entity_name: str,
    entity_class: str,
    parent_field: str | None,
    related_domains: tuple[str, ...],
) -> str:
    imports: list[str] = []
    configurations: list[str] = []
    for related_domain in related_domains:
        related_entity = _singular(related_domain)
        related_class = _class_name(related_entity)
        related_field = f"{related_entity}_ids"
        imports.append(
            f"from core_api.modules.{related_domain}.{related_entity}_entity "
            f"import {related_class}Entity"
        )
        configurations.append(
            f'        "{related_field}": ManyToManyConfig('
            f'attribute="{related_domain}", model={related_class}Entity),'
        )

    lines = [
        "from core_api.infrastructure.database.connection import SessionLocal",
        (
            f"from core_api.modules.{domain_name}.{entity_name}_entity "
            f"import {entity_class}Entity"
        ),
        (
            f"from core_api.modules.{domain_name}.{entity_name}_schema "
            f"import {entity_class}Read"
        ),
        *imports,
        (
            "from shared_kernel.persistence.crud_service import "
            + (
                "ManyToManyConfig, SqlAlchemyCrudService"
                if related_domains
                else "SqlAlchemyCrudService"
            )
        ),
        "",
        "",
        f"{entity_name}_service = SqlAlchemyCrudService(",
        f"    model={entity_class}Entity,",
        f"    read_schema={entity_class}Read,",
        "    session_factory=SessionLocal,",
        f"    parent_field={parent_field!r},",
        "    relations={",
        *configurations,
        "    },",
        ")",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _router_source(
    *,
    domain_name: str,
    entity_name: str,
    entity_class: str,
    parent_field: str | None,
    parent_domain: str | None,
    related_domains: tuple[str, ...],
) -> str:
    tag = domain_name.replace("_", "-")
    route_prefix = f"/{tag}"
    parent_prefix = (
        f"/{parent_domain.replace('_', '-')}/{{{parent_field}}}/{tag}"
        if parent_domain and parent_field
        else None
    )
    relations = {
        domain: f"{_singular(domain)}_ids"
        for domain in related_domains
    }
    return _clean(
        f"""
        from fastapi import APIRouter, HTTPException, Path, status

        from core_api.modules.{domain_name}.{entity_name}_schema import (
            {entity_class}Create,
            {entity_class}Read,
            {entity_class}Update,
        )
        from core_api.modules.{domain_name}.{entity_name}_service import {entity_name}_service
        from shared_kernel.http.crud.route_factory import create_crud_router


        DOMAIN_TAG = "{tag}"
        PARENT_FIELD: str | None = {parent_field!r}
        PARENT_ROUTE_PREFIX: str | None = {parent_prefix!r}
        RELATED_RELATIONS: dict[str, str] = {relations!r}

        router = APIRouter()
        router.include_router(
            create_crud_router(
                prefix="{route_prefix}",
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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="{entity_class} or related resource not found",
            )


        if PARENT_FIELD and PARENT_ROUTE_PREFIX:
            @router.get(
                PARENT_ROUTE_PREFIX,
                response_model=list[{entity_class}Read],
                tags=[f"{{DOMAIN_TAG}} - query"],
            )
            async def list_by_parent(
                parent_id: str = Path(alias=PARENT_FIELD),
                include_deleted: bool = False,
            ) -> list[{entity_class}Read]:
                return {entity_name}_service.list_by_parent(
                    parent_field=PARENT_FIELD,
                    parent_id=parent_id,
                    include_deleted=include_deleted,
                )

            @router.post(
                PARENT_ROUTE_PREFIX,
                response_model={entity_class}Read,
                status_code=status.HTTP_201_CREATED,
                tags=[f"{{DOMAIN_TAG}} - command"],
            )
            async def create_for_parent(
                payload: {entity_class}Create,
                parent_id: str = Path(alias=PARENT_FIELD),
            ) -> {entity_class}Read:
                return {entity_name}_service.create_for_parent(
                    parent_field=PARENT_FIELD,
                    parent_id=parent_id,
                    payload=payload,
                )


        def _list_related_endpoint(related_field: str):
            async def endpoint(resource_id: str) -> list[int]:
                related_ids = {entity_name}_service.list_related(
                    item_id=resource_id,
                    related_field=related_field,
                )
                if related_ids is None:
                    _not_found()
                return related_ids

            return endpoint


        def _link_related_endpoint(related_field: str):
            async def endpoint(resource_id: str, related_id: str) -> {entity_class}Read:
                resource = {entity_name}_service.link_related(
                    item_id=resource_id,
                    related_field=related_field,
                    related_id=related_id,
                )
                if resource is None:
                    _not_found()
                return resource

            return endpoint


        def _unlink_related_endpoint(related_field: str):
            async def endpoint(resource_id: str, related_id: str) -> {entity_class}Read:
                resource = {entity_name}_service.unlink_related(
                    item_id=resource_id,
                    related_field=related_field,
                    related_id=related_id,
                )
                if resource is None:
                    _not_found()
                return resource

            return endpoint


        for related_domain, related_field in RELATED_RELATIONS.items():
            related_tag = f"{{DOMAIN_TAG}}-{{related_domain.replace('_', '-')}}"
            relation_prefix = (
                f"{route_prefix}/{{{{resource_id}}}}/"
                f"{{related_domain.replace('_', '-')}}"
            )
            router.add_api_route(
                relation_prefix,
                _list_related_endpoint(related_field),
                methods=["GET"],
                response_model=list[int],
                tags=[f"{{related_tag}} - query"],
            )
            router.add_api_route(
                f"{{relation_prefix}}/{{{{related_id}}}}",
                _link_related_endpoint(related_field),
                methods=["POST"],
                response_model={entity_class}Read,
                tags=[f"{{related_tag}} - command"],
            )
            router.add_api_route(
                f"{{relation_prefix}}/{{{{related_id}}}}",
                _unlink_related_endpoint(related_field),
                methods=["DELETE"],
                response_model={entity_class}Read,
                tags=[f"{{related_tag}} - command"],
            )
        """
    )


def _migration_source(
    *,
    domain_name: str,
    entity_name: str,
    parent_domain: str | None,
    parent_field: str | None,
    related_domains: tuple[str, ...],
    revision: str,
    down_revision: str | None,
) -> str:
    lines = [
        "from alembic import op",
        "import sqlalchemy as sa",
        "",
        "",
        f"revision = {revision!r}",
        f"down_revision = {down_revision!r}",
        "branch_labels = None",
        "depends_on = None",
        "",
        "",
        "def upgrade() -> None:",
        "    op.create_table(",
        f'        "{domain_name}",',
        '        sa.Column("id", sa.Integer(), primary_key=True),',
        '        sa.Column("name", sa.String(length=120), nullable=False),',
        '        sa.Column("code", sa.String(length=80), nullable=False),',
    ]
    if parent_domain and parent_field:
        lines.extend(
            [
                "        sa.Column(",
                f'            "{parent_field}",',
                "            sa.Integer(),",
                (
                    f'            sa.ForeignKey("{parent_domain}.id", '
                    'ondelete="RESTRICT"),'
                ),
                "            nullable=True,",
                "        ),",
            ]
        )
    lines.extend(
        [
            "        sa.Column(",
            '            "created_at",',
            "            sa.DateTime(timezone=True),",
            "            server_default=sa.func.now(),",
            "            nullable=False,",
            "        ),",
            "        sa.Column(",
            '            "updated_at",',
            "            sa.DateTime(timezone=True),",
            "            server_default=sa.func.now(),",
            "            nullable=False,",
            "        ),",
            (
                '        sa.Column("deleted_at", '
                "sa.DateTime(timezone=True), nullable=True),"
            ),
            (
                f'        sa.UniqueConstraint("code", '
                f'name="uq_{domain_name}_code"),'
            ),
            "    )",
            f'    op.create_index("ix_{domain_name}_name", "{domain_name}", ["name"])',
            (
                f'    op.create_index("ix_{domain_name}_code", '
                f'"{domain_name}", ["code"], unique=True)'
            ),
            (
                f'    op.create_index("ix_{domain_name}_deleted_at", '
                f'"{domain_name}", ["deleted_at"])'
            ),
        ]
    )
    if parent_domain and parent_field:
        lines.append(
            f'    op.create_index("ix_{domain_name}_{parent_field}", '
            f'"{domain_name}", ["{parent_field}"])'
        )

    for related_domain in related_domains:
        related_entity = _singular(related_domain)
        table_name = _association_table(domain_name, related_domain)
        lines.extend(
            [
                "    op.create_table(",
                f'        "{table_name}",',
                "        sa.Column(",
                f'            "{entity_name}_id",',
                "            sa.Integer(),",
                (
                    f'            sa.ForeignKey("{domain_name}.id", '
                    'ondelete="CASCADE"),'
                ),
                "            primary_key=True,",
                "        ),",
                "        sa.Column(",
                f'            "{related_entity}_id",',
                "            sa.Integer(),",
                (
                    f'            sa.ForeignKey("{related_domain}.id", '
                    'ondelete="CASCADE"),'
                ),
                "            primary_key=True,",
                "        ),",
                "    )",
            ]
        )

    lines.extend(["", "", "def downgrade() -> None:"])
    for related_domain in reversed(related_domains):
        lines.append(
            f'    op.drop_table("{_association_table(domain_name, related_domain)}")'
        )
    if parent_domain and parent_field:
        lines.append(
            f'    op.drop_index("ix_{domain_name}_{parent_field}", '
            f'table_name="{domain_name}")'
        )
    lines.extend(
        [
            (
                f'    op.drop_index("ix_{domain_name}_deleted_at", '
                f'table_name="{domain_name}")'
            ),
            (
                f'    op.drop_index("ix_{domain_name}_code", '
                f'table_name="{domain_name}")'
            ),
            (
                f'    op.drop_index("ix_{domain_name}_name", '
                f'table_name="{domain_name}")'
            ),
            f'    op.drop_table("{domain_name}")',
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_relational_core_domain_files(
    *,
    project_root: Path,
    domain_name: str,
    parent_domain: str | None = None,
    related_domains: tuple[str, ...] = (),
    relationship_notes: str | None = None,
) -> tuple[dict[Path, str], Path, str]:
    domain_name = _normalize_snake(domain_name, label="domain")
    parent_domain = (
        _normalize_snake(parent_domain, label="belongs_to")
        if parent_domain
        else None
    )
    related_domains = tuple(
        dict.fromkeys(
            _normalize_snake(value, label="many_to_many")
            for value in related_domains
        )
    )
    if parent_domain == domain_name or domain_name in related_domains:
        raise RelationalDomainError("a domain cannot relate to itself")

    entity_name = _singular(domain_name)
    entity_class = _class_name(entity_name)
    parent_field = f"{_singular(parent_domain)}_id" if parent_domain else None
    package_root = project_root / "apps/core_api/src/core_api"
    domain_dir = package_root / "modules" / domain_name
    required_domains = tuple(
        dict.fromkeys(
            value
            for value in (parent_domain, *related_domains)
            if value is not None
        )
    )
    for related_domain in required_domains:
        related_entity = _singular(related_domain)
        entity_path = (
            package_root
            / "modules"
            / related_domain
            / f"{related_entity}_entity.py"
        )
        if not entity_path.exists():
            raise RelationalDomainError(
                f"relational domain requires existing Core entity: {entity_path}"
            )

    association_tables = tuple(
        _association_table(domain_name, related_domain)
        for related_domain in related_domains
    )
    migration_path, revision, down_revision = _next_migration(
        project_root,
        domain_name=domain_name,
        required_tables=required_domains,
        created_tables=(domain_name, *association_tables),
    )
    domain_title = domain_name.replace("_", " ").title()
    hierarchy = (
        f"- `{domain_name}` belongs to `{parent_domain}` through "
        f"the `{parent_field}` foreign key.\n"
        if parent_domain and parent_field
        else ""
    )
    many_to_many = "\n".join(
        f"- `{domain_name}` and `{related_domain}` use the "
        f"`{_association_table(domain_name, related_domain)}` association table."
        for related_domain in related_domains
    )
    notes = (
        f"\n## Notes\n\n{relationship_notes.strip()}\n"
        if relationship_notes and relationship_notes.strip()
        else ""
    )

    files = {
        domain_dir / "__init__.py": "",
        domain_dir / "README.md": _clean(
            f"""
            # {domain_title}

            Generated Core CRUD domain with SQLAlchemy persistence.

            Apply its migration before using the routes:

            ```bash
            make migrate-core
            ```
            """
        ),
        domain_dir / "RELATIONSHIPS.md": _clean(
            f"""
            # {domain_title} Relationships

            Persistence mode: `relational`.

            ## Hierarchy

            {hierarchy or "- No parent foreign key."}

            ## Many To Many

            {many_to_many or "- No association tables."}
            {notes}
            """
        ),
        domain_dir / f"{entity_name}_entity.py": _entity_source(
            domain_name=domain_name,
            entity_name=entity_name,
            entity_class=entity_class,
            parent_domain=parent_domain,
            related_domains=related_domains,
        ),
        domain_dir / f"{entity_name}_schema.py": _schema_source(
            entity_class=entity_class,
            parent_field=parent_field,
            related_domains=related_domains,
        ),
        domain_dir / f"{entity_name}_service.py": _service_source(
            domain_name=domain_name,
            entity_name=entity_name,
            entity_class=entity_class,
            parent_field=parent_field,
            related_domains=related_domains,
        ),
        domain_dir / f"{entity_name}_router.py": _router_source(
            domain_name=domain_name,
            entity_name=entity_name,
            entity_class=entity_class,
            parent_field=parent_field,
            parent_domain=parent_domain,
            related_domains=related_domains,
        ),
        migration_path: _migration_source(
            domain_name=domain_name,
            entity_name=entity_name,
            parent_domain=parent_domain,
            parent_field=parent_field,
            related_domains=related_domains,
            revision=revision,
            down_revision=down_revision,
        ),
    }

    return files, migration_path, revision


def generate_relational_core_domain(
    *,
    project_root: Path,
    domain_name: str,
    parent_domain: str | None = None,
    related_domains: tuple[str, ...] = (),
    relationship_notes: str | None = None,
) -> list[Path]:
    files, _, _ = build_relational_core_domain_files(
        project_root=project_root,
        domain_name=domain_name,
        parent_domain=parent_domain,
        related_domains=related_domains,
        relationship_notes=relationship_notes,
    )
    existing = [path for path in files if path.exists()]
    if existing:
        raise RelationalDomainError(
            f"refusing to overwrite existing file: {existing[0]}"
        )
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return list(files)
