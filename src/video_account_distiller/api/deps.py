"""FastAPI dependency injection — project resolution and error handling."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from video_account_distiller.errors import DistillerError
from video_account_distiller.storage.project import ProjectLayout


def resolve_project(project_path: str) -> ProjectLayout:
    """Open a distiller project from an endpoint path parameter.

    Returns a ``ProjectLayout`` on success; raises ``HTTPException(400/404)``
    when the path is invalid or the project has not been initialised.
    """
    try:
        root = Path(project_path).expanduser().resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid project path: {exc}") from exc
    try:
        return ProjectLayout.open(root)
    except DistillerError as exc:
        if exc.code.value == "E_PROJECT_NOT_INITIALIZED":
            raise HTTPException(status_code=404, detail=exc.message) from exc
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def distiller_error_to_http(exc: DistillerError) -> HTTPException:
    """Map a ``DistillerError`` to a ``fastapi.HTTPException``."""
    status_map: dict[str, int] = {
        "E_INPUT_MISSING": 400,
        "E_SCHEMA_INVALID": 422,
        "E_FIELD_MAPPING_REQUIRED": 422,
        "E_DUPLICATE_RECORD": 409,
        "E_PLATFORM_UNSUPPORTED": 400,
        "E_PROJECT_EXISTS": 409,
        "E_PROJECT_NOT_INITIALIZED": 404,
        "E_RAW_INTEGRITY": 409,
        "E_QUERY_FAILED": 500,
        "E_INSUFFICIENT_SAMPLE": 422,
        "E_REPORT_GENERATION": 500,
        "E_MODEL_UNAVAILABLE": 503,
        "E_MODEL_SCHEMA_INVALID": 422,
        "E_MEDIA_DECODE": 422,
        "E_ADAPTER_AUTH": 401,
        "E_RATE_LIMIT": 429,
        "E_ADAPTER_RESPONSE": 502,
        "E_PROFILE_URL_INVALID": 400,
        "E_PROVIDER_COST_CONFIRMATION_REQUIRED": 402,
        "E_COLLECTION_BUDGET_EXCEEDED": 422,
        "E_TASK_INTERRUPTED": 409,
        "E_INTERNAL": 500,
    }
    status = status_map.get(exc.code.value, 500)
    return HTTPException(
        status_code=status,
        detail={
            "code": exc.code.value,
            "message": exc.message,
            "details": exc.details,
        },
    )
