from fastapi import APIRouter, Depends

from core_api.infrastructure.auth_context import authenticated_context


router = APIRouter(tags=["ui - query"])


@router.get("/ui-manifest", summary="Describe Core UI capabilities")
async def get_ui_manifest(_context=Depends(authenticated_context)) -> dict[str, object]:
    return {
        "version": 1,
        "service": "core_api",
        "domains": [],
        "navigation": [],
        "actions": [],
    }
