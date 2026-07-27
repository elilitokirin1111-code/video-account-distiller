"""Account distillation and benchmark comparison endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import CompareParams
from video_account_distiller.api.tasks import enqueue_task
from video_account_distiller.distillation import (
    AccountDistillationService,
    BenchmarkComparisonService,
)

router = APIRouter()


@router.post("/{project_path:path}/distill/{account_id}")
async def distill(
    project_path: str,
    account_id: str,
    request: Request,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_task(
        request.app.state.tasks,
        AccountDistillationService(layout).distill,
        account_id=account_id,
        dry_run=dry_run,
    )


@router.post("/{project_path:path}/compare")
async def compare(
    project_path: str,
    request: Request,
    body: CompareParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_task(
        request.app.state.tasks,
        BenchmarkComparisonService(layout).compare,
        target_account_id=body.target_account_id,
        benchmark_account_ids=body.benchmark_account_ids,
        dry_run=dry_run,
    )
