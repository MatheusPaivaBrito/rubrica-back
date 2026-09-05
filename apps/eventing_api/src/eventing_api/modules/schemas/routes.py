from fastapi import APIRouter


router = APIRouter(prefix="/schemas", tags=["schemas"])


@router.get("")
async def list_schemas() -> dict[str, object]:
    return {"schemas": ["example-event.v1"]}
