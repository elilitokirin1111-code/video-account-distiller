"""Read-only normalized data and import-provenance endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.data_browser import BrowsableTable, NormalizedDataBrowser
from video_account_distiller.models import DataSourceTier

router = APIRouter()


@router.get("/{project_path:path}/data")
async def browse_data(
    project_path: str,
    table: BrowsableTable,
    source_tier: DataSourceTier | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Browse an allow-listed normalized table with optional source filtering."""

    browser = NormalizedDataBrowser(resolve_project(project_path))
    data = await asyncio.to_thread(
        browser.browse,
        table=table,
        source_tier=source_tier,
        limit=limit,
        offset=offset,
    )
    return {"ok": True, "data": data}


@router.get("/{project_path:path}/imports")
async def list_imports(
    project_path: str,
    entity: str | None = None,
    source_tier: DataSourceTier | None = None,
) -> dict[str, Any]:
    """List import receipts filtered by entity and auditable source tier."""

    browser = NormalizedDataBrowser(resolve_project(project_path))
    receipts = await asyncio.to_thread(
        browser.list_imports,
        entity=entity,
        source_tier=source_tier,
    )
    return {"ok": True, "data": {"count": len(receipts), "receipts": receipts}}
