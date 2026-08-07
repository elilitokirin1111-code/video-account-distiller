"""Curated account knowledge export and optional OpenKB routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    KnowledgeExportParams,
    ObsidianSyncParams,
    OpenKBQueryParams,
    OpenKBSyncParams,
    WeKnoraSyncParams,
)
from video_account_distiller.api.task_jobs import (
    OpenKBQueryJob,
    OpenKBSyncJob,
    enqueue_api_job,
)
from video_account_distiller.knowledge import (
    KnowledgeExportService,
    ObsidianVaultExporter,
    OpenKBIntegrationService,
    WeKnoraSyncService,
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


@router.post("/{project_path:path}/knowledge/obsidian/accounts/{account_id}/sync")
async def sync_account_obsidian(
    project_path: str,
    account_id: str,
    body: ObsidianSyncParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Write curated account knowledge into a local Obsidian vault."""

    layout = resolve_project(project_path)
    return ObsidianVaultExporter(layout).export_account(
        account_id=account_id,
        vault_path=body.vault_path,
        max_video_analyses=body.max_video_analyses,
        max_export_bytes=body.max_export_bytes,
        dry_run=dry_run,
    )


@router.post("/{project_path:path}/knowledge/weknora/accounts/{account_id}/sync")
async def sync_account_weknora(
    project_path: str,
    account_id: str,
    body: WeKnoraSyncParams,
) -> dict[str, Any]:
    """Upload the human-readable analysis reports into a WeKnora knowledge base."""

    layout = resolve_project(project_path)
    return WeKnoraSyncService(layout).sync_account(
        account_id=account_id,
        base_url=body.base_url,
        api_key=body.api_key,
        kb_name=body.kb_name,
        max_video_analyses=body.max_video_analyses,
    )


@router.post("/{project_path:path}/knowledge/openkb/accounts/{account_id}/sync")
async def sync_account_knowledge(
    project_path: str,
    account_id: str,
    request: Request,
    body: OpenKBSyncParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    service = _integration(str(layout.root), require_remote_token=not dry_run)
    if not dry_run:
        service.require_model_confirmation(body.confirm_model_processing)
    return enqueue_api_job(
        request.app.state.tasks,
        OpenKBSyncJob(
            project_path=str(layout.root),
            account_id=account_id,
            body=body,
            dry_run=dry_run,
        ),
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
    layout = resolve_project(project_path)
    service = _integration(str(layout.root))
    service.require_model_confirmation(body.confirm_model_processing)
    return enqueue_api_job(
        request.app.state.tasks,
        OpenKBQueryJob(
            project_path=str(layout.root),
            body=body,
        ),
    )
