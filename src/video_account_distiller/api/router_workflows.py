"""Self-service workflow endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import AccountDistillWorkflowParams
from video_account_distiller.api.tasks import enqueue_progress_task
from video_account_distiller.collection import (
    build_account_provider,
    build_collection_request,
    resolve_profile_options,
)
from video_account_distiller.workflows import AccountDistillWorkflow

router = APIRouter()


@router.post("/{project_path:path}/workflows/account-distill")
async def account_distill_workflow(
    project_path: str,
    request: Request,
    body: AccountDistillWorkflowParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Submit one complete homepage-to-knowledge workflow."""

    layout = resolve_project(project_path)
    count, comments_per_video = resolve_profile_options(
        profile=body.profile,
        count=body.count,
        all_videos=body.all_videos,
        comments_per_video=body.comments_per_video,
    )
    collection_request = build_collection_request(
        profile_url=body.url,
        count=count,
        sort=body.sort,
        provider=body.provider,
        comments_per_video=comments_per_video,
        comment_video_limit=body.comment_video_limit,
    )
    provider = build_account_provider(body.provider)
    workflow = AccountDistillWorkflow(layout, provider)
    return enqueue_progress_task(
        request.app.state.tasks,
        workflow.run,
        task_type="account_distill",
        request=collection_request,
        collection_profile=body.profile,
        confirm_provider_cost=body.confirm_provider_cost,
        max_provider_calls=body.max_provider_calls,
        media_limit=body.media_limit,
        whisper_model=body.whisper_model,
        whisper_command=Path(body.whisper_command) if body.whisper_command else None,
        vision_provider=body.vision_provider,
        vision_model=body.vision_model,
        ollama_base_url=body.ollama_base_url,
        vision_batch_size=body.vision_batch_size,
        vision_timeout_seconds=body.vision_timeout_seconds,
        strict_media_enrichment=body.strict_media_enrichment,
        strict_vision=body.strict_vision,
        export_knowledge=body.export_knowledge,
        dry_run=dry_run,
    )
