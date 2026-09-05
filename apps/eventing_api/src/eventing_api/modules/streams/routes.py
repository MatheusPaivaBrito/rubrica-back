from fastapi import APIRouter


router = APIRouter(prefix="/streams", tags=["streams"])


@router.get("")
async def list_streams() -> dict[str, object]:
    return {"streams": ["default"], "status": "planned"}
