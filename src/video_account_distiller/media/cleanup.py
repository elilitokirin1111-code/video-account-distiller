"""Safe post-analysis cleanup of retained downloaded video blobs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import MediaAnalysis
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json

MEDIA_CLEANUP_SCHEMA_VERSION = "1.0.0"


def _prior_cleanup_entries(project: ProjectLayout, account_id: str) -> set[tuple[str, str]]:
    entries: set[tuple[str, str]] = set()
    root = project.root / "analyses" / "accounts" / account_id / "media-cleanups"
    for path in root.glob("*.json") if root.is_dir() else ():
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        for item in payload.get("entries", []) if isinstance(payload, dict) else ():
            if not isinstance(item, dict):
                continue
            raw_path = item.get("raw_media_path")
            media_hash = item.get("media_hash")
            if isinstance(raw_path, str) and isinstance(media_hash, str):
                entries.add((raw_path, media_hash))
    return entries


class DownloadedMediaCleanupService:
    """Delete only verified raw video copies after durable analysis has completed."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def cleanup_account(
        self,
        *,
        account_id: str,
        media_analysis_paths: Sequence[str] = (),
        reason: str = "post_distillation_storage_cleanup",
    ) -> dict[str, Any]:
        analysis_root = (self.project.root / "analyses" / "media").resolve()
        raw_media_root = (self.project.root / "raw" / "media").resolve()
        if media_analysis_paths:
            candidates = [self.project.root / path for path in media_analysis_paths]
        else:
            candidates = list(analysis_root.glob("*/*/media-analysis.json"))

        analyses: list[MediaAnalysis] = []
        skipped: list[dict[str, str]] = []
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError as exc:
                skipped.append({"path": str(candidate), "reason": type(exc).__name__})
                continue
            if not resolved.is_relative_to(analysis_root) or resolved.name != "media-analysis.json":
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    "Media cleanup target escapes the media analysis directory",
                    details={"path": str(candidate)},
                )
            try:
                analysis = MediaAnalysis.model_validate(read_json(resolved))
            except (OSError, ValueError, ValidationError) as exc:
                skipped.append(
                    {"path": self.project.relative(resolved), "reason": type(exc).__name__}
                )
                continue
            if analysis.account_id == account_id:
                analyses.append(analysis)

        targets: dict[tuple[str, str], Path] = {}
        for analysis in analyses:
            raw_path = (self.project.root / analysis.raw_media_path).resolve()
            if not raw_path.is_relative_to(raw_media_root):
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    "Media cleanup target escapes raw/media",
                    details={"path": analysis.raw_media_path},
                )
            targets[(analysis.raw_media_path, analysis.metadata.media_hash)] = raw_path

        prior_entries = _prior_cleanup_entries(self.project, account_id)
        deleted: list[dict[str, Any]] = []
        already_deleted: list[str] = []
        failures: list[dict[str, str]] = []
        deleted_bytes = 0
        deleted_at = datetime.now(UTC)
        for (relative_path, expected_hash), target in sorted(targets.items()):
            if not target.is_file():
                if (relative_path, expected_hash) in prior_entries:
                    already_deleted.append(relative_path)
                else:
                    failures.append({"path": relative_path, "reason": "raw_media_missing"})
                continue
            actual_hash = sha256_file(target)
            if actual_hash != expected_hash:
                failures.append({"path": relative_path, "reason": "media_hash_mismatch"})
                continue
            size_bytes = target.stat().st_size
            try:
                target.unlink()
            except OSError as exc:
                failures.append({"path": relative_path, "reason": type(exc).__name__})
                continue
            deleted_bytes += size_bytes
            deleted.append(
                {
                    "raw_media_path": relative_path,
                    "media_hash": expected_hash,
                    "size_bytes": size_bytes,
                    "deleted_at": deleted_at.isoformat(),
                }
            )

        outputs: list[str] = []
        if deleted:
            cleanup_id = stable_id(
                "mcl_",
                account_id,
                sha256_json(
                    [
                        {"path": item["raw_media_path"], "hash": item["media_hash"]}
                        for item in deleted
                    ]
                ),
            )
            cleanup_path = (
                self.project.root
                / "analyses"
                / "accounts"
                / account_id
                / "media-cleanups"
                / f"{cleanup_id}.json"
            )
            atomic_write_json(
                cleanup_path,
                {
                    "schema_version": MEDIA_CLEANUP_SCHEMA_VERSION,
                    "cleanup_id": cleanup_id,
                    "account_id": account_id,
                    "generated_at": deleted_at.isoformat(),
                    "reason": reason,
                    "entries": deleted,
                },
            )
            outputs.append(self.project.relative(cleanup_path))

        return {
            "ok": not failures,
            "account_id": account_id,
            "policy": "delete_verified_raw_video_after_success",
            "deleted_count": len(deleted),
            "deleted_bytes": deleted_bytes,
            "already_deleted_count": len(already_deleted),
            "failed_count": len(failures),
            "failures": failures,
            "skipped": skipped,
            "preserved": [
                "transcripts",
                "keyframes",
                "visual_semantics",
                "audio_features",
                "video_analyses",
                "distillation_and_reports",
            ],
            "outputs": outputs,
        }
