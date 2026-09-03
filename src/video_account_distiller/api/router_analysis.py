"""Analysis endpoints with async task support."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    AccountMediaReparseParams,
    CommentAnalysisParams,
    MediaAnalysisParams,
    VideoAnalysisParams,
)
from video_account_distiller.api.task_jobs import (
    AccountMediaReparseJob,
    AnalyzeCommentsJob,
    AnalyzeMediaJob,
    AnalyzeVideoJob,
    enqueue_api_job,
)
from video_account_distiller.media import AccountMediaEnrichmentService

router = APIRouter()


# ── video analysis ──────────────────────────────────────────────────


@router.post("/{project_path:path}/analyze/video/{video_id}")
async def analyze_video(
    project_path: str,
    video_id: str,
    request: Request,
    body: VideoAnalysisParams = VideoAnalysisParams(
        model_output=None,
        max_attempts=None,
        deep=False,
        deep_provider=None,
        deep_model=None,
        deep_base_url=None,
        deep_output=None,
        strict_deep=False,
    ),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        AnalyzeVideoJob(
            project_path=str(layout.root),
            video_id=video_id,
            body=body,
            dry_run=dry_run,
        ),
    )


# ── comment analysis ─────────────────────────────────────────────────


@router.post("/{project_path:path}/analyze/comments/{account_id}")
async def analyze_comments(
    project_path: str,
    account_id: str,
    request: Request,
    body: CommentAnalysisParams = CommentAnalysisParams(model_output=None, max_attempts=None),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        AnalyzeCommentsJob(
            project_path=str(layout.root),
            account_id=account_id,
            body=body,
            dry_run=dry_run,
        ),
    )


# ── media analysis ───────────────────────────────────────────────────


@router.post("/{project_path:path}/analyze/media/{video_id}")
async def analyze_media(
    project_path: str,
    video_id: str,
    request: Request,
    body: MediaAnalysisParams = MediaAnalysisParams(
        file=None,
        vision_output=None,
        scene_threshold=None,
        max_keyframes=None,
    ),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        AnalyzeMediaJob(
            project_path=str(layout.root),
            video_id=video_id,
            body=body,
            dry_run=dry_run,
        ),
    )


@router.get("/{project_path:path}/analyze/accounts/{account_id}/media/reparse-candidates")
async def media_reparse_candidates(
    project_path: str,
    account_id: str,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return AccountMediaEnrichmentService(layout).reparse_candidates(account_id=account_id)


@router.post("/{project_path:path}/analyze/accounts/{account_id}/media/reparse")
async def reparse_account_media(
    project_path: str,
    account_id: str,
    request: Request,
    body: AccountMediaReparseParams = AccountMediaReparseParams(),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        AccountMediaReparseJob(
            project_path=str(layout.root),
            account_id=account_id,
            body=body,
            dry_run=dry_run,
        ),
    )
