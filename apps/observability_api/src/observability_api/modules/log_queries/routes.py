from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, Field

from observability_api.infrastructure.providers import list_loki_labels, query_loki


router = APIRouter(prefix="/log-queries", tags=["log_queries"])


class LogQueryExample(BaseModel):
    description: str
    query: str = Field(min_length=1)


@router.get("/labels", summary="List Loki labels")
def list_labels() -> dict:
    return {"provider": "loki", "result": list_loki_labels()}


@router.get("/query", summary="Run an instant Loki query")
def run_query(
    query: str = Query(default='{service=~".+"}', min_length=1, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    return {"query": query, "limit": limit, "result": query_loki(query, limit=limit)}


@router.get("/correlations/{correlation_id}", summary="Find logs for one correlation id")
def find_correlation(
    correlation_id: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    query = f'{{service=~".+"}} |= "{correlation_id}"'
    return {"query": query, "limit": limit, "result": query_loki(query, limit=limit)}


@router.get("/examples", response_model=list[LogQueryExample], summary="List useful Loki query examples")
def list_examples() -> list[LogQueryExample]:
    return [
        LogQueryExample(description="All logs carrying a service label.", query='{service=~".+"}'),
        LogQueryExample(description="Errors by level label.", query='{level=~"error|critical"}'),
    ]
