"""Validated account-level analytical dataset loading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import Account, DerivedMetrics, MetricSnapshot, Video
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout

ModelT = TypeVar("ModelT", MetricSnapshot, DerivedMetrics)


@dataclass(frozen=True)
class AccountVideoRecord:
    """One video joined to its latest metric and derived records."""

    video: Video
    metric: MetricSnapshot | None
    derived: DerivedMetrics | None


@dataclass(frozen=True)
class AccountDataset:
    """Account and normalized analytical records with source hashes."""

    account: Account
    records: list[AccountVideoRecord]
    input_hashes: list[str]


def _latest_by_video(records: list[ModelT]) -> dict[str, ModelT]:
    latest: dict[str, ModelT] = {}
    for record in records:
        current = latest.get(record.video_id)
        if current is None or (record.snapshot_at, record.record_id) > (
            current.snapshot_at,
            current.record_id,
        ):
            latest[record.video_id] = record
    return latest


def load_account_dataset(project: ProjectLayout, account_id: str) -> AccountDataset:
    """Load normalized records for one account without reading raw exports."""

    accounts = read_models(project.normalized_dir / "accounts.parquet", Account)
    candidates = [account for account in accounts if account.account_id == account_id]
    if not candidates:
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            f"No normalized account found: {account_id}",
        )
    account = max(candidates, key=lambda item: (item.snapshot_at, item.record_id))
    videos = sorted(
        (
            video
            for video in read_models(project.normalized_dir / "videos.parquet", Video)
            if video.account_id == account_id
        ),
        key=lambda item: item.video_id,
    )
    if not videos:
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            f"No normalized videos found for account: {account_id}",
        )

    video_ids = {video.video_id for video in videos}
    metrics = _latest_by_video(
        [
            record
            for record in read_models(
                project.normalized_dir / "metric_snapshots.parquet", MetricSnapshot
            )
            if record.video_id in video_ids
        ]
    )
    derived = _latest_by_video(
        [
            record
            for record in read_models(
                project.normalized_dir / "derived_metrics.parquet", DerivedMetrics
            )
            if record.video_id in video_ids
        ]
    )
    records = [
        AccountVideoRecord(
            video=video,
            metric=metrics.get(video.video_id),
            derived=derived.get(video.video_id),
        )
        for video in videos
    ]
    input_hashes = {account.raw_hash}
    input_hashes.update(video.raw_hash for video in videos)
    input_hashes.update(record.raw_hash for record in metrics.values())
    input_hashes.update(record.raw_hash for record in derived.values())
    return AccountDataset(
        account=account,
        records=records,
        input_hashes=sorted(input_hashes),
    )
