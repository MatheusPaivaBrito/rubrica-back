from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared_kernel.errors.application import ApplicationError, ErrorTarget


def register_exception_handlers(app: FastAPI, *, service_name: str) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_application_error_content(request, exc, service_name=service_name),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_validation_error_content(request, exc.errors(), service_name=service_name),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_http_error_content(request, exc, service_name=service_name),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_unexpected_error_content(request, exc, service_name=service_name),
        )


def _base_content(
    request: Request,
    *,
    service_name: str,
    status_code: int,
    code: str,
    message: str,
    target: ErrorTarget | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "status_code": status_code,
        "service": service_name,
        "method": request.method,
        "path": request.url.path,
        "trace_id": _trace_id(request),
    }

    if target:
        target_payload = target.as_dict()
        if target_payload:
            error["target"] = target_payload
    if details:
        error["details"] = details

    return {"error": error}


def _application_error_content(
    request: Request,
    exc: ApplicationError,
    *,
    service_name: str,
) -> dict[str, Any]:
    return _base_content(
        request,
        service_name=service_name,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        target=exc.target,
        details=exc.details,
    )


def _validation_error_content(
    request: Request,
    errors: Iterable[dict[str, Any]],
    *,
    service_name: str,
) -> dict[str, Any]:
    normalized_errors = [_normalize_validation_error(error) for error in errors]
    first_error = normalized_errors[0] if normalized_errors else {}

    return _base_content(
        request,
        service_name=service_name,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="request.validation_error",
        message="Request validation failed.",
        target=ErrorTarget(
            location=first_error.get("location"),
            field=first_error.get("field"),
            payload={"errors": normalized_errors},
        ),
    )


def _http_error_content(
    request: Request,
    exc: StarletteHTTPException,
    *,
    service_name: str,
) -> dict[str, Any]:
    message = exc.detail if isinstance(exc.detail, str) else "HTTP request failed."

    return _base_content(
        request,
        service_name=service_name,
        status_code=exc.status_code,
        code=_http_error_code(exc.status_code),
        message=message,
    )


def _unexpected_error_content(
    request: Request,
    exc: Exception,
    *,
    service_name: str,
) -> dict[str, Any]:
    return _base_content(
        request,
        service_name=service_name,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="application.unhandled_error",
        message="An unexpected internal error occurred.",
        details={"exception": exc.__class__.__name__},
    )


def _normalize_validation_error(error: dict[str, Any]) -> dict[str, Any]:
    raw_location = [str(part) for part in error.get("loc", [])]
    location = raw_location[0] if raw_location else None
    field = ".".join(raw_location[1:]) if len(raw_location) > 1 else None

    normalized: dict[str, Any] = {
        "message": error.get("msg", "Invalid value."),
        "type": error.get("type", "validation_error"),
    }

    if location:
        normalized["location"] = location
    if field:
        normalized["field"] = field

    return normalized


def _http_error_code(status_code: int) -> str:
    if status_code == status.HTTP_404_NOT_FOUND:
        return "http.not_found"
    if status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        return "http.method_not_allowed"
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "http.unauthorized"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "http.forbidden"
    return "http.error"


def _trace_id(request: Request) -> str:
    return request.headers.get("x-request-id") or str(uuid4())
