"""Phase 8 online collection endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    CollectionAnalyzeParams,
    VideoUrlCollectParams,
)
from video_account_distiller.api.task_jobs import (
    CollectionAnalyzeJob,
    enqueue_api_job,
)
from video_account_distiller.collection import (
    AccountCollectionService,
    build_account_provider,
    build_collection_request,
    resolve_comment_video_limit,
    resolve_profile_options,
)

router = APIRouter()


@router.post("/{project_path:path}/collection/analyze")
async def collection_analyze(
    project_path: str,
    request: Request,
    body: CollectionAnalyzeParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    count, comments_per_video = resolve_profile_options(
        profile=body.profile,
        count=body.count,
        all_videos=body.all_videos,
        comments_per_video=body.comments_per_video,
    )
    build_collection_request(
        profile_url=body.url,
        count=count,
        sort=body.sort,
        provider=body.provider,
        comments_per_video=comments_per_video,
        comment_video_limit=resolve_comment_video_limit(
            count=count,
            configured_limit=body.comment_video_limit,
        ),
    )
    build_account_provider(body.provider)
    return enqueue_api_job(
        request.app.state.tasks,
        CollectionAnalyzeJob(
            project_path=str(layout.root),
            body=body,
            dry_run=dry_run,
        ),
    )


@router.post("/{project_path:path}/collection/analyze-video-url")
async def collection_analyze_video_url(
    project_path: str,
    body: VideoUrlCollectParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Collect one public video by URL and import it into the offline kernel.

    The single-video path intentionally runs synchronously: it makes at most
    two bounded provider calls and returns the internal account_id/video_id the
    deep-distillation and WeKnora steps need.
    """
    layout = resolve_project(project_path)
    service = AccountCollectionService(
        layout,
        build_account_provider(body.provider),
    )
    return service.analyze_video_url(
        url=body.url,
        provider=body.provider,
        confirm_provider_cost=body.confirm_provider_cost,
        comments_per_video=body.comments_per_video,
        dry_run=dry_run,
    )
