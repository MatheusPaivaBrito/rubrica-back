from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from eventing_api.infrastructure.database.connection import get_session
from eventing_api.modules.outbox.outbox_repository import OutboxRepository
from eventing_api.modules.projections.service import projection_service


router = APIRouter(prefix="/projections", tags=["projections"])


@router.get("")
async def list_projections() -> dict[str, object]:
    return {
        "projections": [
            {"name": "outbox-summary", "status": "available"},
            {"name": "auth-session-audit", "status": "available"},
            {"name": "notification-delivery", "status": "available"},
        ]
    }


def _projection(
    session: Session,
    *,
    event_type_prefix: str | None,
    limit: int,
) -> dict[str, object]:
    return projection_service.event_family(
        OutboxRepository(session),
        event_type_prefix=event_type_prefix,
        limit=limit,
    )


@router.get("/outbox-summary")
async def outbox_summary(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return _projection(session, event_type_prefix=None, limit=limit)


@router.get("/auth-session-audit")
async def auth_session_audit(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return _projection(session, event_type_prefix="auth", limit=limit)


@router.get("/notification-delivery")
async def notification_delivery(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return _projection(
        session,
        event_type_prefix="notification",
        limit=limit,
    )
