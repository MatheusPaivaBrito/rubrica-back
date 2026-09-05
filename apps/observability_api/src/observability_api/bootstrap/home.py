from fastapi import APIRouter, Request

from observability_api.infrastructure.providers import grafana_status, loki_status, sentry_status
from shared_kernel.http import HomeAction, HomeCard, HomePage, HomeSection, render_service_home


router = APIRouter(include_in_schema=False)


def _card(provider: dict, *, title: str, description: str) -> HomeCard:
    status = str(provider["status"])
    return HomeCard(
        title=title,
        description=description,
        status=status,
        available=status in {"ok", "configured"},
    )


@router.get("/")
def home(request: Request):
    return render_service_home(
        request=request,
        page=HomePage(
            service_name="Observability API",
            eyebrow="FastAPI - Observability - Loki - Grafana - Sentry",
            description=(
                "Observability boundary for readiness, incident capture, dashboard links, "
                "Loki log queries, alert events and release markers."
            ),
            actions=(
                HomeAction(label="Open Swagger Docs", url="/docs", primary=True),
                HomeAction(label="Open ReDoc", url="/redoc"),
                HomeAction(label="Readiness", url="/ready"),
            ),
            sections=(
                HomeSection(
                    title="Providers",
                    description="Local Loki/Grafana plus optional external Sentry.",
                    columns=3,
                    cards=(
                        _card(loki_status(), title="Loki", description="Log storage and query API."),
                        _card(grafana_status(), title="Grafana", description="Dashboards and health endpoint."),
                        _card(sentry_status(), title="Sentry", description="External error tracking when SENTRY_DSN exists."),
                    ),
                ),
                HomeSection(
                    title="Useful flows",
                    description="Small routes for testing observability integration before production wiring.",
                    columns=3,
                    cards=(
                        HomeCard(title="Incidents", status="POST /incidents", description="Capture a local or Sentry-backed incident."),
                        HomeCard(title="Log queries", status="GET /log-queries/query", description="Run simple Loki instant queries."),
                        HomeCard(title="Releases", status="POST /releases/markers", description="Register deployment/release markers."),
                    ),
                ),
            ),
        ),
    )
