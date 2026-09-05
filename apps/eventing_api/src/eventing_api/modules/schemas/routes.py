from fastapi import APIRouter


router = APIRouter(prefix="/schemas", tags=["schemas"])


@router.get("")
async def list_schemas() -> dict[str, object]:
    return {"schemas": ["document-uploaded.v1", "signature-request-opened.v1", "signature-completed.v1", "tenant-created.v1"]}
