"""Report listing, sampling, and generation endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import ReportParams, SampleParams
from video_account_distiller.reports import ReportService
from video_account_distiller.sampling import SamplingService
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


@router.post("/{project_path:path}/sample/{account_id}")
async def sample(
    project_path: str,
    account_id: str,
    body: SampleParams = SampleParams(),
    dry_run: bool = False,
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return _spawn(
        request.app.state.tasks,
        SamplingService(layout).select,
        account_id=account_id,
        size=body.size,
        dry_run=dry_run,
    )


@router.post("/{project_path:path}/report/{account_id}")
async def generate_report(
    project_path: str,
    account_id: str,
    body: ReportParams = ReportParams(),
    dry_run: bool = False,
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return _spawn(
        request.app.state.tasks,
        ReportService(layout).generate_account_health,
        account_id=account_id,
        sample_size=body.sample_size,
        dry_run=dry_run,
    )


@router.get("/{project_path:path}/reports/")
async def list_reports(project_path: str) -> dict[str, Any]:
    layout = resolve_project(project_path)
    report_dir = layout.root / "reports" / "accounts"
    items = [p.relative_to(layout.root).as_posix() for p in report_dir.glob("**/report.json")]
    return {"ok": True, "data": {"reports": items}}


@router.get("/{project_path:path}/reports/accounts/{account_id}/")
async def list_account_reports(
    project_path: str, account_id: str
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    account_dir = layout.root / "reports" / "accounts" / account_id
    if not account_dir.is_dir():
        return {"ok": True, "data": {"reports": []}}
    items = [p.relative_to(layout.root).as_posix() for p in account_dir.glob("**/report.json")]
    return {"ok": True, "data": {"reports": items}}


@router.get("/{project_path:path}/reports/accounts/{account_id}/{report_id}/")
async def get_report(
    project_path: str, account_id: str, report_id: str
) -> dict[str, Any]:
    import json

    layout = resolve_project(project_path)
    path = layout.root / "reports" / "accounts" / account_id / report_id / "report.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    return {"ok": True, "data": json.loads(path.read_text(encoding="utf-8"))}
