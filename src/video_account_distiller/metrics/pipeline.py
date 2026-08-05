"""Account-local derived metrics and robust performance scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.metrics.calculations import (
    median,
    performance_band,
    robust_z_scores,
    safe_divide,
)
from video_account_distiller.models import DerivedMetrics, MetricSnapshot, Video
from video_account_distiller.storage.parquet import read_models, write_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id


@dataclass
class WorkingMetric:
    snapshot: MetricSnapshot
    video: Video
    values: dict[str, float | None]
    zscores: dict[str, float | None]
    score: float | None = None


def _latest_snapshots(snapshots: list[MetricSnapshot]) -> list[MetricSnapshot]:
    latest: dict[str, MetricSnapshot] = {}
    for snapshot in snapshots:
        current = latest.get(snapshot.video_id)
        if current is None or (snapshot.snapshot_at, snapshot.record_id) > (
            current.snapshot_at,
            current.record_id,
        ):
            latest[snapshot.video_id] = snapshot
    return [latest[key] for key in sorted(latest)]


def _all_known(values: list[int | None]) -> int | None:
    if any(value is None for value in values):
        return None
    total = 0
    for value in values:
        assert value is not None
        total += value
    return total


def _base_values(snapshot: MetricSnapshot, video: Video) -> dict[str, float | None]:
    interactions = _all_known([snapshot.likes, snapshot.comments, snapshot.shares, snapshot.saves])
    return {
        "views": float(snapshot.views) if snapshot.views is not None else None,
        "like_rate": safe_divide(snapshot.likes, snapshot.views),
        "comment_rate": safe_divide(snapshot.comments, snapshot.views),
        "share_rate": safe_divide(snapshot.shares, snapshot.views),
        "save_rate": safe_divide(snapshot.saves, snapshot.views),
        "engagement_rate_by_view": safe_divide(interactions, snapshot.views),
        "engagement_rate_by_follower": safe_divide(interactions, video.follower_count_at_publish),
        "follow_conversion": safe_divide(snapshot.follows_gained, snapshot.views),
        "profile_conversion": safe_divide(snapshot.profile_visits, snapshot.views),
        "watch_efficiency": safe_divide(snapshot.avg_watch_time_seconds, video.duration_seconds),
        # Absolute interaction volumes. These stay observable when the platform
        # does not expose view counts and act as the heat proxy for scoring.
        "likes_abs": float(snapshot.likes) if snapshot.likes is not None else None,
        "comments_abs": float(snapshot.comments) if snapshot.comments is not None else None,
        "shares_abs": float(snapshot.shares) if snapshot.shares is not None else None,
        "saves_abs": float(snapshot.saves) if snapshot.saves is not None else None,
        "interactions_abs": float(interactions) if interactions is not None else None,
    }


ZSCORE_FIELDS = (
    "views",
    "like_rate",
    "comment_rate",
    "share_rate",
    "save_rate",
    "follow_conversion",
    "watch_efficiency",
    "likes_abs",
    "comments_abs",
    "shares_abs",
    "saves_abs",
    "interactions_abs",
)


class MetricsService:
    """Calculate latest-snapshot metrics within one account baseline."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def calculate(self, *, account_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Calculate null-safe derived metrics and write one Parquet table."""

        videos = read_models(self.project.normalized_dir / "videos.parquet", Video)
        snapshots = read_models(
            self.project.normalized_dir / "metric_snapshots.parquet", MetricSnapshot
        )
        account_videos = {
            video.video_id: video for video in videos if video.account_id == account_id
        }
        if not account_videos:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No normalized videos found for account: {account_id}",
            )
        selected = _latest_snapshots(
            [snapshot for snapshot in snapshots if snapshot.video_id in account_videos]
        )
        if not selected:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No metric snapshots found for account: {account_id}",
            )

        working = [
            WorkingMetric(
                snapshot=snapshot,
                video=account_videos[snapshot.video_id],
                values=_base_values(snapshot, account_videos[snapshot.video_id]),
                zscores={},
            )
            for snapshot in selected
        ]
        config = load_config(self.project.config_path)
        for field in ZSCORE_FIELDS:
            scores = robust_z_scores(
                [row.values[field] for row in working],
                log_transform=config.analysis.log_transform_metrics,
            )
            for row, score in zip(working, scores, strict=True):
                row.zscores[field] = score

        weights = config.analysis.performance_weights
        for row in working:
            weighted_total = 0.0
            weight_sum = 0.0
            for field in ZSCORE_FIELDS:
                score = row.zscores.get(field)
                weight = weights.get(field, 0.0)
                if score is None or weight <= 0:
                    continue
                weighted_total += weight * score
                weight_sum += weight
            row.score = weighted_total / weight_sum if weight_sum > 0 else None

        known_scores = [float(row.score) for row in working if row.score is not None]
        known_views = [
            float(row.values["views"]) for row in working if row.values["views"] is not None
        ]
        median_views = median(known_views)
        run_id = stable_id("run_dry_", account_id, *[row.snapshot.raw_hash for row in working])
        manifest = None
        if not dry_run:
            manifest = self.project.begin_run(
                "metrics",
                input_hashes=sorted({row.snapshot.raw_hash for row in working}),
            )
            run_id = manifest.run_id

        derived: list[DerivedMetrics] = []
        for row in working:
            snapshot = row.snapshot
            record_id = stable_id("dm_", snapshot.metric_snapshot_id, "0.1.0")
            view_value = row.values["views"]
            viral_index = safe_divide(view_value, median_views)
            outliers = [
                field
                for field, value in row.zscores.items()
                if value is not None and abs(value) >= 3.5
            ]
            derived.append(
                DerivedMetrics(
                    record_id=record_id,
                    source_platform=snapshot.source_platform,
                    source_type="derived_metrics",
                    source_uri=snapshot.source_uri,
                    source_record_id=snapshot.metric_snapshot_id,
                    collected_at=snapshot.snapshot_at,
                    run_id=run_id,
                    raw_hash=sha256_json(
                        {
                            "metric_snapshot": snapshot.model_dump(mode="json"),
                            "video": row.video.model_dump(mode="json"),
                        }
                    ),
                    data_quality_flags=snapshot.data_quality_flags,
                    video_id=snapshot.video_id,
                    snapshot_at=snapshot.snapshot_at,
                    like_rate_by_view=row.values["like_rate"],
                    comment_rate_by_view=row.values["comment_rate"],
                    share_rate_by_view=row.values["share_rate"],
                    save_rate_by_view=row.values["save_rate"],
                    engagement_rate_by_view=row.values["engagement_rate_by_view"],
                    engagement_rate_by_follower=row.values["engagement_rate_by_follower"],
                    follow_conversion_rate=row.values["follow_conversion"],
                    profile_conversion_rate=row.values["profile_conversion"],
                    completion_efficiency=row.values["watch_efficiency"],
                    robust_z_views=row.zscores["views"],
                    robust_z_like_rate=row.zscores["like_rate"],
                    robust_z_comment_rate=row.zscores["comment_rate"],
                    robust_z_share_rate=row.zscores["share_rate"],
                    robust_z_save_rate=row.zscores["save_rate"],
                    robust_z_follow_conversion=row.zscores["follow_conversion"],
                    robust_z_watch_efficiency=row.zscores["watch_efficiency"],
                    robust_z_likes_abs=row.zscores["likes_abs"],
                    robust_z_comments_abs=row.zscores["comments_abs"],
                    robust_z_shares_abs=row.zscores["shares_abs"],
                    robust_z_saves_abs=row.zscores["saves_abs"],
                    robust_z_interactions_abs=row.zscores["interactions_abs"],
                    viral_index_account=viral_index,
                    viral_index_peer=None,
                    performance_score=row.score,
                    performance_band=performance_band(row.score, known_scores),
                    outlier_flags=outliers,
                )
            )

        result = {
            "ok": True,
            "dry_run": dry_run,
            "run_id": run_id,
            "account_id": account_id,
            "records": len(derived),
            "bands": {
                band: sum(record.performance_band == band for record in derived)
                for band in ("S", "A", "B", "C", "D")
            },
        }
        if dry_run:
            return result

        output_path = self.project.normalized_dir / "derived_metrics.parquet"
        existing: list[DerivedMetrics] = read_models(output_path, DerivedMetrics)
        other_accounts_video_ids = {
            video.video_id for video in videos if video.account_id != account_id
        }
        merged: list[DerivedMetrics] = [
            record for record in existing if record.video_id in other_accounts_video_ids
        ]
        merged.extend(derived)
        merged.sort(key=lambda record: record.record_id)
        write_models(output_path, merged)
        state = self.project.load_state()
        state.last_metrics_at = datetime.now(UTC)
        self.project.save_state(state)
        assert manifest is not None
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={"derived_metrics": len(derived)},
            output_files=[self.project.relative(output_path)],
        )
        result["output"] = self.project.relative(output_path)
        return result
