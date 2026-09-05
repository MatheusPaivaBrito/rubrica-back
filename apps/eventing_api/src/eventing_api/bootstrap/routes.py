from fastapi import FastAPI

from eventing_api.bootstrap.health import router as health_router
from eventing_api.modules.event_contracts.routes import router as event_contract_router
from eventing_api.modules.outbox.outbox_router import router as outbox_router
from eventing_api.modules.projections.routes import router as projection_router
from eventing_api.modules.schemas.routes import router as schema_router
from eventing_api.modules.streams.routes import router as stream_router
from eventing_api.modules.topics.routes import router as topic_router


def register_routes(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(outbox_router)
    app.include_router(event_contract_router)
    app.include_router(topic_router)
    app.include_router(schema_router)
    app.include_router(stream_router)
    app.include_router(projection_router)
