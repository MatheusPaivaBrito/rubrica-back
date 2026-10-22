from __future__ import annotations

from collections.abc import Callable, Iterable
import os
from time import perf_counter

from fastapi import FastAPI, Request, Response
from prometheus_client import CollectorRegistry, Counter, Histogram, multiprocess
from prometheus_client.metrics_core import Metric
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST, generate_latest


MetricCollector = Callable[[], Iterable[Metric]]

HTTP_REQUESTS = Counter(
    "rubrica_http_requests_total",
    "Total de requisicoes HTTP processadas pelas APIs do Rubrica.",
    ("service", "method", "route", "status_class"),
)
HTTP_REQUEST_DURATION = Histogram(
    "rubrica_http_request_duration_seconds",
    "Duracao das requisicoes HTTP processadas pelas APIs do Rubrica.",
    ("service", "method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


class _CallableCollector:
    def __init__(self, collect: MetricCollector) -> None:
        self._collect = collect

    def collect(self) -> Iterable[Metric]:
        return self._collect()


def _registry(extra_collectors: tuple[MetricCollector, ...]) -> CollectorRegistry:
    registry = CollectorRegistry()
    if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.MultiProcessCollector(registry)
    else:
        registry.register(HTTP_REQUESTS)
        registry.register(HTTP_REQUEST_DURATION)
    for collector in extra_collectors:
        registry.register(_CallableCollector(collector))
    return registry


def apply_metrics(
    app: FastAPI,
    *,
    service_name: str,
    collectors: tuple[MetricCollector, ...] = (),
) -> None:
    @app.middleware("http")
    async def prometheus_http_metrics(request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)
        started_at = perf_counter()
        response = await call_next(request)
        HTTP_REQUESTS.labels(
            service_name,
            request.method,
            _route_label(request),
            f"{response.status_code // 100}xx",
        ).inc()
        HTTP_REQUEST_DURATION.labels(
            service_name, request.method, _route_label(request)
        ).observe(perf_counter() - started_at)
        return response

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(
            content=generate_latest(_registry(collectors)),
            media_type=CONTENT_TYPE_LATEST,
        )
