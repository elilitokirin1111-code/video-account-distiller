"""Report listing, sampling, and generation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import ReportParams, SampleParams
from video_account_distiller.api.task_jobs import (
    ReportJob,
    SampleJob,
    enqueue_api_job,
)

router = APIRouter()


@router.post("/{project_path:path}/sample/{account_id}")
async def sample(
    project_path: str,
    account_id: str,
    request: Request,
    body: SampleParams = SampleParams(size=None),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        SampleJob(
            project_path=str(layout.root),
            account_id=account_id,
            body=body,
            dry_run=dry_run,
        ),
    )


@router.post("/{project_path:path}/report/{account_id}")
async def generate_report(
    project_path: str,
    account_id: str,
    request: Request,
    body: ReportParams = ReportParams(sample_size=None),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        ReportJob(
            project_path=str(layout.root),
            account_id=account_id,
            body=body,
            dry_run=dry_run,
        ),
    )


@router.get("/{project_path:path}/reports/")
async def list_reports(project_path: str) -> dict[str, Any]:
    layout = resolve_project(project_path)
    report_dir = layout.root / "reports" / "accounts"
    items = [p.relative_to(layout.root).as_posix() for p in report_dir.glob("**/report.json")]
    return {"ok": True, "data": {"reports": items}}


@router.get("/{project_path:path}/reports/accounts/{account_id}/")
async def list_account_reports(project_path: str, account_id: str) -> dict[str, Any]:
    layout = resolve_project(project_path)
    account_dir = layout.root / "reports" / "accounts" / account_id
    if not account_dir.is_dir():
        return {"ok": True, "data": {"reports": []}}
    items = [p.relative_to(layout.root).as_posix() for p in account_dir.glob("**/report.json")]
    return {"ok": True, "data": {"reports": items}}


@router.get("/{project_path:path}/reports/accounts/{account_id}/{report_id}/")
async def get_report(project_path: str, account_id: str, report_id: str) -> dict[str, Any]:
    import json

    layout = resolve_project(project_path)
    path = layout.root / "reports" / "accounts" / account_id / report_id / "report.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    markdown_path = path.with_name("report.md")
    markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else None
    data_gaps_path = path.with_name("data-gaps.json")
    data_gaps = (
        json.loads(data_gaps_path.read_text(encoding="utf-8")) if data_gaps_path.is_file() else None
    )
    return {
        "ok": True,
        "data": json.loads(path.read_text(encoding="utf-8")),
        "markdown": markdown,
        "data_gaps": data_gaps,
    }
