"""Read-only account insight endpoints for people and model workflows."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.growth import AccountGrowthService
from video_account_distiller.insights import AnalysisContextService

router = APIRouter()


@router.get("/{project_path:path}/accounts/{account_id}/growth")
async def account_growth(project_path: str, account_id: str) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return AccountGrowthService(layout).summarize(account_id=account_id)


@router.get("/{project_path:path}/accounts/{account_id}/analysis-context")
async def account_analysis_context(
    project_path: str,
    account_id: str,
    max_video_analyses: int = 10,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return AnalysisContextService(layout).build(
        account_id=account_id,
        max_video_analyses=max_video_analyses,
    )
