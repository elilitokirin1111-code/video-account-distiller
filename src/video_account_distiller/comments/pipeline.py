"""Privacy-preserving comment intent and need-cluster analysis."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, StrictUndefined

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features.prompts import (
    COMMENT_INTENT_PROMPT_VERSION,
    render_prompt,
)
from video_account_distiller.features.providers import (
    LlamaCppTextProvider,
    ModelSchemaFailure,
    OllamaTextProvider,
    StructuredFileProvider,
    TextModelProvider,
)
from video_account_distiller.models import (
    ArtifactEvidenceIndex,
    Comment,
    CommentAnalysis,
    CommentIntent,
    CommentNeedCluster,
    CommentSentiment,
    CommentSignal,
    CommentSignalAnnotation,
    EvidenceItem,
    EvidenceSource,
    ModelTaskTrace,
    Video,
)
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json

ANALYSIS_VERSION = "1.0.0"
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
HANDLE_PATTERN = re.compile(r"(?<!\w)@[\w.-]{2,}", re.UNICODE)
WECHAT_PATTERN = re.compile(
    r"(?:微信|vx|v信|wechat)\s*[:：]?\s*[A-Za-z][A-Za-z0-9_-]{5,}", re.IGNORECASE
)

INTENT_NAMES = {
    CommentIntent.SUPPORT: "支持与认可",
    CommentIntent.OPPOSE: "反对与质疑",
    CommentIntent.FOLLOW_UP: "追问与答疑",
    CommentIntent.REQUEST_TUTORIAL: "教程需求",
    CommentIntent.REQUEST_LINK: "链接与入口需求",
    CommentIntent.PURCHASE_INTENT: "购买与预订意图",
    CommentIntent.SHARE_EXPERIENCE: "用户经验分享",
    CommentIntent.QUESTION_EVIDENCE: "证据质疑",
    CommentIntent.PRICE_OBJECTION: "价格异议",
    CommentIntent.FEATURE_OBJECTION: "功能异议",
    CommentIntent.IDENTITY_SIGNAL: "身份认同",
    CommentIntent.EMOTIONAL_EXPRESSION: "情绪表达",
    CommentIntent.JOKE: "玩梗互动",
    CommentIntent.IRRELEVANT: "无关内容",
    CommentIntent.SPAM_OR_AD: "疑似广告或机器人",
    CommentIntent.UNKNOWN: "未识别需求",
}
INTENT_PRIORITY = (
    CommentIntent.SPAM_OR_AD,
    CommentIntent.PURCHASE_INTENT,
    CommentIntent.PRICE_OBJECTION,
    CommentIntent.FEATURE_OBJECTION,
    CommentIntent.REQUEST_TUTORIAL,
    CommentIntent.REQUEST_LINK,
    CommentIntent.QUESTION_EVIDENCE,
    CommentIntent.FOLLOW_UP,
    CommentIntent.OPPOSE,
    CommentIntent.SHARE_EXPERIENCE,
    CommentIntent.IDENTITY_SIGNAL,
    CommentIntent.SUPPORT,
    CommentIntent.EMOTIONAL_EXPRESSION,
    CommentIntent.JOKE,
    CommentIntent.IRRELEVANT,
    CommentIntent.UNKNOWN,
)


def redact_comment_text(text: str) -> tuple[str, int]:
    """Redact common direct identifiers without changing the immutable source comment."""

    cleaned = " ".join(text.split())
    count = 0
    for pattern, replacement in (
        (URL_PATTERN, "[REDACTED_URL]"),
        (EMAIL_PATTERN, "[REDACTED_EMAIL]"),
        (PHONE_PATTERN, "[REDACTED_PHONE]"),
        (WECHAT_PATTERN, "[REDACTED_CONTACT]"),
        (HANDLE_PATTERN, "@[REDACTED]"),
    ):
        cleaned, matches = pattern.subn(replacement, cleaned)
        count += matches
    return cleaned, count


def _contains(text: str, values: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(value.casefold() in lowered for value in values)


def _fallback_annotation(text: str) -> CommentSignalAnnotation:
    labels: list[CommentIntent] = []
    pain_points: list[str] = []
    objections: list[str] = []
    opportunities: list[str] = []

    if _contains(text, ("加微信", "加vx", "兼职", "代理", "推广", "私聊赚钱")):
        labels.append(CommentIntent.SPAM_OR_AD)
    if _contains(text, ("多少钱", "价格", "预订", "订房", "怎么买", "下单", "套餐")):
        labels.append(CommentIntent.PURCHASE_INTENT)
        opportunities.append("补充价格、权益、预订入口和适用条件")
    if _contains(text, ("太贵", "好贵", "价格高", "不值")):
        labels.append(CommentIntent.PRICE_OBJECTION)
        pain_points.append("价格与价值感不匹配")
        objections.append("价格异议")
    if _contains(text, ("没有", "不支持", "不方便", "不能用", "不好用")):
        labels.append(CommentIntent.FEATURE_OBJECTION)
        pain_points.append("功能或服务能力不足")
        objections.append("功能异议")
    if _contains(text, ("教程", "教一下", "怎么做", "做一期", "步骤")):
        labels.append(CommentIntent.REQUEST_TUTORIAL)
        opportunities.append("制作步骤型教程或操作演示")
    if _contains(text, ("链接", "地址", "入口", "哪里订", "在哪买")):
        labels.append(CommentIntent.REQUEST_LINK)
        opportunities.append("明确展示链接、地址或预订入口")
    if _contains(text, ("证据", "依据", "真的吗", "凭什么", "数据呢")):
        labels.append(CommentIntent.QUESTION_EVIDENCE)
        objections.append("证据充分性")
        opportunities.append("补充可核验依据、边界和真实案例")
    is_question = any(mark in text for mark in ("?", "？")) or _contains(
        text, ("吗", "怎么", "如何", "几点", "能不能", "有没有", "为什么")
    )
    if is_question:
        labels.append(CommentIntent.FOLLOW_UP)
        opportunities.append("围绕高频追问制作答疑内容")
    if _contains(text, ("我住过", "我用过", "我遇到", "我的经验", "我觉得")):
        labels.append(CommentIntent.SHARE_EXPERIENCE)
    if _contains(text, ("不对", "不认同", "假的", "骗人", "避雷", "坑")):
        labels.append(CommentIntent.OPPOSE)
    if _contains(text, ("我也是", "同感", "同款", "本地人", "同行")):
        labels.append(CommentIntent.IDENTITY_SIGNAL)
    if _contains(text, ("清楚", "有用", "不错", "喜欢", "学到了", "靠谱", "赞")):
        labels.append(CommentIntent.SUPPORT)
    if _contains(text, ("哈哈", "笑死", "气死", "无语", "感动")):
        labels.append(CommentIntent.EMOTIONAL_EXPRESSION)
    if _contains(text, ("哈哈", "笑死", "这个梗")):
        labels.append(CommentIntent.JOKE)
    if not labels:
        labels.append(CommentIntent.UNKNOWN)

    unique_labels = list(dict.fromkeys(labels))
    opposed = any(
        label
        in {
            CommentIntent.OPPOSE,
            CommentIntent.PRICE_OBJECTION,
            CommentIntent.FEATURE_OBJECTION,
        }
        for label in unique_labels
    )
    supportive = CommentIntent.SUPPORT in unique_labels
    sentiment = (
        CommentSentiment.MIXED
        if opposed and supportive
        else CommentSentiment.OPPOSED
        if opposed
        else CommentSentiment.SUPPORTIVE
        if supportive
        else CommentSentiment.NEUTRAL
    )
    return CommentSignalAnnotation(
        sentiment=sentiment,
        intent_labels=unique_labels,
        pain_points=list(dict.fromkeys(pain_points)),
        questions=[text[:240]] if is_question else [],
        objections=list(dict.fromkeys(objections)),
        purchase_intent=(0.7 if CommentIntent.PURCHASE_INTENT in unique_labels else None),
        identity_signal=(text[:120] if CommentIntent.IDENTITY_SIGNAL in unique_labels else None),
        content_opportunities=list(dict.fromkeys(opportunities)),
        spam_probability=(0.9 if CommentIntent.SPAM_OR_AD in unique_labels else 0.05),
        confidence=0.45,
        unknowns=["model unavailable; labels use deterministic keyword fallback"],
    )


def _selected_comments(comments: list[Comment], limit: int) -> tuple[list[Comment], bool]:
    grouped: dict[str, list[Comment]] = defaultdict(list)
    for comment in comments:
        grouped[comment.video_id].append(comment)
    for values in grouped.values():
        values.sort(
            key=lambda item: (
                not bool(item.is_pinned),
                -(item.like_count or 0),
                item.created_at is None,
                item.created_at or datetime.min.replace(tzinfo=UTC),
                item.comment_id,
            )
        )
    selected: list[Comment] = []
    video_ids = sorted(grouped)
    cursor = 0
    while len(selected) < limit:
        added = False
        for video_id in video_ids:
            values = grouped[video_id]
            if cursor < len(values):
                selected.append(values[cursor])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        cursor += 1
    return selected, len(selected) < len(comments)


def _primary_intent(labels: list[CommentIntent]) -> CommentIntent:
    return next((value for value in INTENT_PRIORITY if value in labels), CommentIntent.UNKNOWN)


def _source(comment: Comment) -> EvidenceSource:
    return EvidenceSource(
        table="comments",
        record_id=comment.record_id,
        source_record_id=comment.source_record_id,
        raw_hash=comment.raw_hash,
        run_id=comment.run_id,
    )


class CommentAnalysisService:
    """Analyze normalized comments without exposing author identifiers."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def analyze(
        self,
        *,
        account_id: str,
        model_output: Path | None = None,
        provider: TextModelProvider | None = None,
        max_attempts: int | None = None,
        strict_model: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Label comment intent and aggregate account-local need clusters."""

        videos = read_models(self.project.normalized_dir / "videos.parquet", Video)
        video_ids = {video.video_id for video in videos if video.account_id == account_id}
        if not video_ids:
            raise DistillerError(
                ErrorCode.INPUT_MISSING, f"No normalized videos found for account: {account_id}"
            )
        comments = [
            item
            for item in read_models(self.project.normalized_dir / "comments.parquet", Comment)
            if item.video_id in video_ids and item.text.strip()
        ]
        if not comments:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No normalized comments found for account: {account_id}",
            )
        if provider is not None and model_output is not None:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID, "Pass either provider or model_output, not both"
            )
        config = load_config(self.project.config_path)
        selected, partial = _selected_comments(comments, config.analysis.max_comments_per_analysis)
        file_provider = StructuredFileProvider(model_output) if model_output else None
        selected_provider = provider or file_provider
        if selected_provider is None and config.models.text_provider == "ollama":
            selected_provider = OllamaTextProvider(
                base_url=config.models.ollama_base_url,
                timeout_seconds=config.models.vision_timeout_seconds,
            )
        elif selected_provider is None and config.models.text_provider == "llamacpp":
            selected_provider = LlamaCppTextProvider(
                model=(
                    config.models.llamacpp_text_model
                    or config.models.llamacpp_model
                    or config.models.vision_model
                    or "local"
                ),
                base_url=config.models.llamacpp_text_base_url,
                timeout_seconds=config.models.vision_timeout_seconds,
                api_key=config.models.llamacpp_api_key,
            )
        attempts_limit = max_attempts or config.models.max_schema_attempts
        effective_strict = strict_model or not config.models.allow_degraded_analysis
        generated_at = datetime.now(UTC)
        signals: list[CommentSignal] = []
        comments_by_id = {item.comment_id: item for item in selected}

        for comment in selected:
            redacted, redaction_count = redact_comment_text(comment.text)
            prompt = render_prompt(
                "comment-intent.md",
                comment_json={
                    "text": redacted,
                    "like_count": comment.like_count,
                    "is_creator_reply": comment.is_creator_reply,
                    "is_pinned": comment.is_pinned,
                    "language": comment.language,
                },
                schema_json=CommentSignalAnnotation.model_json_schema(),
            )
            errors: list[str] = []
            annotation: CommentSignalAnnotation | None = None
            used_attempts = 0
            provider_succeeded = False
            if selected_provider is not None:
                for attempt in range(1, attempts_limit + 1):
                    used_attempts = attempt
                    try:
                        annotation = selected_provider.generate_structured(
                            prompt, CommentSignalAnnotation, temperature=0.0
                        )
                        provider_succeeded = True
                        break
                    except (ModelSchemaFailure, ValueError, TypeError) as exc:
                        errors.append(str(exc)[:500])
            if annotation is None:
                if effective_strict:
                    code = (
                        ErrorCode.MODEL_UNAVAILABLE
                        if selected_provider is None
                        else ErrorCode.MODEL_SCHEMA_INVALID
                    )
                    raise DistillerError(
                        code,
                        f"Comment intent output unavailable for {comment.comment_id}",
                        details={"attempts": used_attempts, "errors": errors},
                    )
                annotation = _fallback_annotation(redacted)
                errors.append(
                    "model provider unavailable; deterministic fallback used"
                    if selected_provider is None
                    else "model candidates exhausted; deterministic fallback used"
                )
            status: Literal["success", "degraded"] = "success" if provider_succeeded else "degraded"
            trace = ModelTaskTrace(
                task="comment_intent",
                prompt_version=COMMENT_INTENT_PROMPT_VERSION,
                prompt_hash=sha256_json({"prompt": prompt}),
                provider=(selected_provider.provider_name if selected_provider else "none"),
                model=(selected_provider.model_name if selected_provider else "none"),
                attempts=used_attempts,
                status=status,
                errors=errors,
            )
            signal_id = stable_id(
                "cms_",
                comment.comment_id,
                ANALYSIS_VERSION,
                sha256_json(annotation.model_dump(mode="json")),
            )
            signals.append(
                CommentSignal(
                    comment_signal_id=signal_id,
                    comment_id=comment.comment_id,
                    video_id=comment.video_id,
                    redacted_text=redacted,
                    redaction_count=redaction_count,
                    annotation=annotation,
                    task_trace=trace,
                    evidence_id=stable_id("evi_", signal_id, "comment"),
                )
            )

        provider_hash = file_provider.input_hash if file_provider else None
        input_hashes = sorted(
            {
                *(comment.raw_hash for comment in selected),
                *([provider_hash] if provider_hash else []),
            }
        )
        analysis_id = stable_id(
            "cma_",
            account_id,
            ANALYSIS_VERSION,
            sha256_json([signal.model_dump(mode="json") for signal in signals]),
            *input_hashes,
        )
        output_dir = self.project.root / "analyses" / "comments" / account_id / analysis_id
        paths = [
            output_dir / "analysis.json",
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
                "analysis": read_json(paths[0]),
                "outputs": relative,
            }
        manifest = (
            None
            if dry_run
            else self.project.begin_run("analyze comments", input_hashes=input_hashes)
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", analysis_id)
        evidence_items = [
            EvidenceItem(
                evidence_id=signal.evidence_id,
                label=f"comment.signal.{signal.comment_id}",
                classification="semantic_annotation",
                value={
                    "redacted_text": signal.redacted_text,
                    "annotation": signal.annotation.model_dump(mode="json"),
                },
                calculation="schema-validated comment annotation over a redacted text copy",
                sources=[_source(comments_by_id[signal.comment_id])],
            )
            for signal in signals
        ]
        grouped: dict[CommentIntent, list[CommentSignal]] = defaultdict(list)
        for signal in signals:
            grouped[_primary_intent(signal.annotation.intent_labels)].append(signal)
        clusters: list[CommentNeedCluster] = []
        for intent in sorted(grouped, key=lambda item: item.value):
            values = grouped[intent]
            comment_ids = sorted(signal.comment_id for signal in values)
            cluster_id = stable_id("cnc_", account_id, intent.value, *comment_ids)
            source_comments = [comments_by_id[item] for item in comment_ids]
            likes = sum(item.like_count or 0 for item in source_comments)
            intensity = min(1.0, len(values) / len(signals) + min(likes, 1000) / 10000)
            evidence_id = stable_id("evi_", analysis_id, "cluster", intent.value)
            cluster = CommentNeedCluster(
                cluster_id=cluster_id,
                name=INTENT_NAMES[intent],
                primary_intent=intent,
                description=f"按主意图聚合的 {INTENT_NAMES[intent]} 评论簇",
                frequency=len(values),
                intensity=intensity,
                comment_ids=comment_ids,
                video_ids=sorted({signal.video_id for signal in values}),
                representative_comment_ids=[
                    item.comment_id
                    for item in sorted(
                        source_comments,
                        key=lambda item: (-(item.like_count or 0), item.comment_id),
                    )[:3]
                ],
                pain_points=sorted(
                    {item for signal in values for item in signal.annotation.pain_points}
                ),
                objections=sorted(
                    {item for signal in values for item in signal.annotation.objections}
                ),
                content_opportunities=sorted(
                    {item for signal in values for item in signal.annotation.content_opportunities}
                ),
                evidence_id=evidence_id,
            )
            clusters.append(cluster)
            evidence_items.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    label=f"comment.cluster.{intent.value}",
                    classification="statistical_association",
                    value=cluster.model_dump(mode="json"),
                    calculation="deterministic grouping by highest-priority intent label",
                    sources=[_source(item) for item in source_comments],
                )
            )

        warnings = [
            "comment_users_are_not_all_viewers",
            "platform_ranking_and_pinning_can_bias_visible_comments",
            "deleted_or_unexported_comments_can_bias_the_sample",
        ]
        if partial:
            warnings.append("comment_sample_partial")
        if any(signal.task_trace.status == "degraded" for signal in signals):
            warnings.append("comment_labels_include_low_confidence_fallbacks")
        if any(signal.redaction_count for signal in signals):
            warnings.append("direct_identifiers_redacted_from_analysis_copy")
        analysis = CommentAnalysis(
            analysis_id=analysis_id,
            account_id=account_id,
            generated_at=generated_at,
            run_id=run_id,
            status=(
                "degraded"
                if any(signal.task_trace.status == "degraded" for signal in signals)
                else "complete"
            ),
            comment_count=len(signals),
            video_count=len({signal.video_id for signal in signals}),
            signals=signals,
            need_clusters=clusters,
            input_hashes=input_hashes,
            evidence_index_path=relative[2],
            warnings_path=relative[3],
            warnings=warnings,
        )
        evidence = ArtifactEvidenceIndex(
            artifact_id=analysis_id,
            account_ids=[account_id],
            run_id=run_id,
            generated_at=generated_at,
            input_hashes=input_hashes,
            items=evidence_items,
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "analysis": analysis.model_dump(mode="json"),
            "outputs": relative,
        }
        if dry_run:
            return result
        assert manifest is not None
        if file_provider is not None:
            raw_path = (
                self.project.root / "raw" / "model-outputs" / f"{file_provider.input_hash}.json"
            )
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            # Atomically copy the model-output file: try an exclusive open first
            # (O_EXCL on Unix, CREATE_NEW on Windows) to avoid TOCTOU between
            # the existence check and the copy.  If the file already exists we
            # trust the content-addressed hash to validate it.
            try:
                with open(raw_path, "xb") as dst:
                    dst.write(file_provider.path.read_bytes())
            except FileExistsError:
                pass
            if sha256_file(raw_path) != file_provider.input_hash:
                raise DistillerError(
                    ErrorCode.RAW_INTEGRITY, f"Model output raw copy hash mismatch: {raw_path}"
                )
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(paths[0], analysis.model_dump(mode="json"))
        atomic_write_json(paths[2], evidence.model_dump(mode="json"))
        atomic_write_json(paths[3], warnings)
        template_path = (
            Path(__file__).resolve().parents[1] / "reports" / "templates" / "comment-analysis.md.j2"
        )
        template = Environment(undefined=StrictUndefined, autoescape=False).from_string(
            template_path.read_text(encoding="utf-8")
        )
        atomic_write_text(paths[1], template.render(analysis=analysis.model_dump(mode="python")))
        state = self.project.load_state()
        state.last_comment_analysis_at = datetime.now(UTC)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={
                "comments": len(signals),
                "need_clusters": len(clusters),
                "redactions": sum(signal.redaction_count for signal in signals),
            },
            output_files=relative,
            warnings=warnings,
        )
        return result
