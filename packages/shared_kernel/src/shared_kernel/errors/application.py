from dataclasses import dataclass, field as dataclass_field
from typing import Any


@dataclass(frozen=True)
class ErrorTarget:
    location: str | None = None
    entity: str | None = None
    field: str | None = None
    payload: dict[str, Any] = dataclass_field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}

        if self.location:
            data["location"] = self.location
        if self.entity:
            data["entity"] = self.entity
        if self.field:
            data["field"] = self.field
        if self.payload:
            data["payload"] = self.payload

        return data


class ApplicationError(Exception):
    status_code = 500
    code = "application.internal_error"
    message = "An unexpected application error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        target: ErrorTarget | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.target = target or ErrorTarget()
        self.details = details or {}
        super().__init__(self.message)
