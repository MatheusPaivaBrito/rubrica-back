from typing import Any

from core_api.shared.auth import core_auth_guard
from shared_kernel.http.crud.route_factory import create_crud_router as create_shared_crud_router


def create_crud_router(**kwargs: Any):
    return create_shared_crud_router(
        **kwargs,
        read_dependencies=core_auth_guard.route_dependencies(),
        command_dependencies=core_auth_guard.route_dependencies(),
    )
