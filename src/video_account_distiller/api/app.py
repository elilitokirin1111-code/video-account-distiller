"""FastAPI application factory for the distiller REST API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from video_account_distiller.api.tasks import TaskStore
from video_account_distiller.errors import DistillerError
from video_account_distiller.logging import configure_logging


def create_app(task_db_path: Path | str | None = None) -> FastAPI:
    """Build the FastAPI app with all routers and middleware."""
    configure_logging()
    task_store = TaskStore(task_db_path)

    app = FastAPI(
        title="Video Account Distiller API",
        description="REST API for evidence-based video account analysis and reporting.",
        version="1.0.0",
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

    # Register routers (lazy import to avoid circular dependencies)
    from video_account_distiller.api.router_analysis import router as analysis_router
    from video_account_distiller.api.router_closed_loop import router as closed_loop_router
    from video_account_distiller.api.router_collection import router as collection_router
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
        tasks = task_store.list(limit=limit, status=status)
        return {"ok": True, "tasks": tasks, "count": len(tasks)}

    @app.get("/api/tasks/{task_id}", tags=["Tasks"])
    async def get_task(task_id: str) -> dict[str, Any]:
        task = task_store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        return task

    app.state.tasks = task_store

    @app.get("/api/health", tags=["Health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "1.0.0"}

    return app


# ---------------------------------------------------------------------------
# CLI entry-points
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the API server (``distiller-api`` entry-point)."""
    import uvicorn

    port = int(os.environ.get("DISTILLER_API_PORT", "8000"))
    host = os.environ.get("DISTILLER_API_HOST", "127.0.0.1")
    uvicorn.run(
        "video_account_distiller.api.app:create_app",
        host=host,
        port=port,
        factory=True,
        reload=True,
    )
