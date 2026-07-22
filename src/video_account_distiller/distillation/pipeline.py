"""Deterministic account patterns, counterexamples, and transfer review."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from jinja2 import Environment, StrictUndefined

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.metrics.calculations import median
from video_account_distiller.models import (
    AccountDistillation,
    AccountPositioning,
    ArtifactEvidenceIndex,
    BenchmarkComparison,
    CommentAnalysis,
    ContentCluster,
    EvidenceItem,
    EvidenceSource,
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
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json

DISTILLATION_VERSION = "1.0.0"
COMPARISON_VERSION = "1.0.0"
Classification = Literal[
    "fact", "semantic_annotation", "statistical_association", "hypothesis", "warning"
]


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
) -> list[ContentCluster]:
    grouped: dict[tuple[str, str], list[AccountVideoRecord]] = defaultdict(list)
    for record in dataset.records:
        analysis = video_analyses.get(record.video.video_id)
        semantic_pillar = (
            analysis.blind_analysis.semantics.primary_pillar if analysis is not None else "unknown"
        )
        if semantic_pillar != "unknown":
            grouped[("semantic_pillar", semantic_pillar)].append(record)
        else:
            proxy = (record.video.content_type or "unknown").strip() or "unknown"
            grouped[("content_type_proxy", proxy)].append(record)

    clusters: list[ContentCluster] = []
    for (method, value), records in sorted(grouped.items()):
        video_ids = sorted(record.video.video_id for record in records)
        cluster_id = stable_id("clu_", dataset.account.account_id, method, value, *video_ids)
        band_counts = dict(sorted(Counter(_band(record) for record in records).items()))
        known_bands = [band for band in (_band(record) for record in records) if band != "unknown"]
        known_scores = [score for record in records if (score := _score(record)) is not None]
        evidence_id = collector.add(
            label=f"content_cluster.{cluster_id}",
            classification=("semantic_annotation" if method == "semantic_pillar" else "fact"),
            value={
                "feature_value": value,
                "method": method,
                "video_ids": video_ids,
                "performance_band_counts": band_counts,
            },
            calculation=(
                "group by latest blind semantic pillar"
                if method == "semantic_pillar"
                else "group by normalized content_type proxy"
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
                median_performance_score=median([float(item) for item in known_scores]),
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
    feature_type: Literal["topic", "hook", "cta", "posting_time", "comment_trigger"],
    feature_name: str,
    feature_value: str,
    records: list[AccountVideoRecord],
    source_evidence_ids: list[str],
    collector: _EvidenceCollector,
    min_support: int,
    generated_at: datetime,
) -> Pattern | None:
    if len(records) < min_support:
        return None
    eligible = [
        record for record in records if not _is_promoted(record) and not _is_outlier(record)
    ]
    high = [record for record in eligible if _band(record) in {"S", "A"}]
    low = [record for record in eligible if _band(record) in {"C", "D"}]
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
            "account-local S/A versus C/D comparison; promoted and robust outlier videos are "
            "excluded from support/counterexample counts"
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
        feature_conditions={"feature_type": feature_type, "feature_value": feature_value},
        target_metrics=["performance_score"],
        support_video_ids=support_ids,
        counterexample_video_ids=counterexample_ids,
        support_count=len(support_ids),
        counterexample_count=len(counterexample_ids),
        effect_summary=(
            f"eligible={len(eligible)}; high={len(high)}; low={len(low)}; "
            f"account-local direction={direction}"
        ),
        confounders=confounders,
        scope=PatternScope(
            platforms=[dataset.account.platform.value],
            pillars=[feature_value] if feature_type == "topic" else [],
            account_stages=["unknown"],
        ),
        confidence=confidence,
        maturity_level=maturity,
        replicability=("high" if feature_type in {"topic", "hook", "cta"} else "medium"),
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
) -> list[Pattern]:
    records_by_id = {record.video.video_id: record for record in dataset.records}
    groups: list[
        tuple[
            Literal["topic", "hook", "cta", "posting_time", "comment_trigger"],
            str,
            str,
            list[AccountVideoRecord],
            list[str],
        ]
    ] = []
    for cluster in clusters:
        groups.append(
            (
                "topic",
                "内容簇",
                cluster.feature_value,
                [records_by_id[item] for item in cluster.video_ids],
                [cluster.evidence_id],
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
        if cta not in {"unknown", "none"}:
            cta_groups[cta].append(record)
    for value, records in sorted(hook_groups.items()):
        groups.append(("hook", "Hook", value, records, []))
    for value, records in sorted(cta_groups.items()):
        groups.append(("cta", "CTA", value, records, []))
    time_groups: dict[str, list[AccountVideoRecord]] = defaultdict(list)
    for record in dataset.records:
        if record.video.published_at is None:
            continue
        hour = record.video.published_at.hour
        bucket = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        time_groups[bucket].append(record)
    for value, records in sorted(time_groups.items()):
        groups.append(("posting_time", "发布时间", value, records, []))
    if comment_analysis is not None:
        for comment_cluster in comment_analysis.need_clusters:
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
                )
            )

    patterns = [
        pattern
        for feature_type, name, value, records, evidence_ids in groups
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
        comment_analysis, comment_evidence = _latest_comment_analysis(self.project, account_id)
        config = load_config(self.project.config_path)
        generated_at = datetime.now(UTC)
        seed = {
            "account_id": account_id,
            "version": DISTILLATION_VERSION,
            "input_hashes": dataset.input_hashes,
            "video_analyses": sorted(item.analysis_id for item in video_analyses.values()),
            "comment_analysis": comment_analysis.analysis_id if comment_analysis else None,
            "min_pattern_support": config.analysis.min_pattern_support,
            "analysis_config": config.analysis.model_dump(mode="json"),
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
        clusters = _build_clusters(dataset, video_analyses, collector)
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
        )
        comment_clusters = comment_analysis.need_clusters if comment_analysis else []
        persona_signals = sorted(
            {
                signal
                for analysis in video_analyses.values()
                for signal in analysis.blind_analysis.semantics.persona_signals
            }
        )
        focus = [
            cluster.name
            for cluster in sorted(clusters, key=lambda item: (-item.video_count, item.name))[:3]
        ]
        need_names = [
            cluster.name
            for cluster in sorted(comment_clusters, key=lambda item: (-item.frequency, item.name))[
                :5
            ]
        ]
        positioning = AccountPositioning(
            statement=(
                f"基于标准化样本，账号内容主要集中在：{'、'.join(focus)}。"
                if focus
                else "当前数据不足以形成可观察的内容定位。"
            ),
            observed_content_focus=focus,
            audience_need_clusters=need_names,
            persona_signals=persona_signals,
            confidence=(
                "high"
                if len(dataset.records) >= 30 and len(video_analyses) >= 10
                else "medium"
                if len(dataset.records) >= 15
                else "low"
            ),
            evidence_ids=[
                account_evidence,
                *(cluster.evidence_id for cluster in clusters[:5]),
                *(cluster.evidence_id for cluster in comment_clusters[:5]),
            ],
            unknowns=[
                *([] if persona_signals else ["persona_signals"]),
                "visual_and_audio_identity",
                "account_stage",
                "commercial_conversion_path",
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
        if not patterns:
            warnings.append("no_pattern_met_minimum_support")
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
                "content_cluster_count": len(clusters),
                "pattern_count": len(patterns),
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
                "account-distillation.md.j2", distillation=distillation.model_dump(mode="python")
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
                    "",
                ]
            ),
        )
        index_path = self.project.root / "knowledge-base" / "index.json"
        index = read_json(index_path) if index_path.is_file() else {"accounts": {}, "patterns": {}}
        index.setdefault("accounts", {})[account_id] = self.project.relative(profile_path)
        for pattern in patterns:
            index.setdefault("patterns", {})[pattern.pattern_id] = self.project.relative(
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
        """Compare distilled patterns without cross-platform raw metric comparison."""

        benchmark_ids = sorted(
            {item for item in benchmark_account_ids if item != target_account_id}
        )
        if not benchmark_ids:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID, "At least one distinct benchmark account is required"
            )
        target = _latest_distillation(self.project, target_account_id)
        benchmarks = [_latest_distillation(self.project, item) for item in benchmark_ids]
        target_platform = str(target.data_scope.get("platform") or "unknown")
        target_features = {cluster.feature_value for cluster in target.content_clusters}
        seed = {
            "target": target.distillation_id,
            "benchmarks": [item.distillation_id for item in benchmarks],
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
            _render("benchmark-comparison.md.j2", comparison=comparison.model_dump(mode="python")),
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
