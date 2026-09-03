"""FastAPI application factory for the distiller REST API."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from video_account_distiller.api.schemas import TaskRetryRequest
from video_account_distiller.api.task_jobs import TASK_HANDLERS
from video_account_distiller.api.tasks import (
    TaskQueueSettings,
    TaskStore,
    TaskWorkerPool,
    retry_persistent_task,
)
from video_account_distiller.errors import DistillerError
from video_account_distiller.insights import KeyringCloudCredentialStore
from video_account_distiller.logging import configure_logging
from video_account_distiller.version import PACKAGE_VERSION

_SENSITIVE_VALIDATION_KEYS = (
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


def _redact_validation_input(value: Any, *, field_name: str = "") -> Any:
    """Make FastAPI validation diagnostics safe to return to API clients."""

    normalized_name = "".join(
        character for character in field_name.casefold() if character.isalnum()
    )
    if any(token in normalized_name for token in _SENSITIVE_VALIDATION_KEYS):
        return "**********"
    if isinstance(value, SecretStr):
        return "**********"
    if isinstance(value, dict):
        return {
            key: _redact_validation_input(item, field_name=str(key)) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_validation_input(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_validation_input(item) for item in value)
    return value


def create_app(
    task_db_path: Path | str | None = None,
    *,
    task_queue_settings: TaskQueueSettings | None = None,
) -> FastAPI:
    """Build the FastAPI app with all routers and middleware."""
    configure_logging()
    task_store = TaskStore(task_db_path, queue_settings=task_queue_settings)
    task_workers = TaskWorkerPool(task_store, TASK_HANDLERS)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await task_workers.start()
        try:
            yield
        finally:
            await task_workers.stop()

    app = FastAPI(
        title="Video Account Distiller API",
        description="REST API for evidence-based video account analysis and reporting.",
        version=PACKAGE_VERSION,
        lifespan=lifespan,
    )

    # CORS — allow Streamlit dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8501",
            "http://127.0.0.1:8501",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handler that bridges DistillerError to HTTP responses
    @app.exception_handler(DistillerError)
    async def _handle_distiller_error(request: Request, exc: DistillerError) -> JSONResponse:
        from video_account_distiller.api.deps import distiller_error_to_http

        http_exc = distiller_error_to_http(exc)
        return JSONResponse(
            status_code=http_exc.status_code,
            content={"ok": False, "error": exc.as_dict()["error"]},
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # Starlette's default 422 response includes Pydantic's ``input`` value.
        # A legacy client may still submit ``cloud_api_key`` in that input, so
        # recursively mask credential-shaped fields before serializing it.
        errors = [_redact_validation_input(error) for error in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder({"detail": errors}),
        )

    # Register routers (lazy import to avoid circular dependencies)
    from video_account_distiller.api.router_analysis import router as analysis_router
    from video_account_distiller.api.router_closed_loop import router as closed_loop_router
    from video_account_distiller.api.router_collection import router as collection_router
    from video_account_distiller.api.router_data import router as data_router
    from video_account_distiller.api.router_distillation import router as distillation_router
    from video_account_distiller.api.router_doctor import router as doctor_router
    from video_account_distiller.api.router_import import router as import_router
    from video_account_distiller.api.router_insights import router as insights_router
    from video_account_distiller.api.router_knowledge import router as knowledge_router
    from video_account_distiller.api.router_projects import router as projects_router
    from video_account_distiller.api.router_reports import router as reports_router
    from video_account_distiller.api.router_status import router as status_router
    from video_account_distiller.api.router_workflows import router as workflows_router

    app.include_router(doctor_router, prefix="/api", tags=["Doctor"])
    app.include_router(projects_router, prefix="/api", tags=["Projects"])
    app.include_router(status_router, prefix="/api/projects", tags=["Status"])
    app.include_router(import_router, prefix="/api/projects", tags=["Import"])
    app.include_router(data_router, prefix="/api/projects", tags=["Data"])
    app.include_router(insights_router, prefix="/api/projects", tags=["Insights"])
    app.include_router(knowledge_router, prefix="/api/projects", tags=["Knowledge"])
    app.include_router(analysis_router, prefix="/api/projects", tags=["Analysis"])
    app.include_router(distillation_router, prefix="/api/projects", tags=["Distillation"])
    app.include_router(closed_loop_router, prefix="/api/projects", tags=["Closed Loop"])
    app.include_router(reports_router, prefix="/api/projects", tags=["Reports"])
    app.include_router(collection_router, prefix="/api/projects", tags=["Collection"])
    app.include_router(workflows_router, prefix="/api/projects", tags=["Workflows"])

    # Task status endpoint
    @app.get("/api/tasks", tags=["Tasks"])
    async def list_tasks(limit: int = 50, status: str | None = None) -> dict[str, Any]:
        tasks = task_store.list_summaries(limit=limit, status=status)
        return {"ok": True, "tasks": tasks, "count": len(tasks)}

    @app.get("/api/task-queue", tags=["Tasks"])
    async def task_queue_status() -> dict[str, Any]:
        return task_store.queue_status()

    @app.get("/api/tasks/{task_id}", tags=["Tasks"])
    async def get_task(task_id: str) -> dict[str, Any]:
        task = task_store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        return task

    @app.post("/api/tasks/{task_id}/cancel", tags=["Tasks"])
    async def cancel_task(task_id: str) -> dict[str, Any]:
        task = task_store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        return task_store.request_cancel(task_id)

    @app.post("/api/tasks/{task_id}/retry", tags=["Tasks"])
    async def retry_task(
        task_id: str,
        body: TaskRetryRequest | None = None,
    ) -> dict[str, Any]:
        task = task_store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        if task.get("status") not in {"failed", "cancelled"}:
            raise HTTPException(
                status_code=409,
                detail="Only failed or cancelled tasks can be retried",
            )
        if not task.get("retryable") or (
            not task.get("durable") and task.get("task_type") != "account_distill"
        ):
            raise HTTPException(
                status_code=409,
                detail="This task type does not support persisted retry",
            )
        if task.get("task_type") == "account_distill":
            from video_account_distiller.api.router_workflows import (
                retry_account_distill_task,
            )

            return retry_account_distill_task(
                task_store,
                task,
                overrides=body.overrides if body is not None else None,
            )
        return retry_persistent_task(task_store, task)

    app.state.tasks = task_store
    app.state.task_workers = task_workers
    app.state.cloud_credentials = KeyringCloudCredentialStore()

    @app.get("/api/health", tags=["Health"])
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": PACKAGE_VERSION,
            "features": {
                # The Streamlit process can hot-reload while the embedded API
                # keeps older modules in memory.  The UI checks this capability
                # before submitting knowledge-mode jobs so an old backend can
                # never silently reinterpret them as creative-learning jobs.
                "account_video_knowledge": "1",
            },
        }

    return app


# ---------------------------------------------------------------------------
# CLI entry-points
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the API server (``distiller-api`` entry-point)."""
    import uvicorn

    port = int(os.environ.get("DISTILLER_API_PORT", "8000"))
    host = os.environ.get("DISTILLER_API_HOST", "127.0.0.1")
    reload_enabled = os.environ.get("DISTILLER_API_RELOAD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    uvicorn.run(
        "video_account_distiller.api.app:create_app",
        host=host,
        port=port,
        factory=True,
        reload=reload_enabled,
    )
