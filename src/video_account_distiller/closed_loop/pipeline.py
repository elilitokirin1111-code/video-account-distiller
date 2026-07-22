"""Deterministic Phase 5 content scoring and learning-loop pipeline."""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from jinja2 import Environment, StrictUndefined

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.metrics.calculations import robust_z_scores, safe_divide
from video_account_distiller.models import (
    AccountDistillation,
    ArtifactEvidenceIndex,
    ContentCandidate,
    DerivedMetrics,
    DimensionScore,
    EvidenceItem,
    EvidenceSource,
    Experiment,
    MetricSnapshot,
    Prediction,
    PredictionError,
    Publication,
    QuantileInterval,
    Retro,
    RetroActualMetrics,
    Rubric,
    RubricChangeProposal,
    RubricDimension,
    Rule,
    RuleChangeProposal,
    RuleStatus,
    ScoreResult,
    SnapshotPlanItem,
    Video,
)
from video_account_distiller.models.analysis import EvidenceClassification
from video_account_distiller.sampling.dataset import (
    AccountVideoRecord,
    load_account_dataset,
)
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import hash_text, sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json
from video_account_distiller.version import CLOSED_LOOP_SCHEMA_VERSION

SCORING_VERSION = "content-scoring-v1"
PREDICTION_VERSION = "account-quantile-prediction-v1"
RETRO_VERSION = "snapshot-retro-v1"
RUBRIC_VERSION = "1.0.0"
RULE_VERSION = "1.0.0"

_SNAPSHOT_LABELS = {1: "t1h", 24: "t24h", 72: "t3d", 168: "t7d"}
_LABEL_HOURS = {value: key for key, value in _SNAPSHOT_LABELS.items()}

_DIMENSION_SPECS: tuple[tuple[str, str, float, list[str]], ...] = (
    (
        "account_match",
        "账号匹配",
        15.0,
        ["与账号定位和主要内容支柱一致", "不依赖尚未具备的账号资产"],
    ),
    (
        "audience_need",
        "用户需求",
        15.0,
        ["回应明确用户问题或决策需求", "需求证据可追溯到评论或账号样本"],
    ),
    (
        "topic_strength",
        "选题强度",
        15.0,
        ["选题具体且可理解", "价值、对象或场景至少有一项明确"],
    ),
    (
        "hook",
        "Hook",
        15.0,
        ["开头快速建立问题、利益或好奇心", "不使用无法兑现的夸张承诺"],
    ),
    (
        "structure_value",
        "结构与价值释放",
        15.0,
        ["信息有清晰推进", "结论、步骤或价值释放可识别"],
    ),
    (
        "credibility",
        "可信度与证据",
        10.0,
        ["关键判断有来源、边界或可核验信息", "区分事实与推断"],
    ),
    (
        "interaction_cta",
        "互动与 CTA",
        5.0,
        ["CTA 与内容价值一致", "不以诱导或虚假承诺换取互动"],
    ),
    (
        "feasibility",
        "制作可行性",
        5.0,
        ["脚本长度和拍摄要求可执行", "制作资源假设清楚"],
    ),
    (
        "risk_control",
        "风险控制",
        5.0,
        ["避免绝对化、保证性或敏感承诺", "必要的适用条件和限制可见"],
    ),
)

_PATTERN_DIMENSIONS = {
    "topic": "topic_strength",
    "hook": "hook",
    "structure": "structure_value",
    "persona": "account_match",
    "cta": "interaction_cta",
    "posting_time": "feasibility",
    "comment_trigger": "audience_need",
    "conversion": "interaction_cta",
    "failure": "risk_control",
}

_RISK_PATTERNS = {
    "guaranteed_outcome": re.compile(
        r"必爆|保证(?:爆|成功|有效|达到|获得)|一定会|稳赚|百分百|100%|绝对有效"
    ),
    "unsupported_superlative": re.compile(r"全网第一|行业第一|最便宜|最好|唯一"),
    "sensitive_claim": re.compile(r"治愈|根治|无风险|零风险|包过|包赚"),
}


def _render(template_name: str, **context: Any) -> str:
    path = Path(__file__).resolve().parents[1] / "reports" / "templates" / template_name
    template = Environment(undefined=StrictUndefined, autoescape=False).from_string(
        path.read_text(encoding="utf-8")
    )
    return template.render(**context).strip() + "\n"


def _source(table: str, record: Any) -> EvidenceSource:
    return EvidenceSource(
        table=cast(Any, table),
        record_id=record.record_id,
        source_record_id=record.source_record_id,
        raw_hash=record.raw_hash,
        run_id=record.run_id,
    )


def _record_sources(record: AccountVideoRecord) -> list[EvidenceSource]:
    sources = [_source("videos", record.video)]
    if record.metric is not None:
        sources.append(_source("metric_snapshots", record.metric))
    if record.derived is not None:
        sources.append(_source("derived_metrics", record.derived))
    return sources


@dataclass
class _EvidenceCollector:
    artifact_id: str
    items: dict[str, EvidenceItem] = field(default_factory=dict)

    def add(
        self,
        *,
        label: str,
        classification: EvidenceClassification,
        value: Any,
        calculation: str,
        sources: Iterable[EvidenceSource],
    ) -> str:
        evidence_id = stable_id("ev_", self.artifact_id, label, sha256_json(value))
        unique = {(item.table, item.record_id): item for item in sources}
        self.items[evidence_id] = EvidenceItem(
            evidence_id=evidence_id,
            label=label,
            classification=classification,
            value=value,
            calculation=calculation,
            sources=[unique[key] for key in sorted(unique)],
        )
        return evidence_id


def _latest_distillation(project: ProjectLayout, account_id: str) -> AccountDistillation:
    candidates = [
        AccountDistillation.model_validate(read_json(path))
        for path in (project.root / "reports" / "accounts" / account_id).glob("*/distillation.json")
    ]
    if not candidates:
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            f"No account distillation found: {account_id}",
            details={"next": "run distiller distill before scoring"},
        )
    return max(candidates, key=lambda item: (item.generated_at, item.distillation_id))


def _load_by_id(project: ProjectLayout, pattern: str, model_type: type[Any], item_id: str) -> Any:
    matches = [path for path in project.root.glob(pattern) if path.parent.name == item_id]
    if not matches:
        raise DistillerError(ErrorCode.INPUT_MISSING, f"Artifact not found: {item_id}")
    return model_type.model_validate(read_json(matches[0]))


def _load_candidate(project: ProjectLayout, candidate_id: str) -> ContentCandidate:
    path = project.root / "candidates" / candidate_id / "candidate.json"
    if not path.is_file():
        raise DistillerError(ErrorCode.INPUT_MISSING, f"Candidate not found: {candidate_id}")
    return ContentCandidate.model_validate(read_json(path))


def _load_score(project: ProjectLayout, score_id: str) -> ScoreResult:
    return cast(
        ScoreResult,
        _load_by_id(project, "reports/scoring/*/*/score.json", ScoreResult, score_id),
    )


def _load_prediction(project: ProjectLayout, prediction_id: str) -> Prediction:
    path = project.root / "predictions" / prediction_id / "prediction.json"
    if not path.is_file():
        raise DistillerError(ErrorCode.INPUT_MISSING, f"Prediction not found: {prediction_id}")
    return Prediction.model_validate(read_json(path))


def _load_publication(project: ProjectLayout, publication_id: str) -> Publication:
    path = project.root / "publications" / publication_id / "publication.json"
    if not path.is_file():
        raise DistillerError(ErrorCode.INPUT_MISSING, f"Publication not found: {publication_id}")
    return Publication.model_validate(read_json(path))


def _rule_path(project: ProjectLayout, rule: Rule) -> Path:
    return project.root / "knowledge-base" / "rules" / rule.rule_id / f"{rule.version}.json"


def _rule_is_negative(rule: Rule) -> bool:
    return "direction=低表现" in rule.expected_effect or "低表现" in rule.name


def _materialize_rules(
    project: ProjectLayout,
    distillation: AccountDistillation,
    *,
    dry_run: bool,
) -> list[Rule]:
    created_at = datetime.now(UTC)
    rules: list[Rule] = []
    for pattern in distillation.patterns:
        feature_value = pattern.feature_conditions.get("feature_value", "unknown")
        rule_id = stable_id("rule_", distillation.account_id, pattern.pattern_id)
        expected_path = project.root / "knowledge-base" / "rules" / rule_id / f"{RULE_VERSION}.json"
        if expected_path.is_file():
            rules.append(Rule.model_validate(read_json(expected_path)))
            continue
        negative = pattern.pattern_type == "failure"
        rule = Rule(
            rule_id=rule_id,
            account_id=distillation.account_id,
            source_pattern_ids=[pattern.pattern_id],
            name=pattern.name,
            instruction=(
                f"将特征“{feature_value}”作为待验证风险，只在受控对照中使用。"
                if negative
                else f"小规模测试特征“{feature_value}”，并保留同支柱反例。"
            ),
            scope=pattern.scope,
            required_conditions=dict(pattern.feature_conditions),
            forbidden_conditions=["promoted_traffic_as_evidence", "robust_outlier_as_default"],
            expected_effect=pattern.effect_summary,
            target_metric=pattern.target_metrics[0]
            if pattern.target_metrics
            else "performance_score",
            confidence=min(pattern.confidence, 0.75),
            evidence_count=pattern.support_count + pattern.counterexample_count,
            experiment_count=0,
            status=RuleStatus.CANDIDATE,
            version=RULE_VERSION,
            created_at=created_at,
            last_updated_at=created_at,
        )
        rules.append(rule)
        if not dry_run:
            atomic_write_json(expected_path, rule.model_dump(mode="json"))
    return sorted(rules, key=lambda item: item.rule_id)


def _materialize_rubric(
    project: ProjectLayout,
    distillation: AccountDistillation,
    rules: list[Rule],
    *,
    dry_run: bool,
) -> Rubric:
    rule_ids = [(item.rule_id, item.version) for item in rules]
    rubric_id = stable_id(
        "rub_", distillation.account_id, distillation.distillation_id, RUBRIC_VERSION, rule_ids
    )
    path = (
        project.root / "knowledge-base" / "rubrics" / distillation.account_id / f"{rubric_id}.json"
    )
    if path.is_file():
        return Rubric.model_validate(read_json(path))
    dimensions = []
    patterns_by_id = {item.pattern_id: item for item in distillation.patterns}
    for dimension_id, name, weight, guide in _DIMENSION_SPECS:
        evidence_rules = [
            rule.rule_id
            for rule in rules
            if _PATTERN_DIMENSIONS.get(patterns_by_id[rule.source_pattern_ids[0]].pattern_type)
            == dimension_id
        ]
        dimensions.append(
            RubricDimension(
                dimension_id=dimension_id,
                name=name,
                weight=weight,
                scoring_guide=guide,
                evidence_rule_ids=evidence_rules,
            )
        )
    rubric = Rubric(
        rubric_id=rubric_id,
        account_id=distillation.account_id,
        version=RUBRIC_VERSION,
        dimensions=dimensions,
        source_distillation_id=distillation.distillation_id,
        created_at=datetime.now(UTC),
    )
    if not dry_run:
        atomic_write_json(path, rubric.model_dump(mode="json"))
    return rubric


def _update_knowledge_index(project: ProjectLayout, rubric: Rubric, rules: list[Rule]) -> Path:
    path = project.root / "knowledge-base" / "index.json"
    index = read_json(path) if path.is_file() else {}
    index.setdefault("rules", {})
    index.setdefault("rubrics", {})
    for rule in rules:
        index["rules"][rule.rule_id] = project.relative(_rule_path(project, rule))
    rubric_path = (
        project.root / "knowledge-base" / "rubrics" / rubric.account_id / f"{rubric.rubric_id}.json"
    )
    index["rubrics"][rubric.account_id] = project.relative(rubric_path)
    atomic_write_json(path, index)
    return path


def _hour_bucket(hour: int) -> str:
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 14:
        return "midday"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _script_features(candidate: ContentCandidate, text: str) -> dict[str, set[str]]:
    first = text.strip()[:120]
    hooks: set[str] = set()
    if re.search(r"为什么|怎么|如何|[?？]", first):
        hooks.add("question_challenge")
    if re.search(r"\d", first):
        hooks.add("number_list")
    if re.search(r"别再|千万|避坑|后悔|损失", first):
        hooks.add("loss_aversion")
    if re.search(r"只要|立省|免费|直接|马上", first):
        hooks.add("clear_benefit")
    ctas: set[str] = set()
    if re.search(r"评论|留言", text):
        ctas.add("comment")
    if re.search(r"收藏", text):
        ctas.add("save")
    if re.search(r"关注", text):
        ctas.add("follow")
    if re.search(r"私信", text):
        ctas.add("direct_message")
    if re.search(r"预订|下单|购买|团购|链接", text):
        ctas.add("product")
    intents: set[str] = set()
    if re.search(r"价格|多少钱|费用|套餐", text):
        intents.update({"price_objection", "purchase_intent"})
    if re.search(r"怎么|步骤|教程|攻略", text):
        intents.add("request_tutorial")
    if re.search(r"为什么|是否|能不能|可以吗", text):
        intents.add("follow_up")
    posting = (
        {_hour_bucket(candidate.planned_publish_hour)}
        if candidate.planned_publish_hour is not None
        else set()
    )
    return {
        "topic": {candidate.target_pillar} if candidate.target_pillar else set(),
        "hook": hooks,
        "cta": ctas,
        "posting_time": posting,
        "comment_trigger": intents,
    }


def _matching_rules(rules: list[Rule], features: dict[str, set[str]]) -> list[Rule]:
    matched = []
    for rule in rules:
        feature_type = rule.required_conditions.get("feature_type")
        feature_value = rule.required_conditions.get("feature_value")
        if feature_type and feature_value and feature_value in features.get(feature_type, set()):
            matched.append(rule)
    return matched


def _base_dimension_scores(
    candidate: ContentCandidate, text: str
) -> dict[str, tuple[float, str, list[str]]]:
    stripped = text.strip()
    first = stripped[:120]
    paragraphs = [item.strip() for item in re.split(r"\n+", stripped) if item.strip()]
    risks = [name for name, pattern in _RISK_PATTERNS.items() if pattern.search(stripped)]
    specificity = bool(re.search(r"\d|适合|针对|场景|酒店|客房|早餐|会员|预订", stripped))
    hook_signal = bool(re.search(r"为什么|怎么|如何|[?？]|别再|千万|\d", first))
    structure_signal = len(paragraphs) >= 3 or bool(
        re.search(r"首先|第一|然后|其次|最后|总结|所以", stripped)
    )
    evidence_signal = bool(re.search(r"根据|官方|数据|实测|案例|适用|以实际|条件", stripped))
    cta_signal = bool(re.search(r"评论|留言|收藏|关注|私信|预订|下单|链接", stripped))
    length = len(stripped)
    return {
        "account_match": (
            72.0 if candidate.target_pillar else 52.0,
            "已指定账号内容支柱。" if candidate.target_pillar else "未指定目标内容支柱。",
            [] if candidate.target_pillar else ["target_pillar"],
        ),
        "audience_need": (
            75.0 if re.search(r"你|用户|客人|住客|家庭|会员|出差|亲子", stripped) else 55.0,
            "脚本明确指向用户或使用场景。"
            if re.search(r"你|用户|客人|住客|家庭|会员|出差|亲子", stripped)
            else "用户对象或场景不够明确。",
            []
            if re.search(r"你|用户|客人|住客|家庭|会员|出差|亲子", stripped)
            else ["audience_or_scene"],
        ),
        "topic_strength": (
            78.0 if specificity else 55.0,
            "选题包含具体对象、数字或使用场景。" if specificity else "选题仍较宽泛。",
            [] if specificity else ["specific_topic_or_scenario"],
        ),
        "hook": (
            80.0 if hook_signal else 48.0,
            "开头存在问题、数字、损失或利益信号。" if hook_signal else "开头缺少可识别的 Hook。",
            [] if hook_signal else ["recognizable_hook"],
        ),
        "structure_value": (
            80.0 if structure_signal and length >= 100 else 62.0 if length >= 80 else 42.0,
            "脚本具有推进结构和足够的信息展开。"
            if structure_signal and length >= 100
            else "脚本结构或价值展开仍不充分。",
            [] if structure_signal and length >= 100 else ["clear_progression_and_value_release"],
        ),
        "credibility": (
            82.0 if evidence_signal else 45.0,
            "脚本包含来源、数据、案例或适用边界。" if evidence_signal else "缺少证据或适用边界。",
            [] if evidence_signal else ["evidence_or_applicability_boundary"],
        ),
        "interaction_cta": (
            78.0 if cta_signal else 45.0,
            "包含与内容相关的行动提示。" if cta_signal else "没有明确且一致的 CTA。",
            [] if cta_signal else ["aligned_cta"],
        ),
        "feasibility": (
            82.0 if 80 <= length <= 1200 else 58.0,
            "脚本长度处于可执行范围。"
            if 80 <= length <= 1200
            else "脚本长度可能不足或制作负担偏高。",
            [] if 80 <= length <= 1200 else ["feasible_script_length"],
        ),
        "risk_control": (
            max(20.0, 92.0 - 24.0 * len(risks)),
            "未发现常见保证性或敏感承诺。" if not risks else f"发现风险：{', '.join(risks)}。",
            risks,
        ),
    }


def _dimension_for_rule(rule: Rule, patterns: dict[str, Any]) -> str:
    pattern = patterns[rule.source_pattern_ids[0]]
    return _PATTERN_DIMENSIONS.get(pattern.pattern_type, "topic_strength")


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _adjusted_interval(values: list[float], adjustment: float) -> QuantileInterval:
    return QuantileInterval(
        p25=round(max(0.0, _quantile(values, 0.25) * adjustment), 6),
        p50=round(max(0.0, _quantile(values, 0.50) * adjustment), 6),
        p75=round(max(0.0, _quantile(values, 0.75) * adjustment), 6),
    )


def _is_eligible(record: AccountVideoRecord) -> bool:
    return not (record.metric is not None and record.metric.is_promoted is True) and not (
        record.derived is not None and bool(record.derived.outlier_flags)
    )


class ScoringService:
    """Score a user-provided script against an account-local, versioned Rubric."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def score(
        self,
        *,
        account_id: str,
        script: Path,
        title: str | None = None,
        topic: str | None = None,
        target_pillar: str | None = None,
        target_metric: str = "performance_score",
        planned_publish_hour: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Create a traceable score without writing a prediction."""

        if not script.is_file():
            raise DistillerError(ErrorCode.INPUT_MISSING, f"Script not found: {script}")
        text = script.read_text(encoding="utf-8").strip()
        if not text:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Script is empty")
        dataset = load_account_dataset(self.project, account_id)
        distillation = _latest_distillation(self.project, account_id)
        rules = _materialize_rules(self.project, distillation, dry_run=dry_run)
        rubric = _materialize_rubric(self.project, distillation, rules, dry_run=dry_run)
        script_hash = sha256_file(script)
        suffix = script.suffix.lower() if script.suffix.lower() in {".md", ".txt"} else ".txt"
        raw_path = self.project.root / "raw" / "candidates" / f"{script_hash}{suffix}"
        derived_title = next((line.strip("# ") for line in text.splitlines() if line.strip()), "")
        candidate_seed = {
            "account_id": account_id,
            "script_hash": script_hash,
            "title": title or derived_title[:120] or script.stem,
            "topic": topic,
            "target_pillar": target_pillar,
            "target_metric": target_metric,
            "planned_publish_hour": planned_publish_hour,
            "version": SCORING_VERSION,
        }
        candidate_id = stable_id("cand_", sha256_json(candidate_seed))
        candidate = ContentCandidate(
            candidate_id=candidate_id,
            account_id=account_id,
            title=str(candidate_seed["title"]),
            topic=topic,
            script_path=self.project.relative(raw_path),
            script_hash=script_hash,
            target_platform=dataset.account.platform,
            target_pillar=target_pillar,
            target_metric=target_metric,
            planned_publish_hour=planned_publish_hour,
            created_at=datetime.now(UTC),
        )
        score_seed = {
            "candidate": candidate_seed,
            "rubric_id": rubric.rubric_id,
            "rubric_version": rubric.version,
            "rule_versions": {item.rule_id: item.version for item in rules},
            "version": SCORING_VERSION,
        }
        score_id = stable_id("score_", sha256_json(score_seed))
        output_dir = self.project.root / "reports" / "scoring" / account_id / score_id
        paths = [
            output_dir / "score.json",
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
                "candidate": _load_candidate(self.project, candidate_id).model_dump(mode="json"),
                "score": read_json(paths[0]),
                "outputs": relative,
            }
        input_hashes = sorted(
            {
                *dataset.input_hashes,
                script_hash,
                hash_text(distillation.model_dump_json()),
                hash_text(rubric.model_dump_json()),
                *(hash_text(rule.model_dump_json()) for rule in rules),
            }
        )
        manifest = (
            None if dry_run else self.project.begin_run("score content", input_hashes=input_hashes)
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", score_id)
        collector = _EvidenceCollector(score_id)
        baseline_sources = [
            _source("accounts", dataset.account),
            *(source for record in dataset.records for source in _record_sources(record)),
        ]
        baseline_evidence = collector.add(
            label="score.account_context",
            classification="fact",
            value={
                "account_id": account_id,
                "platform": dataset.account.platform.value,
                "video_count": len(dataset.records),
                "distillation_id": distillation.distillation_id,
            },
            calculation="latest normalized account dataset plus latest account distillation",
            sources=baseline_sources,
        )
        features = _script_features(candidate, text)
        matched_rules = _matching_rules(rules, features)
        patterns = {item.pattern_id: item for item in distillation.patterns}
        phase4_evidence = ArtifactEvidenceIndex.model_validate(
            read_json(self.project.root / distillation.evidence_index_path)
        )
        phase4_by_id = {item.evidence_id: item for item in phase4_evidence.items}
        rule_evidence_ids: dict[str, str] = {}
        for rule in matched_rules:
            pattern = patterns[rule.source_pattern_ids[0]]
            sources = [
                source
                for evidence_id in pattern.evidence_ids
                if evidence_id in phase4_by_id
                for source in phase4_by_id[evidence_id].sources
            ] or baseline_sources
            rule_evidence_ids[rule.rule_id] = collector.add(
                label=f"score.rule.{rule.rule_id}",
                classification="statistical_association",
                value={
                    "rule_id": rule.rule_id,
                    "version": rule.version,
                    "status": rule.status.value,
                    "matched_conditions": rule.required_conditions,
                },
                calculation="script feature match against a versioned account-local candidate rule",
                sources=sources,
            )
        base_scores = _base_dimension_scores(candidate, text)
        max_adjustment = load_config(self.project.config_path).scoring.max_rule_score_adjustment
        dimensions: list[DimensionScore] = []
        for dimension in rubric.dimensions:
            raw_score, rationale, missing = base_scores[dimension.dimension_id]
            relevant = [
                rule
                for rule in matched_rules
                if _dimension_for_rule(rule, patterns) == dimension.dimension_id
            ]
            adjustments = []
            for rule in relevant:
                maturity_factor = {
                    RuleStatus.CANDIDATE: 0.25,
                    RuleStatus.EXPERIMENTAL: 0.50,
                    RuleStatus.VALIDATED: 1.0,
                    RuleStatus.DEPRECATED: 0.0,
                    RuleStatus.REJECTED: 0.0,
                }[rule.status]
                direction = -1.0 if _rule_is_negative(rule) else 1.0
                adjustments.append(direction * max_adjustment * maturity_factor * rule.confidence)
            adjusted = min(100.0, max(0.0, raw_score + sum(adjustments)))
            weighted = round(adjusted * dimension.weight / 100.0, 4)
            dimensions.append(
                DimensionScore(
                    dimension_id=dimension.dimension_id,
                    name=dimension.name,
                    raw_score=round(adjusted, 2),
                    weight=dimension.weight,
                    weighted_score=weighted,
                    rationale=(
                        rationale
                        + (
                            f" 匹配 {len(relevant)} 条低成熟度账号规则，仅作小幅校准。"
                            if relevant
                            else ""
                        )
                    ),
                    evidence_rule_ids=[item.rule_id for item in relevant],
                    evidence_pattern_ids=[item.source_pattern_ids[0] for item in relevant],
                    missing_items=missing,
                )
            )
        total = round(sum(item.weighted_score for item in dimensions), 2)
        strengths = [item.name for item in dimensions if item.raw_score >= 75]
        weaknesses = [item.name for item in dimensions if item.raw_score < 60]
        required_fixes = list(
            dict.fromkeys(item for dimension in dimensions for item in dimension.missing_items)
        )
        risk_flags = list(
            dict.fromkeys(name for name, pattern in _RISK_PATTERNS.items() if pattern.search(text))
        )
        warnings = [
            "score_is_an_explainable_heuristic_not_a_performance_prediction",
            "candidate_or_experimental_rules_cannot_dominate_the_rubric",
        ]
        if not target_pillar:
            warnings.append("target_pillar_missing")
        if not matched_rules:
            warnings.append("no_account_rule_matched_script_features")
        score = ScoreResult(
            score_id=score_id,
            candidate_id=candidate_id,
            account_id=account_id,
            rubric_id=rubric.rubric_id,
            rubric_version=rubric.version,
            total_score=total,
            dimension_scores=dimensions,
            strengths=strengths,
            weaknesses=weaknesses,
            required_fixes=required_fixes,
            risk_flags=risk_flags,
            evidence_ids=[baseline_evidence, *sorted(rule_evidence_ids.values())],
            created_at=datetime.now(UTC),
            run_id=run_id,
            input_hashes=input_hashes,
            evidence_index_path=relative[2],
            warnings_path=relative[3],
            warnings=warnings,
        )
        evidence = ArtifactEvidenceIndex(
            schema_version=CLOSED_LOOP_SCHEMA_VERSION,
            artifact_id=score_id,
            account_ids=[account_id],
            run_id=run_id,
            generated_at=score.created_at,
            input_hashes=input_hashes,
            items=[collector.items[key] for key in sorted(collector.items)],
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "candidate": candidate.model_dump(mode="json"),
            "rubric": rubric.model_dump(mode="json"),
            "score": score.model_dump(mode="json"),
            "outputs": relative,
        }
        if dry_run:
            return result
        assert manifest is not None
        if raw_path.is_file():
            if sha256_file(raw_path) != script_hash:
                raise DistillerError(
                    ErrorCode.RAW_INTEGRITY, f"Candidate raw hash mismatch: {raw_path}"
                )
        else:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(script, raw_path)
        candidate_path = self.project.root / "candidates" / candidate_id / "candidate.json"
        if not candidate_path.is_file():
            atomic_write_json(candidate_path, candidate.model_dump(mode="json"))
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(paths[0], score.model_dump(mode="json"))
        atomic_write_text(
            paths[1],
            _render(
                "content-scoring.md.j2",
                candidate=candidate.model_dump(mode="python"),
                rubric=rubric.model_dump(mode="python"),
                score=score.model_dump(mode="python"),
            ),
        )
        atomic_write_json(paths[2], evidence.model_dump(mode="json"))
        atomic_write_json(paths[3], warnings)
        index_path = _update_knowledge_index(self.project, rubric, rules)
        state = self.project.load_state()
        state.last_scoring_at = datetime.now(UTC)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={"dimensions": len(dimensions), "matched_rules": len(matched_rules)},
            output_files=[
                *relative,
                self.project.relative(candidate_path),
                self.project.relative(index_path),
            ],
            warnings=warnings,
        )
        return result


class PredictionService:
    """Create an immutable account-local quantile prediction after scoring."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def predict(
        self,
        *,
        account_id: str,
        script: Path,
        title: str | None = None,
        topic: str | None = None,
        target_pillar: str | None = None,
        target_metric: str = "performance_score",
        target_age_hours: int | None = None,
        planned_publish_hour: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Score a script and persist a content-addressed prediction that cannot be overwritten."""

        scoring = ScoringService(self.project).score(
            account_id=account_id,
            script=script,
            title=title,
            topic=topic,
            target_pillar=target_pillar,
            target_metric=target_metric,
            planned_publish_hour=planned_publish_hour,
            dry_run=dry_run,
        )
        candidate = ContentCandidate.model_validate(scoring["candidate"])
        score = ScoreResult.model_validate(scoring["score"])
        dataset = load_account_dataset(self.project, account_id)
        config = load_config(self.project.config_path)
        age_hours = target_age_hours or config.scoring.default_target_snapshot_age_hours
        videos_by_id = {record.video.video_id: record.video for record in dataset.records}
        all_snapshots = [
            item
            for item in read_models(
                self.project.normalized_dir / "metric_snapshots.parquet", MetricSnapshot
            )
            if item.video_id in videos_by_id
        ]
        all_derived = [
            item
            for item in read_models(
                self.project.normalized_dir / "derived_metrics.parquet", DerivedMetrics
            )
            if item.video_id in videos_by_id
        ]
        derived_by_snapshot = {(item.video_id, item.snapshot_at): item for item in all_derived}
        snapshots_by_video: dict[str, list[MetricSnapshot]] = {}
        for item in all_snapshots:
            snapshots_by_video.setdefault(item.video_id, []).append(item)
        selected_records: list[AccountVideoRecord] = []
        selected_ages: dict[str, float] = {}
        for video_id, snapshots in sorted(snapshots_by_video.items()):
            video = videos_by_id[video_id]
            published_at = video.published_at or min(item.snapshot_at for item in snapshots)
            selected = min(
                snapshots,
                key=lambda item: (
                    abs(_metric_age(item, published_at) - age_hours),
                    item.snapshot_at,
                    item.record_id,
                ),
            )
            selected_records.append(
                AccountVideoRecord(
                    video=video,
                    metric=selected,
                    derived=derived_by_snapshot.get((video_id, selected.snapshot_at)),
                )
            )
            selected_ages[selected.metric_snapshot_id] = _metric_age(selected, published_at)
        view_zscores = robust_z_scores(
            [
                float(record.metric.views)
                if record.metric is not None and record.metric.views is not None
                else None
                for record in selected_records
            ]
        )
        metric_values: dict[str, list[tuple[float, AccountVideoRecord]]] = {
            metric: [] for metric in config.scoring.prediction_metrics
        }
        eligible_records: list[AccountVideoRecord] = []
        for record, view_zscore in zip(selected_records, view_zscores, strict=True):
            if not _is_eligible(record) or (view_zscore is not None and abs(view_zscore) >= 3.5):
                continue
            eligible_records.append(record)
            assert record.metric is not None
            interactions = [
                record.metric.likes,
                record.metric.comments,
                record.metric.shares,
                record.metric.saves,
            ]
            interaction_total = (
                sum(item for item in interactions if item is not None)
                if all(item is not None for item in interactions)
                else None
            )
            record_metric_values: dict[str, float | None] = {
                "views": float(record.metric.views) if record.metric.views is not None else None,
                "engagement_rate_by_view": (safe_divide(interaction_total, record.metric.views)),
                "performance_score": record.derived.performance_score if record.derived else None,
            }
            for metric in metric_values:
                actual_value = record_metric_values.get(metric)
                if actual_value is not None and actual_value >= 0:
                    metric_values[metric].append((float(actual_value), record))
        warnings = [
            "prediction_is_an_account_local_interval_not_a_guarantee",
            "promoted_and_robust_outlier_records_are_excluded_from_baseline",
        ]
        mismatch_count = sum(
            abs(selected_ages[record.metric.metric_snapshot_id] - age_hours)
            > max(2.0, age_hours * 0.20)
            for record in eligible_records
            if record.metric is not None
        )
        if mismatch_count:
            warnings.append(
                f"baseline_snapshot_age_mismatch:{mismatch_count}/{len(eligible_records)}"
            )
        usable = {
            key: metric_samples
            for key, metric_samples in metric_values.items()
            if len(metric_samples) >= 3
        }
        for key, metric_samples in metric_values.items():
            if len(metric_samples) < 3:
                warnings.append(
                    f"prediction_metric_insufficient_sample:{key}:{len(metric_samples)}"
                )
        if not usable:
            raise DistillerError(
                ErrorCode.INSUFFICIENT_SAMPLE,
                "No prediction metric has at least three eligible account-local observations",
            )
        adjustment = min(1.20, max(0.80, 1.0 + (score.total_score - 50.0) * 0.004))
        intervals = {
            metric: _adjusted_interval([item[0] for item in metric_samples], adjustment)
            for metric, metric_samples in usable.items()
        }
        distillation = _latest_distillation(self.project, account_id)
        rules = _materialize_rules(self.project, distillation, dry_run=dry_run)
        rule_versions = {
            rule_id: rule.version
            for dimension in score.dimension_scores
            for rule_id in dimension.evidence_rule_ids
            for rule in rules
            if rule.rule_id == rule_id
        }
        baseline_fingerprint = {
            metric: [
                (
                    value,
                    record.video.video_id,
                    record.metric.metric_snapshot_id if record.metric else None,
                    selected_ages.get(record.metric.metric_snapshot_id) if record.metric else None,
                )
                for value, record in metric_samples
            ]
            for metric, metric_samples in usable.items()
        }
        prediction_seed = {
            "candidate_id": candidate.candidate_id,
            "score_id": score.score_id,
            "account_id": account_id,
            "target_age_hours": age_hours,
            "metric_values": baseline_fingerprint,
            "rule_versions": rule_versions,
            "version": PREDICTION_VERSION,
        }
        input_hash = sha256_json(prediction_seed)
        prediction_id = stable_id("pred_", input_hash)
        output_dir = self.project.root / "predictions" / prediction_id
        paths = [
            output_dir / "prediction.json",
            output_dir / "report.md",
            output_dir / "evidence-index.json",
            output_dir / "warnings.json",
        ]
        relative = [self.project.relative(path) for path in paths]
        if paths[0].is_file() and not dry_run:
            existing = Prediction.model_validate(read_json(paths[0]))
            if existing.input_hash != input_hash:
                raise DistillerError(
                    ErrorCode.RAW_INTEGRITY,
                    f"Immutable prediction hash mismatch: {prediction_id}",
                )
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "score": scoring["score"],
                "prediction": existing.model_dump(mode="json"),
                "outputs": relative,
            }
        input_hashes = sorted(
            {
                *dataset.input_hashes,
                candidate.script_hash,
                input_hash,
                *(record.metric.raw_hash for record in selected_records if record.metric),
            }
        )
        manifest = (
            None
            if dry_run
            else self.project.begin_run("predict content", input_hashes=input_hashes)
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", prediction_id)
        collector = _EvidenceCollector(prediction_id)
        evidence_ids = []
        for metric, metric_samples in usable.items():
            evidence_ids.append(
                collector.add(
                    label=f"prediction.baseline.{metric}",
                    classification="fact",
                    value={
                        "metric": metric,
                        "eligible_count": len(metric_samples),
                        "target_age_hours": age_hours,
                        "selected_age_hours": [
                            selected_ages[record.metric.metric_snapshot_id]
                            for _, record in metric_samples
                            if record.metric is not None
                        ],
                        "raw_quantiles": {
                            "p25": _quantile([item[0] for item in metric_samples], 0.25),
                            "p50": _quantile([item[0] for item in metric_samples], 0.50),
                            "p75": _quantile([item[0] for item in metric_samples], 0.75),
                        },
                        "score_adjustment_factor": adjustment,
                    },
                    calculation=(
                        "account-local empirical quantiles from each video's snapshot nearest the "
                        "target age, then a bounded score-based adjustment; no cross-platform raw "
                        "comparison"
                    ),
                    sources=[
                        source for _, record in metric_samples for source in _record_sources(record)
                    ],
                )
            )
        sample_size = min(len(item) for item in usable.values())
        validated_rules = sum(
            rule.status == RuleStatus.VALIDATED for rule in rules if rule.rule_id in rule_versions
        )
        confidence = 0.35 if sample_size < 10 else 0.55 if sample_size < 30 else 0.68
        if eligible_records and mismatch_count > len(eligible_records) / 2:
            confidence = max(0.20, confidence - 0.15)
        if validated_rules:
            confidence = min(0.82, confidence + 0.08)
        confidence_band: Literal["low", "medium", "high"] = (
            "low" if confidence < 0.45 else "medium" if confidence < 0.75 else "high"
        )
        strengths = [item.name for item in score.dimension_scores if item.raw_score >= 75]
        weaknesses = [item.name for item in score.dimension_scores if item.raw_score < 60]
        if not validated_rules:
            warnings.append("no_validated_rule_supports_prediction")
        prediction = Prediction(
            prediction_id=prediction_id,
            candidate_id=candidate.candidate_id,
            score_id=score.score_id,
            account_id=account_id,
            rubric_id=score.rubric_id,
            rubric_version=score.rubric_version,
            rule_versions=rule_versions,
            created_at=datetime.now(UTC),
            target_snapshot_age_hours=age_hours,
            target_metrics=intervals,
            confidence=confidence,
            confidence_band=confidence_band,
            positive_factors=strengths,
            negative_factors=weaknesses,
            uncertainties=[
                "platform distribution and external events may change after prediction",
                "future media execution is not observed from script text",
                "candidate and experimental rules are not validated causal effects",
            ],
            assumptions=[
                "historical account-local distribution remains a useful baseline",
                "the published content materially follows the scored script",
                "actual snapshot age is comparable to the prediction target",
            ],
            input_hash=input_hash,
            run_id=run_id,
            evidence_index_path=relative[2],
            warnings_path=relative[3],
            warnings=list(dict.fromkeys(warnings)),
        )
        evidence = ArtifactEvidenceIndex(
            schema_version=CLOSED_LOOP_SCHEMA_VERSION,
            artifact_id=prediction_id,
            account_ids=[account_id],
            run_id=run_id,
            generated_at=prediction.created_at,
            input_hashes=input_hashes,
            items=[collector.items[key] for key in sorted(collector.items)],
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "score": scoring["score"],
            "prediction": prediction.model_dump(mode="json"),
            "outputs": relative,
        }
        if dry_run:
            return result
        assert manifest is not None
        output_dir.mkdir(parents=True, exist_ok=False)
        atomic_write_json(paths[0], prediction.model_dump(mode="json"))
        atomic_write_text(
            paths[1],
            _render(
                "prediction.md.j2",
                candidate=candidate.model_dump(mode="python"),
                score=score.model_dump(mode="python"),
                prediction=prediction.model_dump(mode="python"),
                evidence_ids=evidence_ids,
            ),
        )
        atomic_write_json(paths[2], evidence.model_dump(mode="json"))
        atomic_write_json(paths[3], prediction.warnings)
        state = self.project.load_state()
        state.last_prediction_at = datetime.now(UTC)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={"prediction_metrics": len(intervals), "baseline_sample": sample_size},
            output_files=relative,
            warnings=prediction.warnings,
        )
        return result


def _metric_age(metric: MetricSnapshot, published_at: datetime) -> float:
    if metric.age_hours is not None:
        return float(metric.age_hours)
    return max(0.0, (metric.snapshot_at - published_at).total_seconds() / 3600.0)


class PublicationService:
    """Register a real publication without mutating its linked prediction."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def register(
        self,
        *,
        prediction_id: str,
        video_id: str,
        published_at: datetime | None = None,
        url: str | None = None,
        notes: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        prediction = _load_prediction(self.project, prediction_id)
        candidate = _load_candidate(self.project, prediction.candidate_id)
        videos = read_models(self.project.normalized_dir / "videos.parquet", Video)
        matching = [item for item in videos if item.video_id == video_id]
        if not matching:
            raise DistillerError(ErrorCode.INPUT_MISSING, f"Normalized video not found: {video_id}")
        video = max(
            matching, key=lambda item: (item.published_at or item.ingested_at, item.record_id)
        )
        if video.account_id != prediction.account_id:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID, "Publication video belongs to another account"
            )
        if video.platform != candidate.target_platform:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID, "Publication platform differs from candidate target"
            )
        effective_published_at = published_at or video.published_at
        if effective_published_at is None:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Publication time is required when the normalized video has no published_at",
            )
        if published_at is not None and video.published_at is not None:
            difference = abs((published_at - video.published_at).total_seconds())
            if difference > 1:
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    "--published-at cannot contradict the normalized video published_at",
                )
        if effective_published_at < prediction.created_at:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Publication time cannot be earlier than the immutable prediction",
                details={
                    "prediction_created_at": prediction.created_at.isoformat(),
                    "publication_published_at": effective_published_at.isoformat(),
                },
            )
        config = load_config(self.project.config_path)
        snapshots = [
            item
            for item in read_models(
                self.project.normalized_dir / "metric_snapshots.parquet", MetricSnapshot
            )
            if item.video_id == video_id
        ]
        plan = []
        for age in sorted(set(config.scoring.snapshot_plan_hours)):
            available = any(
                abs(_metric_age(item, effective_published_at) - age) <= max(2, age * 0.15)
                for item in snapshots
            )
            plan.append(
                SnapshotPlanItem(
                    label=cast(Any, _SNAPSHOT_LABELS.get(age, "custom")),
                    target_age_hours=age,
                    status="available" if available else "planned",
                )
            )
        publication_seed = {
            "prediction_id": prediction_id,
            "candidate_id": candidate.candidate_id,
            "video_id": video_id,
            "published_at": effective_published_at.isoformat(),
            "url": url or video.url,
            "notes": notes,
        }
        input_hash = sha256_json(publication_seed)
        publication_id = stable_id("pub_", input_hash)
        path = self.project.root / "publications" / publication_id / "publication.json"
        if path.is_file() and not dry_run:
            existing = Publication.model_validate(read_json(path))
            if existing.input_hash != input_hash:
                raise DistillerError(
                    ErrorCode.RAW_INTEGRITY, f"Publication hash mismatch: {publication_id}"
                )
            return {
                "ok": True,
                "dry_run": False,
                "already_registered": True,
                "publication": existing.model_dump(mode="json"),
                "output": self.project.relative(path),
            }
        manifest = (
            None
            if dry_run
            else self.project.begin_run(
                "register publication", input_hashes=[candidate.script_hash, input_hash]
            )
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", publication_id)
        publication = Publication(
            publication_id=publication_id,
            candidate_id=candidate.candidate_id,
            prediction_id=prediction_id,
            account_id=prediction.account_id,
            video_id=video_id,
            published_at=effective_published_at,
            url=url or video.url,
            platform=video.platform,
            notes=notes,
            snapshot_plan=plan,
            created_at=datetime.now(UTC),
            run_id=run_id,
            input_hash=input_hash,
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_registered": False,
            "publication": publication.model_dump(mode="json"),
            "output": self.project.relative(path),
        }
        if dry_run:
            return result
        assert manifest is not None
        atomic_write_json(path, publication.model_dump(mode="json"))
        state = self.project.load_state()
        state.last_publication_at = datetime.now(UTC)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={
                "snapshot_plans": len(plan),
                "available_snapshots": sum(item.status == "available" for item in plan),
            },
            output_files=[self.project.relative(path)],
        )
        return result


def _next_version(version: str, *, material: bool) -> str:
    try:
        major, minor, patch = [int(item) for item in version.split(".")]
    except (TypeError, ValueError):
        return "1.0.1"
    return f"{major}.{minor + 1}.0" if material else f"{major}.{minor}.{patch + 1}"


class RetroService:
    """Compare an immutable prediction with one normalized metric snapshot."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def run(
        self,
        *,
        publication_id: str,
        snapshot: str = "t3d",
        target_age_hours: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        publication = _load_publication(self.project, publication_id)
        if publication.prediction_id is None:
            raise DistillerError(ErrorCode.INPUT_MISSING, "Publication has no prediction to review")
        prediction = _load_prediction(self.project, publication.prediction_id)
        score = _load_score(self.project, prediction.score_id)
        candidate = _load_candidate(self.project, prediction.candidate_id)
        target_age = target_age_hours or _LABEL_HOURS.get(snapshot)
        if target_age is None:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                f"Unknown snapshot label: {snapshot}; use t1h, t24h, t3d, t7d, "
                "or --target-age-hours",
            )
        metrics = [
            item
            for item in read_models(
                self.project.normalized_dir / "metric_snapshots.parquet", MetricSnapshot
            )
            if item.video_id == publication.video_id
        ]
        if not metrics:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No normalized metric snapshot for publication video: {publication.video_id}",
            )
        selected = min(
            metrics,
            key=lambda item: (
                abs(_metric_age(item, publication.published_at) - target_age),
                item.snapshot_at,
                item.record_id,
            ),
        )
        actual_age = _metric_age(selected, publication.published_at)
        derived_records = [
            item
            for item in read_models(
                self.project.normalized_dir / "derived_metrics.parquet", DerivedMetrics
            )
            if item.video_id == publication.video_id
        ]
        derived = (
            min(
                derived_records,
                key=lambda item: (
                    abs((item.snapshot_at - selected.snapshot_at).total_seconds()),
                    item.record_id,
                ),
            )
            if derived_records
            else None
        )
        actual_interactions = [selected.likes, selected.comments, selected.shares, selected.saves]
        actual_interaction_total = (
            sum(item for item in actual_interactions if item is not None)
            if all(item is not None for item in actual_interactions)
            else None
        )
        actual_values: dict[str, float | None] = {
            "views": float(selected.views) if selected.views is not None else None,
            "engagement_rate_by_view": safe_divide(actual_interaction_total, selected.views),
            "performance_score": derived.performance_score if derived else None,
        }
        errors = []
        for metric, interval in prediction.target_metrics.items():
            actual = actual_values.get(metric)
            if actual is None:
                position: Literal["below_p25", "within_p25_p75", "above_p75", "unknown"] = "unknown"
                absolute = None
                relative_error = None
            else:
                position = (
                    "below_p25"
                    if actual < interval.p25
                    else "above_p75"
                    if actual > interval.p75
                    else "within_p25_p75"
                )
                absolute = actual - interval.p50
                relative_error = absolute / interval.p50 if interval.p50 else None
            errors.append(
                PredictionError(
                    metric=metric,
                    actual=actual,
                    predicted_p50=interval.p50,
                    absolute_error=absolute,
                    relative_error=relative_error,
                    interval_position=position,
                )
            )
        retro_seed = {
            "publication_id": publication_id,
            "prediction_id": prediction.prediction_id,
            "metric_snapshot_id": selected.metric_snapshot_id,
            "target_age": target_age,
            "version": RETRO_VERSION,
        }
        retro_id = stable_id("retro_", sha256_json(retro_seed))
        output_dir = self.project.root / "reports" / "retros" / publication_id / retro_id
        paths = [
            output_dir / "retro.json",
            output_dir / "report.md",
            output_dir / "evidence-index.json",
            output_dir / "warnings.json",
        ]
        relative_paths = [self.project.relative(path) for path in paths]
        if paths[0].is_file() and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "retro": read_json(paths[0]),
                "outputs": relative_paths,
            }
        dataset = load_account_dataset(self.project, publication.account_id)
        input_hashes = sorted(
            {
                *dataset.input_hashes,
                prediction.input_hash,
                publication.input_hash,
                selected.raw_hash,
                *(item.raw_hash for item in derived_records),
            }
        )
        manifest = (
            None
            if dry_run
            else self.project.begin_run("retro publication", input_hashes=input_hashes)
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", retro_id)
        collector = _EvidenceCollector(retro_id)
        sources = [_source("metric_snapshots", selected)]
        if derived is not None:
            sources.append(_source("derived_metrics", derived))
        collector.add(
            label="retro.actual_snapshot",
            classification="fact",
            value={
                "metric_snapshot_id": selected.metric_snapshot_id,
                "target_age_hours": target_age,
                "actual_age_hours": actual_age,
                "actual_values": actual_values,
            },
            calculation="nearest normalized metric snapshot to the requested publication age",
            sources=sources,
        )
        distillation = _latest_distillation(self.project, publication.account_id)
        rules = _materialize_rules(self.project, distillation, dry_run=dry_run)
        rule_by_id = {item.rule_id: item for item in rules}
        matched_rule_ids = sorted(
            {
                rule_id
                for dimension in score.dimension_scores
                for rule_id in dimension.evidence_rule_ids
                if rule_id in rule_by_id
            }
        )
        band = derived.performance_band if derived else None
        snapshot_mismatch = abs(actual_age - target_age) > max(2.0, target_age * 0.20)
        evidence_confounded = bool(
            snapshot_mismatch
            or selected.is_promoted
            or (derived is not None and derived.outlier_flags)
        )
        supported: list[str] = []
        counterexamples: list[str] = []
        inconclusive: list[str] = []
        for rule_id in matched_rule_ids:
            negative = _rule_is_negative(rule_by_id[rule_id])
            if evidence_confounded:
                inconclusive.append(rule_id)
            elif band in {"S", "A"}:
                (counterexamples if negative else supported).append(rule_id)
            elif band in {"C", "D"}:
                (supported if negative else counterexamples).append(rule_id)
            else:
                inconclusive.append(rule_id)
        created_at = datetime.now(UTC)
        proposals: list[RuleChangeProposal] = []
        for rule_id in [] if evidence_confounded else matched_rule_ids:
            rule = rule_by_id[rule_id]
            proposed_status: RuleStatus
            if rule_id in supported:
                action: Literal["strengthen", "weaken", "narrow", "hold", "deprecate"] = (
                    "strengthen"
                )
                proposed_status = (
                    RuleStatus.EXPERIMENTAL if rule.status == RuleStatus.CANDIDATE else rule.status
                )
                rationale = "本次同账号发布结果与规则方向一致；仍需多轮对照和人工审批。"
            elif rule_id in counterexamples:
                action = "narrow"
                proposed_status = rule.status
                rationale = "本次结果构成反例，建议收窄适用范围并保留该反例。"
            else:
                action = "hold"
                proposed_status = rule.status
                rationale = "实际表现处于中间层或缺少可比指标，暂不调整。"
            proposals.append(
                RuleChangeProposal(
                    proposal_id=stable_id("rcp_", retro_id, rule_id, action),
                    rule_id=rule_id,
                    from_version=rule.version,
                    proposed_version=_next_version(
                        rule.version, material=action in {"strengthen", "narrow"}
                    ),
                    action=action,
                    proposed_status=proposed_status,
                    rationale=rationale,
                    created_at=created_at,
                )
            )
        known_relative = [
            abs(item.relative_error) for item in errors if item.relative_error is not None
        ]
        rubric_proposals: list[RubricChangeProposal] = []
        if (
            not evidence_confounded
            and known_relative
            and sum(known_relative) / len(known_relative) > 0.50
        ):
            top = max(score.dimension_scores, key=lambda item: item.weighted_score)
            risk = next(
                item for item in score.dimension_scores if item.dimension_id == "risk_control"
            )
            rubric_proposals = [
                RubricChangeProposal(
                    proposal_id=stable_id("rbp_", retro_id, top.dimension_id, "down"),
                    dimension_id=top.dimension_id,
                    current_weight=top.weight,
                    proposed_weight=max(1.0, top.weight - 1.0),
                    rationale="预测误差较大，建议小幅降低最高贡献维度；待人工审批。",
                ),
                RubricChangeProposal(
                    proposal_id=stable_id("rbp_", retro_id, risk.dimension_id, "up"),
                    dimension_id=risk.dimension_id,
                    current_weight=risk.weight,
                    proposed_weight=min(100.0, risk.weight + 1.0),
                    rationale="与降权配对，暂提议增加风险与不确定性检查；待人工审批。",
                ),
            ]
        config = load_config(self.project.config_path)
        experiments = [
            Experiment(
                experiment_id=stable_id("exp_", retro_id, rule_id),
                account_id=publication.account_id,
                source_retro_id=retro_id,
                hypothesis=rule_by_id[rule_id].instruction,
                variable=rule_by_id[rule_id].required_conditions.get(
                    "feature_value", "rule_feature"
                ),
                control="同内容支柱、相近时长和相近发布条件下不使用该特征",
                target_metric=rule_by_id[rule_id].target_metric,
                minimum_sample_size=config.analysis.min_validated_rule_support,
                created_at=created_at,
            )
            for rule_id in matched_rule_ids[:3]
        ]
        if not experiments:
            weak_area = score.weaknesses[0] if score.weaknesses else "证据完整性"
            experiments.append(
                Experiment(
                    experiment_id=stable_id("exp_", retro_id, "score_weakness"),
                    account_id=publication.account_id,
                    source_retro_id=retro_id,
                    hypothesis=f"修复评分弱项“{weak_area}”后，账号内表现更稳定。",
                    variable=score.weaknesses[0] if score.weaknesses else "evidence_completeness",
                    control="保持原脚本结构和同一内容支柱",
                    target_metric=candidate.target_metric,
                    minimum_sample_size=config.analysis.min_validated_rule_support,
                    created_at=created_at,
                )
            )
        warnings = [
            "retro_association_does_not_prove_causation",
            "rule_and_rubric_changes_are_pending_and_not_applied",
        ]
        if snapshot_mismatch:
            warnings.append(
                f"snapshot_age_outside_target_tolerance:target={target_age}:actual={actual_age:.2f}"
            )
        if selected.is_promoted:
            warnings.append("actual_snapshot_is_promoted")
        if derived and derived.outlier_flags:
            warnings.append("actual_snapshot_is_robust_outlier")
        if evidence_confounded:
            warnings.append("retro_snapshot_not_eligible_for_rule_or_rubric_updates")
        lessons = [
            (
                f"{item.metric} 实际值位于预测区间内。"
                if item.interval_position == "within_p25_p75"
                else f"{item.metric} 实际值位于预测区间之外，需检查脚本执行、平台分发和外部因素。"
                if item.interval_position != "unknown"
                else f"{item.metric} 缺少可比较的实际值。"
            )
            for item in errors
        ]
        retro = Retro(
            retro_id=retro_id,
            publication_id=publication_id,
            prediction_id=prediction.prediction_id,
            account_id=publication.account_id,
            video_id=publication.video_id,
            evaluated_snapshot_at=selected.snapshot_at,
            target_snapshot_label=snapshot,
            actual_metrics=RetroActualMetrics(
                metric_snapshot_id=selected.metric_snapshot_id,
                snapshot_at=selected.snapshot_at,
                age_hours=actual_age,
                metrics={key: actual_values.get(key) for key in prediction.target_metrics},
                performance_band=band,
            ),
            prediction_errors=errors,
            supported_rule_ids=supported,
            counterexample_rule_ids=counterexamples,
            inconclusive_rule_ids=inconclusive,
            external_factors=[
                *("promoted_traffic" for _ in [0] if selected.is_promoted),
                *("robust_outlier" for _ in [0] if derived and derived.outlier_flags),
                "unobserved_platform_distribution_or_external_events",
            ],
            lessons=lessons,
            rule_change_proposals=proposals,
            rubric_change_proposals=rubric_proposals,
            next_experiments=experiments,
            created_at=created_at,
            run_id=run_id,
            evidence_index_path=relative_paths[2],
            warnings_path=relative_paths[3],
            warnings=warnings,
        )
        evidence = ArtifactEvidenceIndex(
            schema_version=CLOSED_LOOP_SCHEMA_VERSION,
            artifact_id=retro_id,
            account_ids=[publication.account_id],
            run_id=run_id,
            generated_at=created_at,
            input_hashes=input_hashes,
            items=[collector.items[key] for key in sorted(collector.items)],
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "retro": retro.model_dump(mode="json"),
            "outputs": relative_paths,
        }
        if dry_run:
            return result
        assert manifest is not None
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(paths[0], retro.model_dump(mode="json"))
        atomic_write_text(
            paths[1],
            _render(
                "retro.md.j2",
                publication=publication.model_dump(mode="python"),
                prediction=prediction.model_dump(mode="python"),
                retro=retro.model_dump(mode="python"),
            ),
        )
        atomic_write_json(paths[2], evidence.model_dump(mode="json"))
        atomic_write_json(paths[3], warnings)
        review_dir = self.project.root / "knowledge-base" / "reviews" / publication_id / retro_id
        atomic_write_json(review_dir / "retro.json", retro.model_dump(mode="json"))
        atomic_write_text(review_dir / "review.md", paths[1].read_text(encoding="utf-8"))
        experiment_files = []
        for experiment in experiments:
            experiment_path = (
                self.project.root
                / "knowledge-base"
                / "experiments"
                / f"{experiment.experiment_id}.json"
            )
            atomic_write_json(experiment_path, experiment.model_dump(mode="json"))
            experiment_files.append(self.project.relative(experiment_path))
        state = self.project.load_state()
        state.last_retro_at = datetime.now(UTC)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={
                "prediction_errors": len(errors),
                "rule_proposals": len(proposals),
                "rubric_proposals": len(rubric_proposals),
                "experiments": len(experiments),
            },
            output_files=[
                *relative_paths,
                self.project.relative(review_dir / "retro.json"),
                self.project.relative(review_dir / "review.md"),
                *experiment_files,
            ],
            warnings=warnings,
        )
        return result
