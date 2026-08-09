from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel


def create_crud_router(
    *,
    prefix: str,
    tags: list[str] | None = None,
    query_tag: str | None = None,
    command_tag: str | None = None,
    service: Any,
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    read_schema: type[BaseModel],
    not_found_message: str = "Resource not found",
) -> APIRouter:
    router = APIRouter(prefix=prefix)
    fallback_tag = (tags or [prefix.strip("/") or "resources"])[0]
    query_tags = [query_tag or f"{fallback_tag} - query"]
    command_tags = [command_tag or f"{fallback_tag} - command"]

    @router.get("", response_model=list[read_schema], tags=query_tags, summary=f"List {fallback_tag}")
    async def list_resources(include_deleted: bool = False) -> list[Any]:
        return service.list(include_deleted=include_deleted)

    @router.get("/{resource_id}", response_model=read_schema, tags=query_tags, summary=f"Get {fallback_tag}")
    async def get_resource(resource_id: str) -> Any:
        resource = service.get(resource_id)
        if resource is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_message)
        return resource

    @router.post(
        "",
        response_model=read_schema,
        status_code=status.HTTP_201_CREATED,
        tags=command_tags,
        summary=f"Create {fallback_tag}",
    )
    async def create_resource(payload: create_schema) -> Any:
        return service.create(payload)

    @router.patch("/{resource_id}", response_model=read_schema, tags=command_tags, summary=f"Update {fallback_tag}")
    async def update_resource(resource_id: str, payload: update_schema) -> Any:
        resource = service.update(resource_id, payload)
        if resource is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_message)
        return resource

    @router.delete("/{resource_id}", response_model=read_schema, tags=command_tags, summary=f"Delete {fallback_tag}")
    async def delete_resource(resource_id: str) -> Any:
        resource = service.delete(resource_id)
        if resource is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_message)
        return resource

    @router.post(
        "/{resource_id}/restore",
        response_model=read_schema,
        tags=command_tags,
        summary=f"Restore {fallback_tag}",
    )
    async def restore_resource(resource_id: str) -> Any:
        resource = service.restore(resource_id)
        if resource is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_message)
        return resource

    return router
