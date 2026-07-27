"""Curated account knowledge export and optional OpenKB routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    KnowledgeExportParams,
    OpenKBQueryParams,
    OpenKBSyncParams,
)
from video_account_distiller.api.tasks import enqueue_task
from video_account_distiller.knowledge import (
    KnowledgeExportService,
    OpenKBIntegrationService,
    resolve_openkb_target,
)

router = APIRouter()


def _integration(
    project_path: str,
    *,
    require_remote_token: bool = True,
) -> OpenKBIntegrationService:
    layout = resolve_project(project_path)
    target, token = resolve_openkb_target(
        layout,
        require_remote_token=require_remote_token,
    )
    return OpenKBIntegrationService.from_target(layout, target, token=token)


@router.post("/{project_path:path}/knowledge/openkb/accounts/{account_id}/export")
async def export_account_knowledge(
    project_path: str,
    account_id: str,
    body: KnowledgeExportParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return KnowledgeExportService(layout).export_account(
        account_id=account_id,
        max_video_analyses=body.max_video_analyses,
        max_export_bytes=body.max_export_bytes,
        dry_run=dry_run,
    )


@router.post("/{project_path:path}/knowledge/openkb/accounts/{account_id}/sync")
async def sync_account_knowledge(
    project_path: str,
    account_id: str,
    request: Request,
    body: OpenKBSyncParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    service = _integration(project_path, require_remote_token=not dry_run)
    if not dry_run:
        service.require_model_confirmation(body.confirm_model_processing)
    return enqueue_task(
        request.app.state.tasks,
        service.sync_account,
        account_id=account_id,
        confirm_model_processing=body.confirm_model_processing,
        create_kb=body.create_kb,
        force=body.force,
        max_video_analyses=body.max_video_analyses,
        max_export_bytes=body.max_export_bytes,
        dry_run=dry_run,
    )


@router.get("/{project_path:path}/knowledge/openkb/accounts/{account_id}/status")
async def account_knowledge_status(
    project_path: str,
    account_id: str,
    remote: bool = False,
) -> dict[str, Any]:
    return _integration(project_path, require_remote_token=remote).status(
        account_id=account_id,
        remote=remote,
    )


@router.post("/{project_path:path}/knowledge/openkb/query")
async def query_account_knowledge(
    project_path: str,
    request: Request,
    body: OpenKBQueryParams,
) -> dict[str, Any]:
    service = _integration(project_path)
    service.require_model_confirmation(body.confirm_model_processing)
    return enqueue_task(
        request.app.state.tasks,
        service.query,
        question=body.question,
        confirm_model_processing=body.confirm_model_processing,
        save=body.save,
    )
