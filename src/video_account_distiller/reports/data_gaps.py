"""Machine-readable account data-gap and provenance table generation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from video_account_distiller.models import (
    AccountDataGapTable,
    AudienceProfileSegment,
    DataAvailability,
    DataEvidenceRef,
    DataGapItem,
    DataSourceTier,
)
from video_account_distiller.models.core import TraceFields
from video_account_distiller.sampling.dataset import AccountDataset
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout

FieldSpec = tuple[str, str, str, str, DataSourceTier]

FIELD_SPECS: tuple[FieldSpec, ...] = (
    (
        "account.follower_count_current",
        "当前粉丝数",
        "account",
        "follower_count_current",
        DataSourceTier.PUBLIC,
    ),
    ("metric.views", "播放量", "metric", "views", DataSourceTier.PUBLIC),
    ("metric.likes", "点赞量", "metric", "likes", DataSourceTier.PUBLIC),
    ("metric.comments", "评论量", "metric", "comments", DataSourceTier.PUBLIC),
    ("metric.shares", "分享量", "metric", "shares", DataSourceTier.PUBLIC),
    ("metric.saves", "收藏量", "metric", "saves", DataSourceTier.PUBLIC),
    ("metric.impressions", "展现量", "metric", "impressions", DataSourceTier.AUTHORIZED_PRIVATE),
    (
        "metric.avg_watch_time_seconds",
        "平均观看时长",
        "metric",
        "avg_watch_time_seconds",
        DataSourceTier.AUTHORIZED_PRIVATE,
    ),
    (
        "metric.completion_rate",
        "完播率",
        "metric",
        "completion_rate",
        DataSourceTier.AUTHORIZED_PRIVATE,
    ),
    (
        "metric.profile_visits",
        "主页访问",
        "metric",
        "profile_visits",
        DataSourceTier.AUTHORIZED_PRIVATE,
    ),
    (
        "metric.follows_gained",
        "涨粉",
        "metric",
        "follows_gained",
        DataSourceTier.AUTHORIZED_PRIVATE,
    ),
    ("metric.clicks", "点击", "metric", "clicks", DataSourceTier.AUTHORIZED_PRIVATE),
    ("metric.leads", "线索", "metric", "leads", DataSourceTier.AUTHORIZED_PRIVATE),
    ("metric.orders", "订单", "metric", "orders", DataSourceTier.AUTHORIZED_PRIVATE),
    ("metric.revenue", "收入", "metric", "revenue", DataSourceTier.AUTHORIZED_PRIVATE),
    (
        "audience.profile_segments",
        "粉丝画像",
        "audience",
        "profile_segment_id",
        DataSourceTier.AUTHORIZED_PRIVATE,
    ),
    (
        "derived.engagement_rate_by_view",
        "播放互动率",
        "derived",
        "engagement_rate_by_view",
        DataSourceTier.MODEL_INFERRED,
    ),
    (
        "derived.completion_efficiency",
        "完播效率",
        "derived",
        "completion_efficiency",
        DataSourceTier.MODEL_INFERRED,
    ),
    (
        "derived.performance_score",
        "表现评分",
        "derived",
        "performance_score",
        DataSourceTier.MODEL_INFERRED,
    ),
)


def _evidence_ref(table: str, record: TraceFields) -> DataEvidenceRef:
    return DataEvidenceRef(
        table=table,
        record_id=record.record_id,
        source_record_id=record.source_record_id,
        raw_hash=record.raw_hash,
        run_id=record.run_id,
        source_uri=record.source_uri,
    )


def _source_tiers_by_hash(project: ProjectLayout) -> dict[str, set[DataSourceTier]]:
    tiers: dict[str, set[DataSourceTier]] = {}
    for receipt in project.load_state().imports:
        tiers.setdefault(receipt.raw_hash, set()).add(DataSourceTier(receipt.data_source_tier))
    return tiers


def _records_for(
    dataset: AccountDataset,
    audience: list[AudienceProfileSegment],
    group: str,
) -> tuple[str, list[TraceFields], int]:
    if group == "account":
        return "accounts", [dataset.account], 1
    if group == "metric":
        return (
            "metric_snapshots",
            [record.metric for record in dataset.records if record.metric is not None],
            len(dataset.records),
        )
    if group == "derived":
        return (
            "derived_metrics",
            [record.derived for record in dataset.records if record.derived is not None],
            len(dataset.records),
        )
    return "audience_profiles", list(audience), 1


def build_account_data_gap_table(
    project: ProjectLayout,
    dataset: AccountDataset,
    *,
    report_id: str,
    generated_at: datetime,
) -> AccountDataGapTable:
    """Build a fixed-field table where absent observations stay explicitly unknown."""

    audience_path = project.normalized_dir / "audience_profiles.parquet"
    audience = (
        [
            record
            for record in read_models(audience_path, AudienceProfileSegment)
            if record.account_id == dataset.account.account_id
        ]
        if audience_path.is_file()
        else []
    )
    receipt_tiers = _source_tiers_by_hash(project)
    rows: list[DataGapItem] = []
    for field, label, group, attribute, intended_tier in FIELD_SPECS:
        table, records, total_records = _records_for(dataset, audience, group)
        available = [record for record in records if getattr(record, attribute, None) is not None]
        observed: set[DataSourceTier] = set()
        if available and intended_tier == DataSourceTier.MODEL_INFERRED:
            observed.add(DataSourceTier.MODEL_INFERRED)
        else:
            for record in available:
                observed.update(receipt_tiers.get(record.raw_hash, {DataSourceTier.UNKNOWN}))
        rows.append(
            DataGapItem(
                field=field,
                label=label,
                source_tier=intended_tier,
                availability=(
                    DataAvailability.AVAILABLE if available else DataAvailability.UNKNOWN
                ),
                available_records=len(available),
                total_records=total_records,
                observed_source_tiers=sorted(observed, key=lambda tier: tier.value),
                evidence_refs=[_evidence_ref(table, record) for record in available],
            )
        )
    return AccountDataGapTable(
        report_id=report_id,
        account_id=dataset.account.account_id,
        generated_at=generated_at,
        rows=rows,
    )


def data_gap_summary(table: AccountDataGapTable) -> dict[str, Any]:
    """Return compact counts for API responses and run manifests."""

    return {
        "fields": len(table.rows),
        "available": sum(row.availability == DataAvailability.AVAILABLE for row in table.rows),
        "unknown": sum(row.availability == DataAvailability.UNKNOWN for row in table.rows),
    }
