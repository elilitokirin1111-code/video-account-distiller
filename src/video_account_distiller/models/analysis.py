"""Phase 2 sampling, statistics, report, and evidence contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from video_account_distiller.models.core import StrictModel
from video_account_distiller.version import ANALYSIS_SCHEMA_VERSION

PerformanceBand = Literal["S", "A", "B", "C", "D"]
PerformanceCohort = Literal["high", "middle", "low", "unknown"]
EvidenceClassification = Literal[
    "fact",
    "semantic_annotation",
    "statistical_association",
    "hypothesis",
    "warning",
]


class EvidenceSource(StrictModel):
    """One normalized record supporting an evidence item."""

    table: Literal[
        "accounts",
        "videos",
        "metric_snapshots",
        "derived_metrics",
        "transcripts",
        "comments",
        "media_features",
    ]
    record_id: str
    source_record_id: str
    raw_hash: str
    run_id: str


class EvidenceItem(StrictModel):
    """Machine-readable provenance for a statistic, selection, or warning."""

    evidence_id: str
    label: str
    classification: EvidenceClassification
    value: Any
    calculation: str
    sources: list[EvidenceSource] = Field(default_factory=list)


class EvidenceIndex(StrictModel):
    """Complete evidence collection for one account-health report."""

    schema_version: str = ANALYSIS_SCHEMA_VERSION
    report_id: str
    account_id: str
    run_id: str
    generated_at: datetime
    input_hashes: list[str]
    items: list[EvidenceItem]


class ScalarStatistic(StrictModel):
    """A scalar report value linked to evidence."""

    value: str | int | float | bool | None
    unit: str | None = None
    evidence_id: str


class NumericSummary(StrictModel):
    """Null-aware five-number summary linked to evidence."""

    count: int
    missing_count: int
    minimum: float | None = None
    p25: float | None = None
    median: float | None = None
    p75: float | None = None
    maximum: float | None = None
    evidence_id: str


class DistributionSummary(StrictModel):
    """Categorical counts linked to evidence."""

    counts: dict[str, int]
    evidence_id: str


class SamplingCoverage(StrictModel):
    """Population or selected counts across deterministic strata."""

    performance: dict[str, int]
    recency: dict[str, int]
    content_pillar: dict[str, int]
    duration: dict[str, int]
    special: dict[str, int]


class SampleItem(StrictModel):
    """One selected video and the explicit reasons for its inclusion."""

    video_id: str
    source_video_id: str
    published_at: datetime | None = None
    performance_band: PerformanceBand | None = None
    performance_score: float | None = None
    content_pillar: str
    duration_bucket: str
    is_promoted: bool
    is_outlier: bool
    selection_reasons: list[str]
    evidence_id: str


class SampleManifest(StrictModel):
    """Content-addressed deterministic Phase 2 sample manifest."""

    schema_version: str = ANALYSIS_SCHEMA_VERSION
    sample_manifest_id: str
    account_id: str
    strategy: Literal["stratified"] = "stratified"
    strategy_version: str = "1.0.0"
    population_size: int
    requested_size: int
    target_size: int
    selected_size: int
    generated_at: datetime
    run_id: str
    input_hashes: list[str]
    recent_cutoff: datetime | None = None
    population_coverage: SamplingCoverage
    selected_coverage: SamplingCoverage
    selected: list[SampleItem]
    warnings: list[str] = Field(default_factory=list)


class AccountStatistics(StrictModel):
    """Deterministic account-level statistics used by the health report."""

    account_id: str
    video_count: ScalarStatistic
    period_start: ScalarStatistic
    period_end: ScalarStatistic
    follower_count_current: ScalarStatistic
    publishing_frequency_weekly: ScalarStatistic
    publication_gap_days: NumericSummary
    duration_seconds: NumericSummary
    performance_score: NumericSummary
    views: NumericSummary
    engagement_rate_by_view: NumericSummary
    completion_efficiency: NumericSummary
    high_performance_rate: ScalarStatistic
    longest_low_streak: ScalarStatistic
    promoted_video_count: ScalarStatistic
    outlier_video_count: ScalarStatistic
    performance_bands: DistributionSummary
    content_pillars: DistributionSummary
    data_quality_flags: DistributionSummary


class CohortStatistics(StrictModel):
    """Statistics for one high/middle/low performance cohort."""

    cohort: PerformanceCohort
    bands: list[PerformanceBand]
    video_count: int
    video_ids: list[str]
    metrics: dict[str, NumericSummary]
    evidence_id: str


class PerformanceComparison(StrictModel):
    """Account-local high, middle, and low cohort comparison."""

    high: CohortStatistics
    middle: CohortStatistics
    low: CohortStatistics


class ReportFinding(StrictModel):
    """One deterministic finding with evidence references."""

    finding_id: str
    title: str
    statement: str
    classification: EvidenceClassification
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str]


class ReportDataScope(StrictModel):
    """Data range and provenance envelope for a report."""

    platform: str
    population_size: int
    metric_video_count: int
    period_start: datetime | None = None
    period_end: datetime | None = None
    input_hashes: list[str]
    evidence_ids: dict[str, str]


class AccountHealthReport(StrictModel):
    """Phase 2 account-health report; facts and associations only."""

    schema_version: str = ANALYSIS_SCHEMA_VERSION
    report_id: str
    report_type: Literal["account_health"] = "account_health"
    report_version: str = "1.0.0"
    account_id: str
    generated_at: datetime
    run_id: str
    data_scope: ReportDataScope
    statistics: AccountStatistics
    comparison: PerformanceComparison
    sample_manifest_id: str
    sample_manifest_path: str
    evidence_index_path: str
    warnings_path: str
    findings: list[ReportFinding]
    warnings: list[str] = Field(default_factory=list)
