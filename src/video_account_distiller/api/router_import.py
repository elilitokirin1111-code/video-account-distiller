"""Data import and normalization endpoints."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, UploadFile

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.ingestion import ImportService
from video_account_distiller.metrics import MetricsService
from video_account_distiller.models import Platform
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.transcripts import TranscriptImportService

router = APIRouter()


def _save_upload(file: UploadFile) -> Path:
    """Persist an uploaded file to a temp location."""
    suffix = Path(file.filename or "upload").suffix or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(file.file.read())
    finally:
        tmp.close()
    return Path(tmp.name)


@router.post("/{project_path:path}/import/accounts")
async def import_accounts(
    project_path: str,
    file: UploadFile,
    platform: Platform,
    mapping: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import account data from an uploaded CSV/JSON file."""
    layout = resolve_project(project_path)
    source = _save_upload(file)
    try:
        receipt, report, already = await asyncio.to_thread(
            ImportService(layout).import_file,
            entity="accounts",
            source=source,
            platform=platform,
            mapping_path=Path(mapping) if mapping else None,
            dry_run=dry_run,
        )
        return {
            "ok": True,
            "data": {
                "receipt": receipt.model_dump(mode="json") if receipt else None,
                "report": report.model_dump(mode="json"),
                "already_imported": already,
                "dry_run": dry_run,
            },
        }
    finally:
        source.unlink(missing_ok=True)


@router.post("/{project_path:path}/import/videos")
async def import_videos(
    project_path: str,
    file: UploadFile,
    platform: Platform,
    mapping: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import video data from an uploaded CSV/JSON file."""
    layout = resolve_project(project_path)
    source = _save_upload(file)
    try:
        receipt, report, already = await asyncio.to_thread(
            ImportService(layout).import_file,
            entity="videos",
            source=source,
            platform=platform,
            mapping_path=Path(mapping) if mapping else None,
            dry_run=dry_run,
        )
        return {
            "ok": True,
            "data": {
                "receipt": receipt.model_dump(mode="json") if receipt else None,
                "report": report.model_dump(mode="json"),
                "already_imported": already,
                "dry_run": dry_run,
            },
        }
    finally:
        source.unlink(missing_ok=True)


@router.post("/{project_path:path}/import/metrics")
async def import_metrics(
    project_path: str,
    file: UploadFile,
    platform: Platform,
    mapping: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import metric snapshot data from an uploaded CSV/JSON file."""
    layout = resolve_project(project_path)
    source = _save_upload(file)
    try:
        receipt, report, already = await asyncio.to_thread(
            ImportService(layout).import_file,
            entity="metrics",
            source=source,
            platform=platform,
            mapping_path=Path(mapping) if mapping else None,
            dry_run=dry_run,
        )
        return {
            "ok": True,
            "data": {
                "receipt": receipt.model_dump(mode="json") if receipt else None,
                "report": report.model_dump(mode="json"),
                "already_imported": already,
                "dry_run": dry_run,
            },
        }
    finally:
        source.unlink(missing_ok=True)


@router.post("/{project_path:path}/import/comments")
async def import_comments(
    project_path: str,
    file: UploadFile,
    platform: Platform,
    mapping: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import comment data from an uploaded CSV/JSON file."""
    layout = resolve_project(project_path)
    source = _save_upload(file)
    try:
        receipt, report, already = await asyncio.to_thread(
            ImportService(layout).import_file,
            entity="comments",
            source=source,
            platform=platform,
            mapping_path=Path(mapping) if mapping else None,
            dry_run=dry_run,
        )
        return {
            "ok": True,
            "data": {
                "receipt": receipt.model_dump(mode="json") if receipt else None,
                "report": report.model_dump(mode="json"),
                "already_imported": already,
                "dry_run": dry_run,
            },
        }
    finally:
        source.unlink(missing_ok=True)


@router.post("/{project_path:path}/import/transcripts")
async def import_transcripts(
    project_path: str,
    file: UploadFile,
    video_id: str,
    language: str | None = None,
    source_name: str = "user_subtitle",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import subtitle data (SRT/VTT/TXT/JSON) for a specific video."""
    layout = resolve_project(project_path)
    source = _save_upload(file)
    try:
        receipt, report, already = await asyncio.to_thread(
            TranscriptImportService(layout).import_file,
            video_id=video_id,
            source=source,
            language=language,
            source_name=source_name,
            dry_run=dry_run,
        )
        return {
            "ok": True,
            "data": {
                "receipt": receipt.model_dump(mode="json") if receipt else None,
                "report": report.model_dump(mode="json"),
                "already_imported": already,
                "dry_run": dry_run,
            },
        }
    finally:
        source.unlink(missing_ok=True)


@router.post("/{project_path:path}/normalize")
async def normalize(project_path: str, dry_run: bool = False) -> dict[str, Any]:
    """Run the normalization pipeline over all imported data."""
    layout = resolve_project(project_path)
    result = await asyncio.to_thread(NormalizationService(layout).normalize, dry_run=dry_run)
    return result


@router.post("/{project_path:path}/metrics/{account_id}")
async def calculate_metrics(
    project_path: str, account_id: str, dry_run: bool = False
) -> dict[str, Any]:
    """Calculate derived metrics and performance bands for an account."""
    layout = resolve_project(project_path)
    result = await asyncio.to_thread(
        MetricsService(layout).calculate, account_id=account_id, dry_run=dry_run
    )
    return result
