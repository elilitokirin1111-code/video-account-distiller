"""Integrity validation for immutable account collection batches."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from video_account_distiller.models import AccountCollectionBatch, ProviderDriftReport
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.io import read_json


def validate_collection_batches(
    project: ProjectLayout,
    batch_paths: list[Path],
) -> list[tuple[Path, str]]:
    """Validate batch hashes, canonical companions, and optional drift reports."""

    errors: list[tuple[Path, str]] = []
    for path in batch_paths:
        try:
            payload = read_json(path)
            batch = AccountCollectionBatch.model_validate(payload)
            if sha256_json(payload) != path.parent.name:
                raise ValueError("content hash does not match account collection directory")
            if batch.provider.value != path.parent.parent.name:
                raise ValueError("collection provider does not match directory")
            companions = {
                "accounts.json": [batch.account.model_dump(mode="json")],
                "videos.json": [item.model_dump(mode="json") for item in batch.videos],
                "metrics.json": [item.model_dump(mode="json") for item in batch.metrics],
            }
            comments_companion = path.parent / "comments.json"
            if batch.comments or comments_companion.is_file():
                companions["comments.json"] = [
                    item.model_dump(mode="json") for item in batch.comments
                ]
            for filename, expected in companions.items():
                companion = path.parent / filename
                if not companion.is_file() or sha256_json(read_json(companion)) != sha256_json(
                    expected
                ):
                    raise ValueError(f"collection companion mismatch: {filename}")

            drift_path = path.parent / "drift-report.json"
            if drift_path.is_file():
                drift = ProviderDriftReport.model_validate(read_json(drift_path))
                if drift.provider != batch.provider:
                    raise ValueError("drift report provider does not match collection batch")
                if drift.ok != (drift.status != "fail"):
                    raise ValueError("drift report ok/status values are inconsistent")
        except (OSError, ValueError, ValidationError) as exc:
            errors.append((path, str(exc)))
    return errors
