from fastapi import APIRouter


router = APIRouter(tags=["ui - query"])


@router.get("/ui-manifest", summary="Describe Core UI capabilities")
async def get_ui_manifest() -> dict[str, object]:
    return {
        "version": 1,
        "service": "core_api",
        "domains": [],
        "navigation": [],
        "actions": [],
    }
