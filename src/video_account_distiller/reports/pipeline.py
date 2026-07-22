"""Account-health report generation with full evidence traceability."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from jinja2 import Environment, StrictUndefined

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    AccountHealthReport,
    AccountStatistics,
    CohortStatistics,
    DistributionSummary,
    EvidenceIndex,
    EvidenceItem,
    EvidenceSource,
    NumericSummary,
    PerformanceComparison,
    ReportDataScope,
    ReportFinding,
    SampleManifest,
    ScalarStatistic,
)
from video_account_distiller.reports.statistics import (
    longest_low_streak,
    publication_frequency_weekly,
    publication_gaps_days,
    summarize_numeric,
)
from video_account_distiller.sampling import SamplingService
from video_account_distiller.sampling.dataset import (
    AccountDataset,
    AccountVideoRecord,
    load_account_dataset,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json
from video_account_distiller.version import ANALYSIS_SCHEMA_VERSION

REPORT_VERSION = "1.0.0"
MetricName = Literal[
    "views",
    "engagement_rate_by_view",
    "completion_efficiency",
    "duration_seconds",
    "performance_score",
]
EvidenceTable = Literal["accounts", "videos", "metric_snapshots", "derived_metrics"]
COHORT_METRICS: tuple[MetricName, ...] = (
    "views",
    "engagement_rate_by_view",
    "completion_efficiency",
    "duration_seconds",
    "performance_score",
)


def _sources(
    rows: list[tuple[str, Any]],
) -> list[EvidenceSource]:
    sources: dict[tuple[str, str], EvidenceSource] = {}
    for table, row in rows:
        source = EvidenceSource(
            table=cast(EvidenceTable, table),
            record_id=row.record_id,
            source_record_id=row.source_record_id,
            raw_hash=row.raw_hash,
            run_id=row.run_id,
        )
        sources[(table, row.record_id)] = source
    return [sources[key] for key in sorted(sources)]


def _record_sources(record: AccountVideoRecord) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = [("videos", record.video)]
    if record.metric is not None:
        rows.append(("metric_snapshots", record.metric))
    if record.derived is not None:
        rows.append(("derived_metrics", record.derived))
    return rows


def _metric_value(record: AccountVideoRecord, name: MetricName) -> float | None:
    if name == "duration_seconds":
        return record.video.duration_seconds
    if name == "views":
        return (
            float(record.metric.views)
            if record.metric and record.metric.views is not None
            else None
        )
    if record.derived is None:
        return None
    value = getattr(record.derived, name)
    return float(value) if value is not None else None


def _performance_band(record: AccountVideoRecord) -> str:
    return (
        record.derived.performance_band
        if record.derived is not None and record.derived.performance_band is not None
        else "unknown"
    )


def _content_pillar(record: AccountVideoRecord) -> str:
    value = record.video.content_type
    return value.strip() if value and value.strip() else "unknown"


def _is_promoted(record: AccountVideoRecord) -> bool:
    return bool(
        record.video.is_ad
        or (record.metric is not None and record.metric.is_promoted)
        or (
            record.metric is not None
            and record.metric.promotion_spend is not None
            and record.metric.promotion_spend > 0
        )
    )


def _is_outlier(record: AccountVideoRecord) -> bool:
    return bool(record.derived is not None and record.derived.outlier_flags)


class EvidenceCollector:
    """Create stable evidence IDs while preventing duplicate entries."""

    def __init__(self, report_id: str) -> None:
        self.report_id = report_id
        self.items: dict[str, EvidenceItem] = {}

    def add(
        self,
        *,
        label: str,
        classification: Literal["fact", "statistical_association", "warning"],
        value: Any,
        calculation: str,
        rows: list[tuple[str, Any]],
        evidence_id: str | None = None,
    ) -> str:
        """Add one evidence item and return its stable identifier."""

        identifier = evidence_id or stable_id("evi_", self.report_id, label)
        self.items[identifier] = EvidenceItem(
            evidence_id=identifier,
            label=label,
            classification=classification,
            value=value,
            calculation=calculation,
            sources=_sources(rows),
        )
        return identifier


def _numeric_with_evidence(
    collector: EvidenceCollector,
    *,
    label: str,
    records: list[AccountVideoRecord],
    metric: MetricName,
) -> NumericSummary:
    values = [_metric_value(record, metric) for record in records]
    evidence_id = collector.add(
        label=label,
        classification="fact",
        value=values,
        calculation=f"null-aware five-number summary of {metric}",
        rows=[row for record in records for row in _record_sources(record)],
    )
    return summarize_numeric(values, evidence_id=evidence_id)


def _cohort(
    collector: EvidenceCollector,
    *,
    name: Literal["high", "middle", "low"],
    bands: list[Literal["S", "A", "B", "C", "D"]],
    records: list[AccountVideoRecord],
) -> CohortStatistics:
    selected = [record for record in records if _performance_band(record) in bands]
    evidence_id = collector.add(
        label=f"cohort.{name}.membership",
        classification="fact",
        value=[record.video.video_id for record in selected],
        calculation=f"performance_band in {bands}",
        rows=[row for record in selected for row in _record_sources(record)],
    )
    metrics: dict[str, NumericSummary] = {
        str(metric): _numeric_with_evidence(
            collector,
            label=f"cohort.{name}.{metric}",
            records=selected,
            metric=metric,
        )
        for metric in COHORT_METRICS
    }
    return CohortStatistics(
        cohort=name,
        bands=bands,
        video_count=len(selected),
        video_ids=[record.video.video_id for record in selected],
        metrics=metrics,
        evidence_id=evidence_id,
    )


def _build_statistics(
    dataset: AccountDataset,
    collector: EvidenceCollector,
) -> tuple[AccountStatistics, PerformanceComparison]:
    records = dataset.records
    all_video_rows = [("videos", record.video) for record in records]
    dated = [record.video.published_at for record in records if record.video.published_at]

    video_count_evidence = collector.add(
        label="account.video_count",
        classification="fact",
        value=len(records),
        calculation="count(normalized videos for account)",
        rows=all_video_rows,
    )
    period_start_evidence = collector.add(
        label="account.period_start",
        classification="fact",
        value=min(dated).isoformat() if dated else None,
        calculation="minimum known published_at",
        rows=all_video_rows,
    )
    period_end_evidence = collector.add(
        label="account.period_end",
        classification="fact",
        value=max(dated).isoformat() if dated else None,
        calculation="maximum known published_at",
        rows=all_video_rows,
    )
    follower_evidence = collector.add(
        label="account.follower_count_current",
        classification="fact",
        value=dataset.account.follower_count_current,
        calculation="latest normalized account snapshot value; not follower_count_at_publish",
        rows=[("accounts", dataset.account)],
    )
    frequency = publication_frequency_weekly([record.video.published_at for record in records])
    frequency_evidence = collector.add(
        label="account.publishing_frequency_weekly",
        classification="fact",
        value=frequency,
        calculation="known video count / observed publication span in weeks",
        rows=all_video_rows,
    )
    gaps = publication_gaps_days([record.video.published_at for record in records])
    gap_evidence = collector.add(
        label="account.publication_gap_days",
        classification="fact",
        value=gaps,
        calculation="chronological differences between known published_at values",
        rows=all_video_rows,
    )

    known_bands = [
        _performance_band(record) for record in records if _performance_band(record) != "unknown"
    ]
    high_rate = (
        sum(band in {"S", "A"} for band in known_bands) / len(known_bands) if known_bands else None
    )
    high_rate_evidence = collector.add(
        label="account.high_performance_rate",
        classification="fact",
        value=high_rate,
        calculation="count(S or A) / count(known performance bands)",
        rows=[row for record in records for row in _record_sources(record)],
    )
    low_streak = longest_low_streak(
        [(record.video.published_at, _performance_band(record)) for record in records]
    )
    low_streak_evidence = collector.add(
        label="account.longest_low_streak",
        classification="fact",
        value=low_streak,
        calculation="maximum chronological consecutive run of C/D bands",
        rows=[row for record in records for row in _record_sources(record)],
    )
    promoted_count = sum(_is_promoted(record) for record in records)
    promoted_evidence = collector.add(
        label="account.promoted_video_count",
        classification="fact",
        value=promoted_count,
        calculation="count(is_ad or is_promoted or promotion_spend > 0)",
        rows=[row for record in records for row in _record_sources(record)],
    )
    outlier_count = sum(_is_outlier(record) for record in records)
    outlier_evidence = collector.add(
        label="account.outlier_video_count",
        classification="fact",
        value=outlier_count,
        calculation="count(non-empty derived_metrics.outlier_flags)",
        rows=[row for record in records for row in _record_sources(record)],
    )
    band_counts = dict(sorted(Counter(_performance_band(record) for record in records).items()))
    bands_evidence = collector.add(
        label="account.performance_bands",
        classification="fact",
        value=band_counts,
        calculation="count videos by account-local performance_band",
        rows=[row for record in records for row in _record_sources(record)],
    )
    pillar_counts = dict(sorted(Counter(_content_pillar(record) for record in records).items()))
    pillars_evidence = collector.add(
        label="account.content_pillars",
        classification="fact",
        value=pillar_counts,
        calculation="count videos by content_type used as the Phase 2 pillar proxy",
        rows=all_video_rows,
    )
    quality_counts = Counter(
        flag.value
        for record in records
        for model in (record.video, record.metric, record.derived)
        if model is not None
        for flag in model.data_quality_flags
    )
    quality_evidence = collector.add(
        label="account.data_quality_flags",
        classification="warning" if quality_counts else "fact",
        value=dict(sorted(quality_counts.items())),
        calculation="count normalized data_quality_flags across joined account records",
        rows=[row for record in records for row in _record_sources(record)],
    )

    statistics = AccountStatistics(
        account_id=dataset.account.account_id,
        video_count=ScalarStatistic(
            value=len(records), unit="videos", evidence_id=video_count_evidence
        ),
        period_start=ScalarStatistic(
            value=min(dated).isoformat() if dated else None,
            unit="datetime",
            evidence_id=period_start_evidence,
        ),
        period_end=ScalarStatistic(
            value=max(dated).isoformat() if dated else None,
            unit="datetime",
            evidence_id=period_end_evidence,
        ),
        follower_count_current=ScalarStatistic(
            value=dataset.account.follower_count_current,
            unit="followers",
            evidence_id=follower_evidence,
        ),
        publishing_frequency_weekly=ScalarStatistic(
            value=frequency,
            unit="videos_per_week",
            evidence_id=frequency_evidence,
        ),
        publication_gap_days=summarize_numeric(gaps, evidence_id=gap_evidence),
        duration_seconds=_numeric_with_evidence(
            collector, label="account.duration_seconds", records=records, metric="duration_seconds"
        ),
        performance_score=_numeric_with_evidence(
            collector,
            label="account.performance_score",
            records=records,
            metric="performance_score",
        ),
        views=_numeric_with_evidence(
            collector, label="account.views", records=records, metric="views"
        ),
        engagement_rate_by_view=_numeric_with_evidence(
            collector,
            label="account.engagement_rate_by_view",
            records=records,
            metric="engagement_rate_by_view",
        ),
        completion_efficiency=_numeric_with_evidence(
            collector,
            label="account.completion_efficiency",
            records=records,
            metric="completion_efficiency",
        ),
        high_performance_rate=ScalarStatistic(
            value=high_rate,
            unit="ratio",
            evidence_id=high_rate_evidence,
        ),
        longest_low_streak=ScalarStatistic(
            value=low_streak,
            unit="videos",
            evidence_id=low_streak_evidence,
        ),
        promoted_video_count=ScalarStatistic(
            value=promoted_count,
            unit="videos",
            evidence_id=promoted_evidence,
        ),
        outlier_video_count=ScalarStatistic(
            value=outlier_count,
            unit="videos",
            evidence_id=outlier_evidence,
        ),
        performance_bands=DistributionSummary(
            counts=band_counts,
            evidence_id=bands_evidence,
        ),
        content_pillars=DistributionSummary(
            counts=pillar_counts,
            evidence_id=pillars_evidence,
        ),
        data_quality_flags=DistributionSummary(
            counts=dict(sorted(quality_counts.items())),
            evidence_id=quality_evidence,
        ),
    )
    comparison = PerformanceComparison(
        high=_cohort(collector, name="high", bands=["S", "A"], records=records),
        middle=_cohort(collector, name="middle", bands=["B"], records=records),
        low=_cohort(collector, name="low", bands=["C", "D"], records=records),
    )
    return statistics, comparison


def _report_warnings(dataset: AccountDataset, sample: SampleManifest) -> list[str]:
    warnings = list(sample.warnings)
    if len(dataset.records) < 30:
        warnings.append("结论仅为描述性观察：视频样本少于 30 条。")
    if any(record.metric is None for record in dataset.records):
        warnings.append("部分视频缺少指标快照，相关汇总保留为 null。")
    if any(record.derived is None for record in dataset.records):
        warnings.append("部分视频尚未计算 DerivedMetrics，表现对照覆盖不完整。")
    if any(_is_promoted(record) for record in dataset.records):
        warnings.append("数据包含广告或投流视频，不应将其表现直接解释为内容规律。")
    if any(_is_outlier(record) for record in dataset.records):
        warnings.append("数据包含 Robust Z-score 异常样本，报告保留但单独标记。")
    warnings.extend(
        [
            "Phase 2 使用 content_type 作为内容支柱代理；语义内容支柱将在 Phase 3 标注。",
            "高、中、低表现差异是统计关联，不代表因果关系或爆款保证。",
            "当前报告仅使用单账号、单平台内部基线，不比较跨平台原始指标。",
        ]
    )
    return list(dict.fromkeys(warnings))


def _findings(
    *,
    report_id: str,
    statistics: AccountStatistics,
    comparison: PerformanceComparison,
    warnings_evidence_id: str,
) -> list[ReportFinding]:
    period_start = statistics.period_start.value or "未知"
    period_end = statistics.period_end.value or "未知"
    findings = [
        ReportFinding(
            finding_id=stable_id("find_", report_id, "scope"),
            title="数据范围",
            statement=(
                f"本报告覆盖 {statistics.video_count.value} 条视频，观察期为 "
                f"{period_start} 至 {period_end}。"
            ),
            classification="fact",
            confidence="high",
            evidence_ids=[
                statistics.video_count.evidence_id,
                statistics.period_start.evidence_id,
                statistics.period_end.evidence_id,
            ],
        )
    ]
    if statistics.views.median is not None:
        engagement_median = statistics.engagement_rate_by_view.median
        engagement_text = engagement_median if engagement_median is not None else "未知"
        findings.append(
            ReportFinding(
                finding_id=stable_id("find_", report_id, "baseline"),
                title="账号内基线",
                statement=(
                    f"最新指标快照的播放中位数为 {statistics.views.median:.2f}，"
                    f"互动率中位数为 {engagement_text}。"
                ),
                classification="fact",
                confidence="high",
                evidence_ids=[
                    statistics.views.evidence_id,
                    statistics.engagement_rate_by_view.evidence_id,
                ],
            )
        )
    high_views = comparison.high.metrics["views"].median
    low_views = comparison.low.metrics["views"].median
    if high_views is not None and low_views is not None:
        comparison_confidence: Literal["low", "medium", "high"] = (
            "medium"
            if comparison.high.video_count >= 5 and comparison.low.video_count >= 5
            else "low"
        )
        findings.append(
            ReportFinding(
                finding_id=stable_id("find_", report_id, "cohort-views"),
                title="高中低表现对照",
                statement=(
                    f"高表现组播放中位数为 {high_views:.2f}，低表现组为 {low_views:.2f}；"
                    "该差异只描述账号内关联。"
                ),
                classification="statistical_association",
                confidence=comparison_confidence,
                evidence_ids=[
                    comparison.high.metrics["views"].evidence_id,
                    comparison.low.metrics["views"].evidence_id,
                ],
            )
        )
    high_rate = statistics.high_performance_rate.value
    high_rate_text = high_rate if high_rate is not None else "未知"
    findings.append(
        ReportFinding(
            finding_id=stable_id("find_", report_id, "stability"),
            title="表现稳定性",
            statement=(
                f"高表现命中率为 {high_rate_text}，"
                f"最长连续低表现为 {statistics.longest_low_streak.value} 条。"
            ),
            classification="fact",
            confidence="high",
            evidence_ids=[
                statistics.high_performance_rate.evidence_id,
                statistics.longest_low_streak.evidence_id,
            ],
        )
    )
    findings.append(
        ReportFinding(
            finding_id=stable_id("find_", report_id, "limitations"),
            title="解释边界",
            statement="报告保留投流、异常值、缺失字段和小样本警告，不从表现结果反推内容因果。",
            classification="warning",
            confidence="high",
            evidence_ids=[warnings_evidence_id],
        )
    )
    return findings


def _render_markdown(report: AccountHealthReport, evidence: EvidenceIndex) -> str:
    template_path = Path(__file__).parent / "templates" / "account-health.md.j2"
    try:
        environment = Environment(undefined=StrictUndefined, autoescape=False)
        template = environment.from_string(template_path.read_text(encoding="utf-8"))
        return (
            template.render(
                report=report.model_dump(mode="json"),
                evidence_count=len(evidence.items),
            ).rstrip()
            + "\n"
        )
    except Exception as exc:
        raise DistillerError(
            ErrorCode.REPORT_GENERATION,
            "Failed to render account-health report",
            details={"reason": str(exc)},
        ) from exc


class ReportService:
    """Generate content-addressed JSON/Markdown reports and evidence files."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def generate_account_health(
        self,
        *,
        account_id: str,
        sample_size: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Generate or reuse a traceable deterministic account-health report."""

        dataset = load_account_dataset(self.project, account_id)
        sample_result = SamplingService(self.project).select(
            account_id=account_id,
            size=sample_size,
            dry_run=dry_run,
        )
        sample = SampleManifest.model_validate(sample_result["manifest"])
        report_id = stable_id(
            "rpt_",
            account_id,
            REPORT_VERSION,
            sample.sample_manifest_id,
            dataset.input_hashes,
        )
        relative_dir = Path("reports") / "accounts" / account_id / report_id
        output_dir = self.project.root / relative_dir
        report_json_path = output_dir / "report.json"
        report_markdown_path = output_dir / "report.md"
        evidence_path = output_dir / "evidence-index.json"
        warnings_path = output_dir / "warnings.json"
        if report_json_path.is_file() and not dry_run:
            existing = AccountHealthReport.model_validate(read_json(report_json_path))
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "report": existing.model_dump(mode="json"),
                "outputs": [
                    self.project.relative(report_json_path),
                    self.project.relative(report_markdown_path),
                    self.project.relative(evidence_path),
                    self.project.relative(warnings_path),
                ],
            }

        now = datetime.now(UTC)
        run_id = stable_id("run_dry_", report_id)
        run = None
        if not dry_run:
            run = self.project.begin_run("report account-health", input_hashes=dataset.input_hashes)
            run_id = run.run_id
        collector = EvidenceCollector(report_id)
        statistics, comparison = _build_statistics(dataset, collector)
        for item in sample.selected:
            source_record = next(
                record for record in dataset.records if record.video.video_id == item.video_id
            )
            collector.add(
                label=f"sample.{item.video_id}",
                classification="fact",
                value=item.selection_reasons,
                calculation="deterministic stratified selection reasons",
                rows=_record_sources(source_record),
                evidence_id=item.evidence_id,
            )
        warnings = _report_warnings(dataset, sample)
        warnings_evidence_id = collector.add(
            label="report.warnings",
            classification="warning",
            value=warnings,
            calculation=(
                "deterministic checks for sample size, missingness, promotion, outliers, and scope"
            ),
            rows=[row for record in dataset.records for row in _record_sources(record)],
        )
        dated = [
            record.video.published_at for record in dataset.records if record.video.published_at
        ]
        metric_video_count = sum(record.metric is not None for record in dataset.records)
        platform_evidence_id = collector.add(
            label="scope.platform",
            classification="fact",
            value=dataset.account.platform.value,
            calculation="normalized account platform",
            rows=[("accounts", dataset.account)],
        )
        metric_count_evidence_id = collector.add(
            label="scope.metric_video_count",
            classification="fact",
            value=metric_video_count,
            calculation="count videos joined to a latest metric snapshot",
            rows=[
                ("metric_snapshots", record.metric)
                for record in dataset.records
                if record.metric is not None
            ],
        )
        report = AccountHealthReport(
            report_id=report_id,
            account_id=account_id,
            generated_at=now,
            run_id=run_id,
            data_scope=ReportDataScope(
                platform=dataset.account.platform.value,
                population_size=len(dataset.records),
                metric_video_count=metric_video_count,
                period_start=min(dated) if dated else None,
                period_end=max(dated) if dated else None,
                input_hashes=dataset.input_hashes,
                evidence_ids={
                    "platform": platform_evidence_id,
                    "population_size": statistics.video_count.evidence_id,
                    "metric_video_count": metric_count_evidence_id,
                    "period_start": statistics.period_start.evidence_id,
                    "period_end": statistics.period_end.evidence_id,
                },
            ),
            statistics=statistics,
            comparison=comparison,
            sample_manifest_id=sample.sample_manifest_id,
            sample_manifest_path=str(sample_result["output"]),
            evidence_index_path=self.project.relative(evidence_path),
            warnings_path=self.project.relative(warnings_path),
            findings=_findings(
                report_id=report_id,
                statistics=statistics,
                comparison=comparison,
                warnings_evidence_id=warnings_evidence_id,
            ),
            warnings=warnings,
        )
        evidence = EvidenceIndex(
            report_id=report_id,
            account_id=account_id,
            run_id=run_id,
            generated_at=now,
            input_hashes=dataset.input_hashes,
            items=[collector.items[key] for key in sorted(collector.items)],
        )
        markdown = _render_markdown(report, evidence)
        outputs = [
            self.project.relative(report_json_path),
            self.project.relative(report_markdown_path),
            self.project.relative(evidence_path),
            self.project.relative(warnings_path),
        ]
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "already_generated": False,
                "report": report.model_dump(mode="json"),
                "outputs": outputs,
            }

        atomic_write_json(report_json_path, report.model_dump(mode="json"))
        atomic_write_text(report_markdown_path, markdown)
        atomic_write_json(evidence_path, evidence.model_dump(mode="json"))
        atomic_write_json(
            warnings_path,
            {
                "schema_version": ANALYSIS_SCHEMA_VERSION,
                "report_id": report_id,
                "run_id": run_id,
                "warnings": warnings,
            },
        )
        state = self.project.load_state()
        state.last_report_at = now
        self.project.save_state(state)
        assert run is not None
        self.project.finish_run(
            run,
            success=True,
            processed_counts={
                "population_videos": len(dataset.records),
                "sample_videos": sample.selected_size,
                "evidence_items": len(evidence.items),
            },
            output_files=outputs,
            warnings=warnings,
        )
        return {
            "ok": True,
            "dry_run": False,
            "already_generated": False,
            "report": report.model_dump(mode="json"),
            "outputs": outputs,
        }
