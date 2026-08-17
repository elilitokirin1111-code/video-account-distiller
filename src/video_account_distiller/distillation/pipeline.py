"""Deterministic account patterns, counterexamples, and transfer review."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from jinja2 import Environment, StrictUndefined

from video_account_distiller.benchmarking import (
    AccountBenchmarkProfileService,
    rank_account_profiles,
)
from video_account_distiller.config import load_config
from video_account_distiller.distillation.craft import (
    CRAFT_CATEGORIES,
    CRAFT_CATEGORY_LABELS,
    build_craft_profile,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.metrics.calculations import median
from video_account_distiller.models import (
    AccountBenchmarkProfile,
    AccountDistillation,
    AccountPositioning,
    ArtifactEvidenceIndex,
    BenchmarkComparison,
    CommentAnalysis,
    ContentCluster,
    CraftProfile,
    EvidenceItem,
    EvidenceSource,
    MediaAnalysis,
    MediaFeatureRecord,
    Pattern,
    PatternScope,
    SingleVideoAnalysis,
    TransferMatrixItem,
)
from video_account_distiller.sampling.dataset import (
    AccountDataset,
    AccountVideoRecord,
    load_account_dataset,
)
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json

DISTILLATION_VERSION = "1.4.0"
COMPARISON_VERSION = "1.1.0"
Classification = Literal[
    "fact", "semantic_annotation", "statistical_association", "hypothesis", "warning"
]
UNKNOWN_LABELS = frozenset({"", "unknown", "unclassified", "未知", "未识别", "未识别需求"})


def _is_unknown_label(value: object) -> bool:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().casefold() in UNKNOWN_LABELS


def _media_features(
    project: ProjectLayout,
    video_ids: set[str],
) -> list[MediaFeatureRecord]:
    grouped: dict[str, tuple[MediaFeatureRecord, datetime]] = {}
    for item in read_models(
        project.normalized_dir / "media_features.parquet",
        MediaFeatureRecord,
    ):
        if item.video_id not in video_ids:
            continue
        generated_at = datetime.min.replace(tzinfo=UTC)
        analysis_path = project.root / item.analysis_path
        if analysis_path.is_file():
            try:
                generated_at = MediaAnalysis.model_validate(read_json(analysis_path)).generated_at
            except (OSError, ValueError):
                pass
        previous = grouped.get(item.video_id)
        if previous is None or (generated_at, item.analysis_id) > (
            previous[1],
            previous[0].analysis_id,
        ):
            grouped[item.video_id] = (item, generated_at)
    return [grouped[key][0] for key in sorted(grouped)]


def _production_signals(features: Sequence[MediaFeatureRecord]) -> list[str]:
    """Summarize only directly measured framing, edit rhythm, and audio activity."""

    if not features:
        return []
    signals: list[str] = []
    vertical = sum(
        item.width is not None and item.height is not None and item.height > item.width
        for item in features
    )
    measured_orientation = sum(
        item.width is not None and item.height is not None for item in features
    )
    if measured_orientation:
        if vertical == measured_orientation:
            signals.append(f"竖屏画幅（{vertical}/{measured_orientation} 条实测）")
        elif vertical:
            signals.append(f"以竖屏为主（{vertical}/{measured_orientation} 条实测）")
    shot_durations = [
        item.average_shot_duration_ms
        for item in features
        if item.average_shot_duration_ms is not None
    ]
    typical_shot = median(shot_durations)
    if typical_shot is not None:
        pace = (
            "快节奏剪辑"
            if typical_shot < 1_500
            else "中等镜头节奏"
            if typical_shot <= 3_500
            else "偏长镜头表达"
        )
        signals.append(f"{pace}（镜头时长中位数 {typical_shot / 1000:.1f} 秒）")
    silence_values = [item.silence_ratio for item in features if item.silence_ratio is not None]
    typical_silence = median(silence_values)
    if typical_silence is not None:
        audio = (
            "音频持续活跃"
            if typical_silence <= 0.2
            else "音频活跃度中等"
            if typical_silence < 0.5
            else "音频留白较多"
        )
        signals.append(f"{audio}（静音占比中位数 {typical_silence:.0%}）")
    visual_count = sum(item.visual_annotation_count for item in features)
    if visual_count:
        signals.append(f"已有 {visual_count} 个带证据的视觉镜头标注")
    visual_labels = Counter(value for item in features for value in item.visual_labels)
    if visual_labels:
        signals.append(
            "高频画面元素：" + "、".join(value for value, _ in visual_labels.most_common(5))
        )
    colors = Counter(value for item in features for value in item.dominant_colors)
    if colors:
        signals.append("常见画面主色：" + "、".join(value for value, _ in colors.most_common(4)))
    # 拍摄手法与表现形式（景别/运镜/机位/构图/光线/字幕/动效/品牌/开场/节奏）由
    # CraftProfile 按类别与覆盖率结构化输出，避免在这里重复合并标签。
    return signals


def _source(table: str, row: Any) -> EvidenceSource:
    return EvidenceSource(
        table=cast(Any, table),
        record_id=row.record_id,
        source_record_id=row.source_record_id,
        raw_hash=row.raw_hash,
        run_id=row.run_id,
    )


def _record_sources(record: AccountVideoRecord) -> list[EvidenceSource]:
    sources = [_source("videos", record.video)]
    if record.metric is not None:
        sources.append(_source("metric_snapshots", record.metric))
    if record.derived is not None:
        sources.append(_source("derived_metrics", record.derived))
    return sources


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


def _band(record: AccountVideoRecord) -> str:
    if record.derived is None or record.derived.performance_band is None:
        return "unknown"
    return record.derived.performance_band


def _score(record: AccountVideoRecord) -> float | None:
    if record.derived is None:
        return None
    return record.derived.performance_score


@dataclass(frozen=True)
class _PatternPerformance:
    """Comparable account-local bands used only for association mining."""

    basis: Literal["performance_score", "public_interaction_proxy", "unavailable"]
    bands: dict[str, str]
    scores: dict[str, float]

    @property
    def target_metric(self) -> str:
        return (
            "performance_score" if self.basis == "performance_score" else "public_interaction_proxy"
        )

    def band(self, record: AccountVideoRecord) -> str:
        return self.bands.get(record.video.video_id, "unknown")

    def score(self, record: AccountVideoRecord) -> float | None:
        return self.scores.get(record.video.video_id)


def _public_interaction_total(record: AccountVideoRecord) -> int | None:
    """Return a transparent public-count proxy without pretending views are known."""

    if record.metric is None:
        return None
    direct = (record.metric.likes, record.metric.comments, record.metric.shares)
    saved = max(record.metric.saves or 0, record.metric.favorites or 0)
    if not any(
        value is not None for value in (*direct, record.metric.saves, record.metric.favorites)
    ):
        return None
    return sum(value or 0 for value in direct) + saved


def _resolve_pattern_performance(dataset: AccountDataset) -> _PatternPerformance:
    """Prefer real performance bands; otherwise rank transparent public interactions.

    The fallback is deliberately account-local and ordinal. It enables bounded
    pattern/counterexample mining when a public provider omits views, while the
    output remains explicitly labelled as a proxy rather than view efficiency.
    """

    actual_bands = {
        record.video.video_id: _band(record)
        for record in dataset.records
        if _band(record) != "unknown"
    }
    if len(actual_bands) == len(dataset.records):
        return _PatternPerformance(
            basis="performance_score",
            bands=actual_bands,
            scores={
                record.video.video_id: score
                for record in dataset.records
                if (score := _score(record)) is not None
            },
        )

    totals = {
        record.video.video_id: total
        for record in dataset.records
        if (total := _public_interaction_total(record)) is not None
    }
    if len(totals) < 5:
        return _PatternPerformance(basis="unavailable", bands={}, scores={})

    ordered_values = sorted(set(totals.values()))
    denominator = max(len(ordered_values) - 1, 1)
    rank_by_total = {total: index for index, total in enumerate(ordered_values)}
    percentiles = {
        video_id: rank_by_total[total] / denominator for video_id, total in totals.items()
    }
    bands = {
        video_id: (
            "A"
            if percentile >= 0.8
            else "B"
            if percentile >= 0.55
            else "C"
            if percentile >= 0.25
            else "D"
        )
        for video_id, percentile in percentiles.items()
    }
    return _PatternPerformance(
        basis="public_interaction_proxy",
        bands=bands,
        scores={
            video_id: round(percentile * 100, 3) for video_id, percentile in percentiles.items()
        },
    )


def _public_account_stage(dataset: AccountDataset) -> str:
    followers = dataset.account.follower_count_current or 0
    published = dataset.account.video_count_current or len(dataset.records)
    if followers >= 100_000 or published >= 100:
        return "公开规模代理：成熟账号"
    if followers >= 10_000 or published >= 30:
        return "公开规模代理：增长期账号"
    return "公开规模代理：起步期账号"


class _EvidenceCollector:
    def __init__(self, artifact_id: str) -> None:
        self.artifact_id = artifact_id
        self.items: dict[str, EvidenceItem] = {}

    def add(
        self,
        *,
        label: str,
        classification: Classification,
        value: Any,
        calculation: str,
        sources: list[EvidenceSource],
        evidence_id: str | None = None,
    ) -> str:
        identifier = evidence_id or stable_id("evi_", self.artifact_id, label)
        unique = {(item.table, item.record_id): item for item in sources}
        self.items[identifier] = EvidenceItem(
            evidence_id=identifier,
            label=label,
            classification=classification,
            value=value,
            calculation=calculation,
            sources=[unique[key] for key in sorted(unique)],
        )
        return identifier


def _latest_video_analyses(
    project: ProjectLayout, video_ids: set[str]
) -> dict[str, SingleVideoAnalysis]:
    selected: dict[str, SingleVideoAnalysis] = {}
    for path in sorted((project.root / "analyses" / "videos").glob("*/*/analysis.json")):
        value = SingleVideoAnalysis.model_validate(read_json(path))
        if value.video_id not in video_ids:
            continue
        current = selected.get(value.video_id)
        if current is None or (value.generated_at, value.analysis_id) > (
            current.generated_at,
            current.analysis_id,
        ):
            selected[value.video_id] = value
    return selected


def _latest_comment_analysis(
    project: ProjectLayout, account_id: str
) -> tuple[CommentAnalysis | None, ArtifactEvidenceIndex | None]:
    selected: tuple[CommentAnalysis, Path] | None = None
    for path in sorted(
        (project.root / "analyses" / "comments" / account_id).glob("*/analysis.json")
    ):
        value = CommentAnalysis.model_validate(read_json(path))
        if selected is None or (value.generated_at, value.analysis_id) > (
            selected[0].generated_at,
            selected[0].analysis_id,
        ):
            selected = (value, path)
    if selected is None:
        return None, None
    evidence = ArtifactEvidenceIndex.model_validate(
        read_json(project.root / selected[0].evidence_index_path)
    )
    return selected[0], evidence


def _build_clusters(
    dataset: AccountDataset,
    video_analyses: dict[str, SingleVideoAnalysis],
    collector: _EvidenceCollector,
    performance: _PatternPerformance,
) -> list[ContentCluster]:
    grouped: dict[tuple[str, str], list[AccountVideoRecord]] = defaultdict(list)
    for record in dataset.records:
        analysis = video_analyses.get(record.video.video_id)
        semantic_pillar = (
            analysis.blind_analysis.semantics.primary_pillar if analysis is not None else "unknown"
        )
        if not _is_unknown_label(semantic_pillar):
            grouped[("semantic_pillar", semantic_pillar)].append(record)
        else:
            proxy = (record.video.content_type or "unknown").strip() or "unknown"
            if not _is_unknown_label(proxy):
                grouped[("content_type_proxy", proxy)].append(record)

    clusters: list[ContentCluster] = []
    for (method, value), records in sorted(grouped.items()):
        video_ids = sorted(record.video.video_id for record in records)
        cluster_id = stable_id("clu_", dataset.account.account_id, method, value, *video_ids)
        band_counts = dict(sorted(Counter(performance.band(record) for record in records).items()))
        known_bands = [
            band for band in (performance.band(record) for record in records) if band != "unknown"
        ]
        known_scores = [
            score for record in records if (score := performance.score(record)) is not None
        ]
        evidence_id = collector.add(
            label=f"content_cluster.{cluster_id}",
            classification=("semantic_annotation" if method == "semantic_pillar" else "fact"),
            value={
                "feature_value": value,
                "method": method,
                "video_ids": video_ids,
                "performance_band_counts": band_counts,
                "performance_basis": performance.basis,
            },
            calculation=(
                (
                    "group by latest blind semantic pillar; performance bands use "
                    f"{performance.basis}"
                )
                if method == "semantic_pillar"
                else (
                    "group by normalized content_type proxy; performance bands use "
                    f"{performance.basis}"
                )
            ),
            sources=[source for record in records for source in _record_sources(record)],
        )
        clusters.append(
            ContentCluster(
                cluster_id=cluster_id,
                name=value,
                method=cast(Any, method),
                feature_value=value,
                video_ids=video_ids,
                video_count=len(records),
                performance_band_counts=band_counts,
                median_performance_score=(
                    median([float(item) for item in known_scores])
                    if performance.basis == "performance_score"
                    else None
                ),
                high_performance_rate=(
                    sum(item in {"S", "A"} for item in known_bands) / len(known_bands)
                    if known_bands
                    else None
                ),
                source_analysis_ids=sorted(
                    {
                        video_analyses[video_id].analysis_id
                        for video_id in video_ids
                        if video_id in video_analyses
                    }
                ),
                evidence_id=evidence_id,
            )
        )
    return clusters


def _pattern_from_records(
    *,
    dataset: AccountDataset,
    feature_type: Literal["topic", "hook", "cta", "posting_time", "comment_trigger", "craft"],
    feature_name: str,
    feature_value: str,
    records: list[AccountVideoRecord],
    source_evidence_ids: list[str],
    collector: _EvidenceCollector,
    min_support: int,
    generated_at: datetime,
    performance: _PatternPerformance,
    craft_category: str | None = None,
) -> Pattern | None:
    if len(records) < min_support:
        return None
    eligible = [
        record for record in records if not _is_promoted(record) and not _is_outlier(record)
    ]
    high = [record for record in eligible if performance.band(record) in {"S", "A"}]
    low = [record for record in eligible if performance.band(record) in {"C", "D"}]
    if not high and not low:
        return None
    failure = len(low) > len(high)
    support = low if failure else high
    counterexamples = high if failure else low
    if not support:
        return None
    confounded = [record for record in records if record not in eligible]
    source_ids = sorted(record.video.video_id for record in records)
    support_ids = sorted(record.video.video_id for record in support)
    counterexample_ids = sorted(record.video.video_id for record in counterexamples)
    direction = "低表现" if failure else "高表现"
    pattern_type = "failure" if failure else feature_type
    pattern_seed = {
        "account_id": dataset.account.account_id,
        "feature_type": feature_type,
        "feature_value": feature_value,
        "performance_basis": performance.basis,
        "support": support_ids,
        "counterexamples": counterexample_ids,
        "version": DISTILLATION_VERSION,
    }
    pattern_id = stable_id("pat_", sha256_json(pattern_seed))
    evidence_id = collector.add(
        label=f"pattern.{pattern_id}",
        classification="statistical_association",
        value={
            "feature": feature_value,
            "all_video_ids": source_ids,
            "support_video_ids": support_ids,
            "counterexample_video_ids": counterexample_ids,
            "excluded_confounder_video_ids": sorted(record.video.video_id for record in confounded),
        },
        calculation=(
            f"account-local S/A versus C/D comparison using {performance.basis}; "
            "promoted and robust outlier videos are excluded from support/counterexample counts"
        ),
        sources=[source for record in records for source in _record_sources(record)],
    )
    maturity: Literal[0, 1] = 1 if len(support) >= min_support and bool(counterexamples) else 0
    raw_confidence = len(support) / (len(support) + len(counterexamples) + 2)
    confidence = min(0.75, raw_confidence)
    if not counterexamples:
        confidence = min(confidence, 0.55)
    confounders = []
    if any(_is_promoted(record) for record in confounded):
        confounders.append("promoted_video_excluded")
    if any(_is_outlier(record) for record in confounded):
        confounders.append("robust_outlier_excluded")
    risks = ["association_not_causation"]
    if performance.basis == "public_interaction_proxy":
        risks.extend(
            [
                "views_unavailable_proxy_is_not_view_efficiency",
                "publication_age_not_normalized",
            ]
        )
    if not counterexamples:
        risks.append("no_observed_counterexample_in_current_sample")
    return Pattern(
        pattern_id=pattern_id,
        account_id=dataset.account.account_id,
        pattern_type=cast(Any, pattern_type),
        name=f"{feature_name}：{feature_value} 的{direction}关联",
        description=(
            f"在账号内可比样本中，特征“{feature_value}”有 {len(support)} 条{direction}支持样本，"
            f"并保留 {len(counterexamples)} 条反例。"
        ),
        feature_conditions={
            "feature_type": feature_type,
            "feature_value": feature_value,
            **({"craft_category": craft_category} if craft_category is not None else {}),
        },
        target_metrics=[performance.target_metric],
        support_video_ids=support_ids,
        counterexample_video_ids=counterexample_ids,
        support_count=len(support_ids),
        counterexample_count=len(counterexample_ids),
        effect_summary=(
            f"eligible={len(eligible)}; high={len(high)}; low={len(low)}; "
            f"account-local direction={direction}; basis={performance.basis}"
        ),
        confounders=confounders,
        scope=PatternScope(
            platforms=[dataset.account.platform.value],
            pillars=[feature_value] if feature_type == "topic" else [],
            account_stages=[_public_account_stage(dataset)],
        ),
        confidence=confidence,
        maturity_level=maturity,
        replicability=("high" if feature_type in {"topic", "hook", "cta", "craft"} else "medium"),
        risks=risks,
        evidence_ids=list(dict.fromkeys([*source_evidence_ids, evidence_id])),
        created_at=generated_at,
        last_validated_at=generated_at,
        version=DISTILLATION_VERSION,
    )


def _build_patterns(
    dataset: AccountDataset,
    clusters: list[ContentCluster],
    video_analyses: dict[str, SingleVideoAnalysis],
    comment_analysis: CommentAnalysis | None,
    collector: _EvidenceCollector,
    min_support: int,
    generated_at: datetime,
    performance: _PatternPerformance,
    craft_profile: CraftProfile | None = None,
) -> list[Pattern]:
    records_by_id = {record.video.video_id: record for record in dataset.records}
    groups: list[
        tuple[
            Literal["topic", "hook", "cta", "posting_time", "comment_trigger", "craft"],
            str,
            str,
            list[AccountVideoRecord],
            list[str],
            str | None,
        ]
    ] = []
    for cluster in clusters:
        if _is_unknown_label(cluster.feature_value):
            continue
        groups.append(
            (
                "topic",
                "内容簇",
                cluster.feature_value,
                [records_by_id[item] for item in cluster.video_ids],
                [cluster.evidence_id],
                None,
            )
        )
    hook_groups: dict[str, list[AccountVideoRecord]] = defaultdict(list)
    cta_groups: dict[str, list[AccountVideoRecord]] = defaultdict(list)
    for video_id, analysis in video_analyses.items():
        record = records_by_id.get(video_id)
        if record is None:
            continue
        hook = analysis.blind_analysis.semantics.hook.primary_type.value
        cta = analysis.blind_analysis.semantics.cta.primary_type.value
        if hook != "unknown":
            hook_groups[hook].append(record)
        if cta != "unknown":
            cta_groups["未设置明确行动引导" if cta == "none" else cta].append(record)
    for value, records in sorted(hook_groups.items()):
        groups.append(("hook", "Hook", value, records, [], None))
    for value, records in sorted(cta_groups.items()):
        groups.append(("cta", "CTA", value, records, [], None))
    time_groups: dict[str, list[AccountVideoRecord]] = defaultdict(list)
    for record in dataset.records:
        if record.video.published_at is None:
            continue
        hour = record.video.published_at.hour
        bucket = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        time_groups[bucket].append(record)
    for value, records in sorted(time_groups.items()):
        groups.append(("posting_time", "发布时间", value, records, [], None))
    if comment_analysis is not None:
        for comment_cluster in comment_analysis.need_clusters:
            if _is_unknown_label(comment_cluster.primary_intent):
                continue
            records = [
                records_by_id[item] for item in comment_cluster.video_ids if item in records_by_id
            ]
            groups.append(
                (
                    "comment_trigger",
                    "评论触发",
                    comment_cluster.primary_intent.value,
                    records,
                    [comment_cluster.evidence_id],
                    None,
                )
            )
    if craft_profile is not None:
        for category in CRAFT_CATEGORIES:
            for summary in craft_profile.categories.get(category, []):
                records = [
                    records_by_id[item] for item in summary.video_ids if item in records_by_id
                ]
                groups.append(
                    (
                        "craft",
                        CRAFT_CATEGORY_LABELS[category],
                        summary.tag,
                        records,
                        [],
                        category,
                    )
                )

    patterns = [
        pattern
        for feature_type, name, value, records, evidence_ids, craft_category in groups
        if (
            pattern := _pattern_from_records(
                dataset=dataset,
                feature_type=feature_type,
                feature_name=name,
                feature_value=value,
                records=records,
                source_evidence_ids=evidence_ids,
                collector=collector,
                min_support=min_support,
                generated_at=generated_at,
                performance=performance,
                craft_category=craft_category,
            )
        )
        is not None
    ]
    return sorted(patterns, key=lambda item: (item.pattern_type, item.name, item.pattern_id))


def _render(template_name: str, **context: Any) -> str:
    path = Path(__file__).resolve().parents[1] / "reports" / "templates" / template_name
    template = Environment(undefined=StrictUndefined, autoescape=False).from_string(
        path.read_text(encoding="utf-8")
    )
    return template.render(**context).strip() + "\n"


class AccountDistillationService:
    """Produce account patterns with support, counterexamples, and action planning."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def distill(self, *, account_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Distill one account from normalized data and existing Phase 3/4 artifacts."""

        dataset = load_account_dataset(self.project, account_id)
        video_ids = {record.video.video_id for record in dataset.records}
        video_analyses = _latest_video_analyses(self.project, video_ids)
        media_features = _media_features(self.project, video_ids)
        craft_profile = build_craft_profile(media_features)
        production_signals = _production_signals(media_features)
        identity_signals = list(
            dict.fromkeys([*production_signals, *craft_profile.signature_style])
        )
        comment_analysis, comment_evidence = _latest_comment_analysis(self.project, account_id)
        config = load_config(self.project.config_path)
        pattern_performance = _resolve_pattern_performance(dataset)
        public_account_stage = _public_account_stage(dataset)
        generated_at = datetime.now(UTC)
        seed = {
            "account_id": account_id,
            "version": DISTILLATION_VERSION,
            "input_hashes": dataset.input_hashes,
            "video_analyses": sorted(item.analysis_id for item in video_analyses.values()),
            "media_analyses": sorted(item.analysis_id for item in media_features),
            "craft_profile": craft_profile.model_dump(mode="json"),
            "comment_analysis": comment_analysis.analysis_id if comment_analysis else None,
            "min_pattern_support": config.analysis.min_pattern_support,
            "analysis_config": config.analysis.model_dump(mode="json"),
            "pattern_performance": {
                "basis": pattern_performance.basis,
                "bands": pattern_performance.bands,
                "scores": pattern_performance.scores,
            },
            "video_features": [
                {
                    "video_id": record.video.video_id,
                    "content_type": record.video.content_type,
                    "published_at": (
                        record.video.published_at.isoformat() if record.video.published_at else None
                    ),
                    "is_ad": record.video.is_ad,
                    "performance_score": _score(record),
                    "performance_band": _band(record),
                    "outlier": _is_outlier(record),
                }
                for record in dataset.records
            ],
        }
        distillation_id = stable_id("dst_", sha256_json(seed))
        output_dir = self.project.root / "reports" / "accounts" / account_id / distillation_id
        paths = [
            output_dir / "distillation.json",
            output_dir / "report.md",
            output_dir / "evidence-index.json",
            output_dir / "warnings.json",
        ]
        relative = [self.project.relative(path) for path in paths]
        if paths[0].is_file() and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "distillation": read_json(paths[0]),
                "outputs": relative,
            }
        input_hashes = sorted(
            {
                *dataset.input_hashes,
                *(comment_analysis.input_hashes if comment_analysis is not None else []),
                *(item.raw_hash for item in media_features),
            }
        )
        manifest = (
            None
            if dry_run
            else self.project.begin_run("distill account", input_hashes=input_hashes)
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", distillation_id)
        collector = _EvidenceCollector(distillation_id)
        account_evidence = collector.add(
            label="account.profile",
            classification="fact",
            value={
                "display_name": dataset.account.display_name,
                "bio": dataset.account.bio,
                "platform": dataset.account.platform.value,
            },
            calculation="latest normalized account record",
            sources=[_source("accounts", dataset.account)],
        )
        media_evidence: list[str] = []
        if media_features:
            media_evidence.append(
                collector.add(
                    label="account.production_signals",
                    classification="fact",
                    value={
                        "analyzed_media_count": len(media_features),
                        "signals": production_signals,
                    },
                    calculation=(
                        "measured media orientation plus medians of shot duration "
                        "and signal-level silence ratio"
                    ),
                    sources=[_source("media_features", item) for item in media_features],
                )
            )
            media_evidence.append(
                collector.add(
                    label="account.craft_profile",
                    classification="semantic_annotation",
                    value={
                        "analyzed_media_count": craft_profile.analyzed_media_count,
                        "annotated_media_count": craft_profile.annotated_media_count,
                        "categories": {
                            category: [item.tag for item in summaries]
                            for category, summaries in craft_profile.categories.items()
                        },
                        "signature_style": craft_profile.signature_style,
                    },
                    calculation=(
                        "deterministic aggregation of per-shot vision craft labels "
                        "and measured editing rhythm across videos"
                    ),
                    sources=[_source("media_features", item) for item in media_features],
                )
            )
        clusters = _build_clusters(dataset, video_analyses, collector, pattern_performance)
        if comment_evidence is not None:
            for item in comment_evidence.items:
                collector.items.setdefault(item.evidence_id, item)
        patterns = _build_patterns(
            dataset,
            clusters,
            video_analyses,
            comment_analysis,
            collector,
            config.analysis.min_pattern_support,
            generated_at,
            pattern_performance,
            craft_profile,
        )
        all_comment_clusters = comment_analysis.need_clusters if comment_analysis else []
        comment_clusters = [
            cluster
            for cluster in all_comment_clusters
            if not _is_unknown_label(cluster.primary_intent)
        ]
        persona_signals = sorted(
            {
                signal
                for analysis in video_analyses.values()
                for signal in analysis.blind_analysis.semantics.persona_signals
            }
        )
        ranked_focus = [
            cluster.name
            for cluster in sorted(clusters, key=lambda item: (-item.video_count, item.name))[:3]
        ]
        known_focus = [name for name in ranked_focus if name != "unknown"]
        focus = known_focus or ([] if ranked_focus == ["unknown"] else ranked_focus)
        need_names = [
            cluster.name
            for cluster in sorted(comment_clusters, key=lambda item: (-item.frequency, item.name))[
                :5
            ]
        ]
        positioning = AccountPositioning(
            statement=(
                (
                    f"在 {len(video_analyses)}/{len(dataset.records)} 条已完成语义分析的视频中，"
                    f"已观察到的内容方向包括：{'、'.join(focus)}；"
                    f"账号处于{public_account_stage.removeprefix('公开规模代理：')}。"
                )
                if focus and video_analyses
                else f"基于标准化内容类型代理，账号内容主要集中在：{'、'.join(focus)}。"
                if focus
                else "当前语义证据不足以形成可观察的内容定位。"
            ),
            observed_content_focus=focus,
            audience_need_clusters=need_names,
            persona_signals=persona_signals,
            visual_and_audio_identity=identity_signals,
            confidence=(
                "high"
                if len(dataset.records) >= 30 and len(video_analyses) >= 10
                else "medium"
                if len(dataset.records) >= 15
                else "low"
            ),
            evidence_ids=[
                account_evidence,
                *media_evidence,
                *(cluster.evidence_id for cluster in clusters[:5]),
                *(cluster.evidence_id for cluster in comment_clusters[:5]),
            ],
            unknowns=[
                *([] if persona_signals else ["缺少可核验的人设表达证据"]),
                *([] if production_signals else ["尚未完成可测量的画面与音频特征分析"]),
                *(
                    ["已有镜头节奏等测量，但尚无视觉模型语义标注"]
                    if production_signals
                    and not any(item.visual_annotation_count for item in media_features)
                    else []
                ),
                *craft_profile.unknowns,
                "公开内容未提供完整商业转化承接路径",
            ],
        )
        strengths = [pattern.name for pattern in patterns if pattern.pattern_type != "failure"][:5]
        weaknesses = [pattern.name for pattern in patterns if pattern.pattern_type == "failure"][:5]
        copyable = [
            pattern.name
            for pattern in patterns
            if pattern.pattern_type != "failure"
            and pattern.replicability in {"high", "medium"}
            and not pattern.confounders
        ][:5]
        noncopyable = [
            "投流和 Robust 异常样本不能作为内容效果模板",
            "未分析的视觉、声音、团队资源与外部事件不能直接迁移",
        ]
        actions = list(
            dict.fromkeys(
                opportunity
                for cluster in sorted(
                    comment_clusters, key=lambda item: (-item.frequency, item.name)
                )
                for opportunity in cluster.content_opportunities
            )
        )[:5]
        actions.extend(f"围绕“{name}”设计同支柱对照内容" for name in strengths[:3])
        if not actions:
            actions.append("补充评论和更多单视频语义分析后再确定选题优先级")
        experiments = [
            (
                f"在同一内容支柱内，对“{pattern.feature_conditions['feature_value']}”做 A/B 对照，"
                "目标指标使用账号内 performance_score；至少保留 1 个反例。"
            )
            for pattern in patterns[:3]
        ]
        warnings: list[str] = []
        if len(dataset.records) < 30:
            warnings.append("small_video_sample_no_strong_account_rule")
        if comment_analysis is None:
            warnings.append("comment_analysis_missing")
        else:
            warnings.extend(comment_analysis.warnings)
        if len(video_analyses) < min(10, len(dataset.records)):
            warnings.append("semantic_video_analysis_coverage_low")
        if any(
            _is_unknown_label(analysis.blind_analysis.semantics.primary_pillar)
            for analysis in video_analyses.values()
        ):
            warnings.append("semantic_unknown_values_excluded_from_strategy")
        if len(comment_clusters) != len(all_comment_clusters):
            warnings.append("comment_unknown_clusters_excluded_from_strategy")
        if len(media_features) < min(3, len(dataset.records)):
            warnings.append("media_analysis_coverage_low")
        if craft_profile.annotated_media_count < min(3, len(media_features)):
            warnings.append("craft_profile_vision_annotations_low")
        if craft_profile.analyzed_media_count and not any(
            summaries for summaries in craft_profile.categories.values()
        ):
            warnings.append("craft_profile_no_aggregatable_craft_tags")
        if not patterns:
            warnings.append("no_pattern_met_minimum_support")
        if pattern_performance.basis == "public_interaction_proxy":
            warnings.append("patterns_use_public_interaction_proxy_not_view_efficiency")
        elif pattern_performance.basis == "unavailable":
            warnings.append("pattern_performance_basis_unavailable")
        warnings.extend(
            [
                "patterns_are_observations_or_associations_not_causal_rules",
                "no_phase4_pattern_is_a_level4_validated_rule",
            ]
        )
        distillation = AccountDistillation(
            distillation_id=distillation_id,
            account_id=account_id,
            generated_at=generated_at,
            run_id=run_id,
            data_scope={
                "platform": dataset.account.platform.value,
                "video_count": len(dataset.records),
                "comment_count": comment_analysis.comment_count if comment_analysis else 0,
                "analyzed_video_count": len(video_analyses),
                "analyzed_media_count": len(media_features),
                "content_cluster_count": len(clusters),
                "pattern_count": len(patterns),
                "pattern_performance_basis": pattern_performance.basis,
                "pattern_performance_coverage": len(pattern_performance.bands),
                "public_account_stage": public_account_stage,
            },
            positioning=positioning,
            content_clusters=clusters,
            comment_need_clusters=comment_clusters,
            patterns=patterns,
            strengths=strengths,
            weaknesses=weaknesses,
            copyable_factors=copyable,
            noncopyable_factors=noncopyable,
            action_recommendations=list(dict.fromkeys(actions))[:8],
            experiment_plan=experiments,
            craft_profile=craft_profile,
            evidence_index_path=relative[2],
            warnings_path=relative[3],
            warnings=list(dict.fromkeys(warnings)),
        )
        evidence = ArtifactEvidenceIndex(
            artifact_id=distillation_id,
            account_ids=[account_id],
            run_id=run_id,
            generated_at=generated_at,
            input_hashes=input_hashes,
            items=[collector.items[key] for key in sorted(collector.items)],
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "distillation": distillation.model_dump(mode="json"),
            "outputs": relative,
        }
        if dry_run:
            return result
        assert manifest is not None
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(paths[0], distillation.model_dump(mode="json"))
        atomic_write_text(
            paths[1],
            _render(
                "account-distillation.md.j2",
                distillation=distillation.model_dump(mode="python"),
                craft_labels=CRAFT_CATEGORY_LABELS,
            ),
        )
        atomic_write_json(paths[2], evidence.model_dump(mode="json"))
        atomic_write_json(paths[3], distillation.warnings)
        pattern_dir = self.project.root / "knowledge-base" / "patterns"
        for pattern in patterns:
            pattern_path = pattern_dir / f"{pattern.pattern_id}.json"
            if not pattern_path.exists():
                atomic_write_json(pattern_path, pattern.model_dump(mode="json"))
        profile_path = self.project.root / "knowledge-base" / "accounts" / f"{account_id}.md"
        craft_lines = craft_profile.signature_style or ["unknown"]
        atomic_write_text(
            profile_path,
            "\n".join(
                [
                    f"# Account profile: {account_id}",
                    "",
                    positioning.statement,
                    "",
                    f"Latest distillation: `{relative[0]}`",
                    f"Observed focus: {', '.join(focus) or 'unknown'}",
                    f"Audience needs: {', '.join(need_names) or 'unknown'}",
                    f"Public account stage: {public_account_stage}",
                    f"Craft signature: {'；'.join(craft_lines)}",
                    "",
                ]
            ),
        )
        index_path = self.project.root / "knowledge-base" / "index.json"
        index = read_json(index_path) if index_path.is_file() else {"accounts": {}, "patterns": {}}
        index.setdefault("accounts", {})[account_id] = self.project.relative(profile_path)
        pattern_index = index.setdefault("patterns", {})
        for pattern_id, relative_path in list(pattern_index.items()):
            existing_path = self.project.root / str(relative_path)
            try:
                existing = read_json(existing_path)
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(existing, dict) and existing.get("account_id") == account_id:
                pattern_index.pop(pattern_id, None)
        for pattern in patterns:
            pattern_index[pattern.pattern_id] = self.project.relative(
                pattern_dir / f"{pattern.pattern_id}.json"
            )
        atomic_write_json(index_path, index)
        state = self.project.load_state()
        state.last_distillation_at = datetime.now(UTC)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={
                "content_clusters": len(clusters),
                "comment_need_clusters": len(comment_clusters),
                "patterns": len(patterns),
                "craft_patterns": sum(item.pattern_type == "craft" for item in patterns),
                "counterexamples": sum(item.counterexample_count for item in patterns),
            },
            output_files=[
                *relative,
                self.project.relative(profile_path),
                self.project.relative(index_path),
            ],
            warnings=distillation.warnings,
        )
        return result


def _latest_distillation(project: ProjectLayout, account_id: str) -> AccountDistillation:
    candidates: list[AccountDistillation] = []
    for path in (project.root / "reports" / "accounts" / account_id).glob("*/distillation.json"):
        candidates.append(AccountDistillation.model_validate(read_json(path)))
    if not candidates:
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            f"No account distillation found: {account_id}",
            details={"next": "run distiller distill for every target and benchmark account"},
        )
    return max(candidates, key=lambda item: (item.generated_at, item.distillation_id))


class BenchmarkComparisonService:
    """Create a conservative transfer matrix from completed account distillations."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def compare(
        self,
        *,
        target_account_id: str,
        benchmark_account_ids: list[str],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Compare distilled patterns plus same-platform public interaction profiles."""

        benchmark_ids = sorted(
            {item for item in benchmark_account_ids if item != target_account_id}
        )
        if not benchmark_ids:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID, "At least one distinct benchmark account is required"
            )
        target = _latest_distillation(self.project, target_account_id)
        benchmarks = [_latest_distillation(self.project, item) for item in benchmark_ids]
        profile_service = AccountBenchmarkProfileService(self.project)
        profiles = [
            AccountBenchmarkProfile.model_validate(
                profile_service.build(account_id=account_id, dry_run=dry_run)["profile"]
            )
            for account_id in [target_account_id, *benchmark_ids]
        ]
        ranking_profiles = [
            profile for profile in profiles if profile.platform == profiles[0].platform
        ]
        excluded_ranking_accounts = sorted(
            profile.account_id for profile in profiles if profile not in ranking_profiles
        )
        rankings = rank_account_profiles(ranking_profiles)
        target_platform = str(target.data_scope.get("platform") or "unknown")
        target_features = {cluster.feature_value for cluster in target.content_clusters}
        seed = {
            "target": target.distillation_id,
            "benchmarks": [item.distillation_id for item in benchmarks],
            "profiles": [item.profile_id for item in profiles],
            "version": COMPARISON_VERSION,
        }
        comparison_id = stable_id("cmp_", sha256_json(seed))
        output_dir = self.project.root / "reports" / "comparisons" / comparison_id
        paths = [
            output_dir / "comparison.json",
            output_dir / "report.md",
            output_dir / "evidence-index.json",
            output_dir / "warnings.json",
        ]
        relative = [self.project.relative(path) for path in paths]
        if paths[0].is_file() and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "comparison": read_json(paths[0]),
                "outputs": relative,
            }
        input_hashes = sorted(
            {
                sha256_json(target.model_dump(mode="json")),
                *(sha256_json(item.model_dump(mode="json")) for item in benchmarks),
                *(item for profile in profiles for item in profile.input_hashes),
            }
        )
        manifest = (
            None
            if dry_run
            else self.project.begin_run("compare accounts", input_hashes=input_hashes)
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", comparison_id)
        generated_at = datetime.now(UTC)
        collector = _EvidenceCollector(comparison_id)
        target_evidence = ArtifactEvidenceIndex.model_validate(
            read_json(self.project.root / target.evidence_index_path)
        )
        target_evidence_by_id = {item.evidence_id: item for item in target_evidence.items}
        benchmark_evidence_by_account = {
            benchmark.account_id: {
                item.evidence_id: item
                for item in ArtifactEvidenceIndex.model_validate(
                    read_json(self.project.root / benchmark.evidence_index_path)
                ).items
            }
            for benchmark in benchmarks
        }
        matrix: list[TransferMatrixItem] = []
        warnings: list[str] = []
        if excluded_ranking_accounts:
            warnings.append(
                "cross_platform_accounts_excluded_from_interaction_ranking:"
                + ",".join(excluded_ranking_accounts)
            )
        for benchmark in benchmarks:
            source_platform = str(benchmark.data_scope.get("platform") or "unknown")
            same_platform = source_platform == target_platform
            if not same_platform:
                warnings.append(
                    f"cross_platform_baselines_kept_separate:{benchmark.account_id}:{source_platform}"
                )
            for pattern in benchmark.patterns:
                feature = pattern.feature_conditions.get("feature_value", "unknown")
                overlap = feature in target_features
                source_items = benchmark_evidence_by_account[benchmark.account_id]
                related_items = [
                    source_items[item] for item in pattern.evidence_ids if item in source_items
                ]
                related_items.extend(
                    target_evidence_by_id[cluster.evidence_id]
                    for cluster in target.content_clusters
                    if cluster.feature_value == feature
                    and cluster.evidence_id in target_evidence_by_id
                )
                evidence_id = collector.add(
                    label=f"transfer.{benchmark.account_id}.{pattern.pattern_id}",
                    classification="hypothesis",
                    value={
                        "source_pattern": pattern.model_dump(mode="json"),
                        "target_feature_overlap": overlap,
                        "same_platform": same_platform,
                    },
                    calculation=(
                        "conservative transfer review using normalized content features and "
                        "source pattern maturity; no raw cross-account metric comparison"
                    ),
                    sources=[source for item in related_items for source in item.sources],
                )
                verdict: Literal[
                    "directly_test", "adapt_then_test", "understand_only", "do_not_migrate"
                ]
                if pattern.pattern_type == "failure":
                    verdict = "do_not_migrate"
                elif not same_platform:
                    verdict = "understand_only"
                elif overlap and pattern.maturity_level >= 1:
                    verdict = "directly_test"
                else:
                    verdict = "adapt_then_test"
                risks = list(pattern.risks)
                if not same_platform:
                    risks.append("platform_mechanism_difference")
                if pattern.confounders:
                    risks.append("source_pattern_has_confounders")
                matrix.append(
                    TransferMatrixItem(
                        source_account_id=benchmark.account_id,
                        target_account_id=target_account_id,
                        pattern_id=pattern.pattern_id,
                        pattern_name=pattern.name,
                        user_alignment="medium" if overlap else "unknown",
                        value_alignment="high" if overlap else "unknown",
                        account_stage_alignment="unknown",
                        resource_alignment="unknown",
                        platform_alignment="same" if same_platform else "different",
                        business_alignment="unknown",
                        replicability=pattern.replicability,
                        verdict=verdict,
                        preserve=["结构化特征与验证假设"],
                        replace=([] if overlap else ["内容主题、用户场景和表达语境"]),
                        remove=(
                            ["失败模式及其表面模仿"] if pattern.pattern_type == "failure" else []
                        ),
                        risks=list(dict.fromkeys(risks)),
                        evidence_ids=[evidence_id],
                    )
                )
        matrix.sort(key=lambda item: (item.source_account_id, item.verdict, item.pattern_id))
        experiments = [
            f"将“{item.pattern_name}”按 `{item.verdict}` 处理，并在目标账号同支柱做小样本对照。"
            for item in matrix
            if item.verdict in {"directly_test", "adapt_then_test"}
        ][:10]
        warnings.extend(
            [
                "transfer_matrix_is_a_planning_hypothesis_not_a_validated_rule",
                "audience_resources_account_stage_and_business_alignment_require_human_input",
            ]
        )
        comparison = BenchmarkComparison(
            comparison_id=comparison_id,
            target_account_id=target_account_id,
            benchmark_account_ids=benchmark_ids,
            generated_at=generated_at,
            run_id=run_id,
            profiles=profiles,
            rankings=rankings,
            ranking_basis=[
                "单条视频点赞、评论、分享、收藏中位数的同平台百分位",
                "粉丝数可用时加入每千粉单条视频互动中位数",
                "播放量因平台可见性限制不参与排序",
                "评论情绪、意图、痛点、追问和购买意向只作内容解释，不作为流量分数",
            ],
            transfer_matrix=matrix,
            recommended_experiments=experiments,
            evidence_index_path=relative[2],
            warnings_path=relative[3],
            warnings=list(dict.fromkeys(warnings)),
        )
        evidence = ArtifactEvidenceIndex(
            artifact_id=comparison_id,
            account_ids=[target_account_id, *benchmark_ids],
            run_id=run_id,
            generated_at=generated_at,
            input_hashes=input_hashes,
            items=[collector.items[key] for key in sorted(collector.items)],
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "comparison": comparison.model_dump(mode="json"),
            "outputs": relative,
        }
        if dry_run:
            return result
        assert manifest is not None
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(paths[0], comparison.model_dump(mode="json"))
        atomic_write_text(
            paths[1],
            _render(
                "benchmark-comparison.md.j2",
                comparison=comparison.model_dump(mode="python"),
                craft_labels=CRAFT_CATEGORY_LABELS,
            ),
        )
        atomic_write_json(paths[2], evidence.model_dump(mode="json"))
        atomic_write_json(paths[3], comparison.warnings)
        state = self.project.load_state()
        state.last_comparison_at = datetime.now(UTC)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={"transfer_items": len(matrix), "experiments": len(experiments)},
            output_files=relative,
            warnings=comparison.warnings,
        )
        return result
