from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from eventing_api.infrastructure.database.connection import get_session
from eventing_api.modules.outbox.outbox_repository import OutboxRepository
from eventing_api.modules.outbox.outbox_schema import EventIn, OutboxRecord
from eventing_api.modules.outbox.outbox_service import outbox_service


router = APIRouter(tags=["outbox"])


@router.post("/events", response_model=OutboxRecord, status_code=status.HTTP_202_ACCEPTED, tags=["events"])
async def register_event(payload: EventIn, session: Session = Depends(get_session)) -> OutboxRecord:
    event = outbox_service.register(payload, OutboxRepository(session))
    return OutboxRecord.model_validate(event)


@router.get("/outbox", response_model=list[OutboxRecord])
async def list_outbox(status: str | None = None, limit: int = 50, session: Session = Depends(get_session)) -> list[OutboxRecord]:
    repository = OutboxRepository(session)
    return [OutboxRecord.model_validate(event) for event in repository.list(status=status, limit=limit)]
