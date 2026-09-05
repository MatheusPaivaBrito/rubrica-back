from fastapi import APIRouter
from pydantic import BaseModel, Field

from shared_kernel.time import DateTimeService


router = APIRouter(prefix="/releases", tags=["releases"])


class ReleaseMarkerCreate(BaseModel):
    service: str = Field(min_length=2, max_length=80)
    version: str = Field(min_length=1, max_length=80)
    commit_sha: str | None = Field(default=None, max_length=80)
    environment: str = Field(default="development", min_length=2, max_length=80)


@router.post("/markers", summary="Accept a release marker")
def create_release_marker(payload: ReleaseMarkerCreate) -> dict:
    return {**payload.model_dump(), "accepted": True, "marked_at": DateTimeService.utc_now().isoformat()}


@router.get("/examples", summary="List release marker examples")
def list_release_examples() -> dict:
    return {"examples": [{"service": "core_api", "version": "0.1.0", "environment": "development"}]}
