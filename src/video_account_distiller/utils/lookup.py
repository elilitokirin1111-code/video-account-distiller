"""Deterministic normalized-record lookup helpers."""

from __future__ import annotations

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import Video
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout


def resolve_video(project: ProjectLayout, identifier: str) -> Video:
    """Resolve an internal or unique platform video ID."""

    videos = read_models(project.normalized_dir / "videos.parquet", Video)
    internal = next((item for item in videos if item.video_id == identifier), None)
    if internal is not None:
        return internal
    matches = [item for item in videos if item.platform_video_id == identifier]
    if not matches:
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            f"Normalized video not found: {identifier}",
            details={"next": "import videos and run normalize first"},
        )
    if len(matches) > 1:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            f"Platform video ID is ambiguous: {identifier}",
            details={"matching_video_ids": sorted(item.video_id for item in matches)},
        )
    return matches[0]
