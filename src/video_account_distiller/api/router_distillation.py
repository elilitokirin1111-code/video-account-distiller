"""Account distillation and benchmark comparison endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import CompareParams
from video_account_distiller.distillation import (
    AccountDistillationService,
    BenchmarkComparisonService,
)
from video_account_distiller.utils.ids import new_run_id

router = APIRouter()


def _spawn(tasks: dict, fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    task_id = new_run_id()
    tasks[task_id] = {"task_id": task_id, "status": "pending", "progress": 0}

    async def _runner() -> None:
        try:
            tasks[task_id]["status"] = "running"
            result = await asyncio.to_thread(fn, *args, **kwargs)
            tasks[task_id].update(status="completed", result=result)
        except Exception as exc:
            tasks[task_id].update(
                status="failed",
                error={"code": getattr(exc, "code", "E_INTERNAL"), "message": str(exc)},
            )

    asyncio.ensure_future(_runner())
    return {"ok": True, "task_id": task_id, "status": "pending"}


@router.post("/{project_path:path}/distill/{account_id}")
async def distill(
    project_path: str,
    account_id: str,
    dry_run: bool = False,
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return _spawn(
        request.app.state.tasks,
        AccountDistillationService(layout).distill,
        account_id=account_id,
        dry_run=dry_run,
    )


@router.post("/{project_path:path}/compare")
async def compare(
    project_path: str,
    body: CompareParams,
    dry_run: bool = False,
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return _spawn(
        request.app.state.tasks,
        BenchmarkComparisonService(layout).compare,
        target_account_id=body.target_account_id,
        benchmark_account_ids=body.benchmark_account_ids,
        dry_run=dry_run,
    )
