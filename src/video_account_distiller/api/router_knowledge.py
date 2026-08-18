"""Local curated-knowledge, Obsidian, and WeKnora routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    KnowledgeExportParams,
    ObsidianSyncParams,
    WeKnoraConnectionParams,
    WeKnoraSyncParams,
)
from video_account_distiller.knowledge import (
    KnowledgeExportService,
    ObsidianVaultExporter,
    WeKnoraSyncService,
)

router = APIRouter()


@router.post("/{project_path:path}/knowledge/local/accounts/{account_id}/export")
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
        kb_id=body.kb_id,
        max_video_analyses=body.max_video_analyses,
    )


@router.post("/{project_path:path}/knowledge/weknora/videos/{video_id}/sync")
async def sync_video_weknora(
    project_path: str,
    video_id: str,
    body: WeKnoraSyncParams,
) -> dict[str, Any]:
    """Upload one video's single-video deep distillation card into WeKnora."""

    layout = resolve_project(project_path)
    return WeKnoraSyncService(layout).sync_video_distillation(
        video_id=video_id,
        base_url=body.base_url,
        api_key=body.api_key,
        kb_id=body.kb_id,
    )


@router.post("/{project_path:path}/knowledge/weknora/knowledge-bases")
async def list_weknora_knowledge_bases(
    project_path: str,
    body: WeKnoraConnectionParams,
) -> dict[str, Any]:
    """List WeKnora knowledge bases visible to the supplied API Key."""

    layout = resolve_project(project_path)
    knowledge_bases = WeKnoraSyncService(layout).list_knowledge_bases(
        base_url=body.base_url,
        api_key=body.api_key,
    )
    return {"ok": True, "knowledge_bases": knowledge_bases}
