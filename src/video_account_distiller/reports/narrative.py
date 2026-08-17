# ruff: noqa: E501
"""Narrative long-form account analysis report (Chinese, human-readable).

Aggregates the latest distillation, health report, media enrichment, video
analyses, and comment analysis into a deterministic Markdown document meant
for operators who want to imitate the distilled account: positioning, content
strategy, production craft, heat rules, comment needs, and an action list.

Everything is rendered from persisted artifacts - no model calls - so the
report is fast, reproducible, and evidence-backed.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from video_account_distiller.distillation.pipeline import (
    _latest_comment_analysis,
    _latest_distillation,
    _latest_video_analyses,
    _media_features,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    CommentAnalysis,
    DerivedMetrics,
    MediaFeatureRecord,
    MetricSnapshot,
    SingleVideoAnalysis,
    Video,
)
from video_account_distiller.sampling.dataset import load_account_dataset
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import read_json

NARRATIVE_VERSION = "0.7.2"

ZH_MAP = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "unknown": "未知",
    "observed_fact": "已观察事实",
    "statistical_association": "统计关联",
    "hypothesis": "假设",
    "recommendation": "建议",
    "pain_point": "痛点",
    "question_challenge": "提问挑战",
    "loss_aversion": "损失厌恶",
    "curiosity": "好奇",
    "promise": "承诺",
    "comment_trigger": "评论触发",
    "feature_objection": "功能异议",
    "follow_up": "追问与答疑",
    "number_list": "数字清单",
    "topic": "主题方向",
    "hook": "钩子",
    "structure": "内容结构",
    "persona": "人设",
    "cta": "行动号召",
    "posting_time": "发布时间",
    "conversion": "转化规律",
    "failure": "失败规律",
    "提问_evidence": "证据质疑",
    "evidence": "证据",
    "association_not_causation": "关联不代表因果",
    "small_sample": "样本量较小",
    "not_experimental": "未经实验验证",
    "low_replicability": "可复现性低",
    "no_observed_counterexample_in_current_sample": "当前样本中未见反例",
    "Entertainment": "娱乐",
    "entertainment": "娱乐",
    "culture": "文化",
    "content_creation": "内容创作",
    "education": "教育",
    "lifestyle": "生活方式",
    "travel": "旅行",
    "food": "美食",
    "sports": "体育",
    "fashion": "时尚",
    "music": "音乐",
    "gaming": "游戏",
    "technology": "科技",
    "business": "商业",
    "comedy": "喜剧",
    "drama": "剧情",
    "Brand Engagement": "品牌互动",
    "Dialogue-based interaction": "对话式互动",
    "Emotional Engagement": "情感互动",
    "Engagement through repetition": "重复记忆点",
    "Exam stress": "考试压力",
    "Humor": "幽默",
    "International students": "留学生群体",
    "Narrative Interest": "叙事吸引力",
    "Relatability": "强共鸣感",
    "content_creator": "内容创作者",
    "film_enthusiast": "影视爱好者",
    "oppose": "反对型评论",
    "purchase_intent": "购买意向",
    "request_tutorial": "求教程",
    "emotional_expression": "情绪表达",
    "joke": "玩梗互动",
    "question_evidence": "证据质疑",
    "share_experience": "经验分享",
    "suggestion": "改进建议",
    "knowledge_contribution": "专业信息补充",
    "support": "支持认可",
    "story_suspense": "悬念钩子",
    "morning": "上午发布",
    "performance_score": "表现分",
    "public_interaction_proxy": "账号内公开互动代理层级",
    "account_stage": "账号阶段",
    "commercial_conversion_path": "商业化转化路径",
    "small_video_sample_no_strong_account_rule": "样本量较小，暂不构成强账号规律",
    "comment_users_are_not_all_viewers": "评论用户不能代表全部观众",
    "platform_ranking_and_pinning_can_bias_visible_comments": "平台排序与置顶可能使可见评论有偏",
    "deleted_or_unexported_comments_can_bias_the_sample": "已删除或未导出的评论可能使样本有偏",
    "direct_identifiers_redacted_from_analysis_copy": "分析副本已对直接标识信息脱敏",
    "comment_labels_include_low_confidence_fallbacks": "评论标签来自低置信度降级识别，需抽样复核",
    "comment_unknown_intent_rate_high": "评论意图未识别比例偏高，需补充模型或人工复核",
    "semantic_unknown_values_excluded_from_strategy": "未识别的视频语义已排除在策略结论之外",
    "comment_unknown_clusters_excluded_from_strategy": "未识别评论簇已排除在策略结论之外",
    "patterns_are_observations_or_associations_not_causal_rules": "模式属于观察或统计关联，不代表因果",
    "no_phase4_pattern_is_a_level4_validated_rule": "尚无达到最高验证等级的模式",
    "patterns_use_public_interaction_proxy_not_view_efficiency": (
        "缺少播放量时，模式使用账号内公开互动排序；它不是播放效率或因果结论"
    ),
    "pattern_performance_basis_unavailable": "缺少足够公开互动字段，暂不能形成强弱样本对照",
    "views_unavailable_proxy_is_not_view_efficiency": "公开互动代理不等于播放效率",
    "publication_age_not_normalized": "公开互动代理未消除作品发布时间差异",
    "high_performance": "高表现",
    "low_performance": "低表现",
    "account-local direction=高表现": "账号内方向为高表现",
    "account-local direction=低表现": "账号内方向为低表现",
}


def _zh(value: Any) -> str:
    return ZH_MAP.get(str(value), str(value))


def _pattern_name_zh(value: Any) -> str:
    text = str(value)
    for key, translated in sorted(ZH_MAP.items(), key=lambda item: -len(item[0])):
        if not key:
            continue
        if re.fullmatch(r"[A-Za-z0-9_]+", key):
            text = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])",
                translated,
                text,
                flags=re.IGNORECASE,
            )
        else:
            text = text.replace(key, translated)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"([\u4e00-\u9fff]) ([的与和])", r"\1\2", text)
    return text


def _translate_known(value: Any) -> str:
    return _pattern_name_zh(value)


def _statement_zh(value: str) -> str:
    translated = _translate_known(value)
    translated = re.sub(r"([\u4e00-\u9fff]{2,6})(?:、\1)+", r"\1", translated)
    return translated


def _opportunity_preview(items: list[str]) -> str:
    """Keep at most three Chinese opportunity hints for the human report."""

    def _has_chinese(value: str) -> bool:
        chinese_count = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
        return chinese_count >= 3 and chinese_count / max(len(value), 1) >= 0.2

    kept = [item for item in items if _has_chinese(item)]
    if not kept:
        return "已识别机会点，详见 AI 学习沉淀知识库"
    preview = "；".join(kept[:3])
    if len(kept) > 3:
        preview += f"（共 {len(kept)} 条）"
    return preview


def _median(values: list[float | int | None]) -> float | None:
    present = sorted(float(value) for value in values if value is not None)
    if not present:
        return None
    middle = len(present) // 2
    if len(present) % 2:
        return present[middle]
    return (present[middle - 1] + present[middle]) / 2


def _counter_top(values: list[Any], limit: int = 3) -> list[tuple[str, int]]:
    unavailable = {"", "unknown", "未知", "none", "null", "n/a"}
    counts = Counter(
        str(value)
        for value in values
        if value is not None and str(value).strip().casefold() not in unavailable
    )
    return counts.most_common(limit)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(numerator / denominator, 2)


def _number(value: float | int | None) -> str:
    if value is None:
        return "暂缺"
    return f"{value:,.0f}"


def _is_unknown_label(value: Any) -> bool:
    normalized = str(value or "").strip().casefold()
    return not normalized or any(
        token in normalized for token in ("unknown", "unclassified", "未识别", "未知")
    )


def _effect_summary_zh(pattern: dict[str, Any]) -> str:
    text = str(pattern.get("effect_summary") or "")
    text = re.sub(r"eligible=(\d+)", r"可比样本 \1 条", text)
    text = re.sub(r"high=(\d+)", r"高表现 \1 条", text)
    text = re.sub(r"low=(\d+)", r"低表现 \1 条", text)
    text = text.replace("account-local direction=高表现", "账号内方向为高表现")
    text = text.replace("account-local direction=低表现", "账号内方向为低表现")
    text = text.replace(";", "；").replace("； ", "；").strip()
    return text


def _latest_health_report(project: ProjectLayout, account_id: str) -> dict[str, Any] | None:
    """Load the newest account-health report JSON for the account."""
    report_dir = project.root / "reports" / "accounts" / account_id
    if not report_dir.is_dir():
        return None
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for path in sorted(report_dir.glob("rpt_*/report.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        generated_at = payload.get("generated_at")
        if isinstance(generated_at, str):
            try:
                stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            except ValueError:
                stamp = datetime.min.replace(tzinfo=UTC)
        else:
            stamp = datetime.min.replace(tzinfo=UTC)
        candidates.append((stamp, payload))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _latest_enrichment(project: ProjectLayout, account_id: str) -> dict[str, Any] | None:
    """Load the newest media-enrichment summary for the account."""
    base = project.root / "analyses" / "accounts" / account_id / "media-enrichments"
    if not base.is_dir():
        return None
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for path in sorted(base.glob("ame_*/enrichment.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        stamp = datetime.min.replace(tzinfo=UTC)
        raw = payload.get("generated_at")
        if isinstance(raw, str):
            try:
                stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        candidates.append((stamp, payload))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _video_rows(
    project: ProjectLayout,
    account_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Combine snapshots, derived metrics, analyses, and media per video."""
    dataset = load_account_dataset(project, account_id)
    video_ids = {record.video.video_id for record in dataset.records}
    analyses = _latest_video_analyses(project, video_ids)
    media = {item.video_id: item for item in _media_features(project, video_ids)}
    rows: list[dict[str, Any]] = []
    for record in dataset.records:
        video: Video = record.video
        metric: MetricSnapshot | None = record.metric
        derived: DerivedMetrics | None = record.derived
        analysis: SingleVideoAnalysis | None = analyses.get(video.video_id)
        media_feature: MediaFeatureRecord | None = media.get(video.video_id)
        title = video.title or "(无标题)"
        hashtags = list(video.hashtags or [])
        missing_tags = [f"#{tag}" for tag in hashtags if f"#{tag}" not in title]
        if missing_tags:
            extra_tags_display = " ".join(missing_tags)
        elif hashtags:
            extra_tags_display = "标签见标题"
        else:
            extra_tags_display = "无标签"
        semantics = (
            analysis.blind_analysis.semantics.model_dump(mode="json")
            if analysis is not None
            else {}
        )
        rows.append(
            {
                "video_id": video.video_id,
                "short_id": video.video_id[-8:],
                "title": title,
                "hashtags": hashtags,
                "content_type": video.content_type,
                "tags_text": " ".join(f"#{tag}" for tag in hashtags),
                "extra_tags": extra_tags_display,
                "extra_tags_display": extra_tags_display,
                "published_at": (video.published_at.isoformat() if video.published_at else None),
                "duration_seconds": video.duration_seconds,
                "views": metric.views if metric else None,
                "likes": metric.likes if metric else None,
                "comments": metric.comments if metric else None,
                "shares": metric.shares if metric else None,
                "saves": metric.saves if metric else None,
                "score": derived.performance_score if derived else None,
                "band": derived.performance_band if derived else None,
                "pillar": semantics.get("primary_pillar"),
                "hook_type": (semantics.get("hook") or {}).get("primary_type"),
                "analysis_status": analysis.status if analysis else None,
                "avg_shot_ms": media_feature.average_shot_duration_ms if media_feature else None,
            }
        )
    rows.sort(key=lambda item: (item["score"] is None, -(item["score"] or 0.0)))
    return rows, dataset.account.model_dump(mode="json")


def _bands_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        band = row["band"]
        if band:
            summary[band] = summary.get(band, 0) + 1
    return dict(sorted(summary.items()))


def _format_time(value: str | None) -> str:
    if not value:
        return "未知"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _stat_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value")
    return value


class NarrativeReportService:
    """Generate a deterministic Chinese long-form analysis report."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def generate(self, *, account_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Build or reuse the narrative report for one account."""
        try:
            distillation = _latest_distillation(self.project, account_id)
        except DistillerError:
            distillation = None
        health = _latest_health_report(self.project, account_id)
        enrichment = _latest_enrichment(self.project, account_id)
        comment_analysis, _ = _latest_comment_analysis(self.project, account_id)
        rows, account = _video_rows(self.project, account_id)
        bands = _bands_summary(rows)

        seed = {
            "account_id": account_id,
            "version": NARRATIVE_VERSION,
            "distillation_id": distillation.distillation_id if distillation else None,
            "report_id": (health or {}).get("report_id"),
            "video_rows": [
                {
                    "video_id": row["video_id"],
                    "score": row["score"],
                    "band": row["band"],
                    "pillar": row["pillar"],
                }
                for row in rows
            ],
        }
        narrative_id = stable_id("narr_", seed)
        output_dir = self.project.root / "reports" / "accounts" / account_id / narrative_id
        narrative_path = output_dir / "narrative.md"
        longform_path = output_dir / "longform.md"
        if narrative_path.is_file() and longform_path.is_file() and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "outputs": [
                    self.project.relative(narrative_path),
                    self.project.relative(longform_path),
                ],
            }

        run_id = stable_id("run_dry_", narrative_id)
        if not dry_run:
            scope_hashes = (
                [str(item) for item in distillation.data_scope.values()] if distillation else []
            )
            manifest = self.project.begin_run(
                "report narrative",
                input_hashes=sorted(
                    {
                        *scope_hashes,
                        *((health or {}).get("input_hashes") or []),
                    }
                ),
            )
            run_id = manifest.run_id

        payload = self._build_payload(
            account_id=account_id,
            distillation=distillation,
            health=health,
            enrichment=enrichment,
            comment_analysis=comment_analysis,
            rows=rows,
            bands=bands,
            account=account,
        )
        markdown = self._render(payload)
        longform_markdown = self._render_longform(payload)

        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "narrative.md").write_text(markdown, encoding="utf-8")
            (output_dir / "longform.md").write_text(
                longform_markdown,
                encoding="utf-8",
            )
            (output_dir / "run_id.txt").write_text(run_id, encoding="utf-8")
        return {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "outputs": [
                self.project.relative(narrative_path),
                self.project.relative(longform_path),
            ],
        }

    def _build_payload(
        self,
        *,
        account_id: str,
        distillation: Any | None,
        health: dict[str, Any] | None,
        enrichment: dict[str, Any] | None,
        comment_analysis: CommentAnalysis | None,
        rows: list[dict[str, Any]],
        bands: dict[str, int],
        account: dict[str, Any],
    ) -> dict[str, Any]:
        stats = {}
        if health:
            stats = dict(health.get("statistics") or {})
        band_order = ("S", "A", "B", "C", "D")
        stat_flat = {
            "follower_count_current": _stat_value(stats.get("follower_count_current")),
            "video_count": _stat_value(stats.get("video_count")),
            "publishing_frequency_weekly": _stat_value(stats.get("publishing_frequency_weekly")),
            "publication_gap_days_median": (stats.get("publication_gap_days") or {}).get("median"),
            "duration_seconds_median": (stats.get("duration_seconds") or {}).get("median"),
            "high_performance_rate": _stat_value(stats.get("high_performance_rate")),
            "longest_low_streak": _stat_value(stats.get("longest_low_streak")),
            "outlier_video_count": _stat_value(stats.get("outlier_video_count")),
            "promoted_video_count": _stat_value(stats.get("promoted_video_count")),
            "performance_bands": stats.get("performance_bands"),
        }
        metric_coverage = {
            "views": sum(1 for row in rows if row.get("views") is not None),
            "likes": sum(1 for row in rows if row.get("likes") is not None),
            "comments": sum(1 for row in rows if row.get("comments") is not None),
            "shares": sum(1 for row in rows if row.get("shares") is not None),
            "saves": sum(1 for row in rows if row.get("saves") is not None),
            "performance_score": sum(1 for row in rows if row.get("score") is not None),
        }
        metric_names = ("likes", "comments", "shares", "saves")
        metric_medians = {name: _median([row.get(name) for row in rows]) for name in metric_names}
        metric_medians["performance_score"] = _median([row.get("score") for row in rows])
        top_rows = rows[:5]
        bottom_rows = list(reversed(rows[-5:]))

        def _row_metric(row: dict[str, Any], name: str) -> Any:
            return row.get("score") if name == "performance_score" else row.get(name)

        top_bottom_medians = {
            name: [
                _median([_row_metric(row, name) for row in top_rows]),
                _median([_row_metric(row, name) for row in bottom_rows]),
            ]
            for name in (*metric_names, "performance_score")
        }
        median_labels = {
            "likes": "点赞",
            "comments": "评论",
            "shares": "分享",
            "saves": "收藏",
            "performance_score": "表现分",
        }

        def _fmt_median(value: float | None, *, score: bool = False) -> str:
            if value is None:
                return "?"
            return f"{value:,.2f}" if score else f"{value:,.0f}"

        median_table = []
        for name, label in median_labels.items():
            top_value, bottom_value = top_bottom_medians.get(name, (None, None))
            median_table.append(
                [
                    label,
                    _fmt_median(metric_medians.get(name), score=name == "performance_score"),
                    _fmt_median(top_value, score=name == "performance_score"),
                    _fmt_median(bottom_value, score=name == "performance_score"),
                ]
            )
        patterns = (
            [item.model_dump(mode="json") for item in distillation.patterns]
            if distillation is not None
            else []
        )

        def _is_trusted_pattern(pattern: dict[str, Any]) -> bool:
            return (
                int(pattern.get("maturity_level") or 0) >= 2
                and float(pattern.get("confidence") or 0) >= 0.65
                and not _is_unknown_label(pattern.get("name"))
            )

        trusted_patterns = [pattern for pattern in patterns if _is_trusted_pattern(pattern)]
        appendix_patterns = [pattern for pattern in patterns if not _is_trusted_pattern(pattern)]
        comment_needs = (
            [item.model_dump(mode="json") for item in distillation.comment_need_clusters]
            if distillation is not None
            else []
        )
        for need in comment_needs:
            need["opportunity_preview"] = _opportunity_preview(
                need.get("content_opportunities") or []
            )
        meaningful_comment_needs = [
            need for need in comment_needs if not _is_unknown_label(need.get("name"))
        ]

        def _has_chinese(value: str) -> bool:
            return any("\u4e00" <= char <= "\u9fff" for char in value)

        actions_raw = distillation.action_recommendations if distillation is not None else []
        actions: list[str] = []
        for item in actions_raw:
            translated = _translate_known(item).strip()
            if (
                _has_chinese(translated)
                and not _is_unknown_label(translated)
                and translated not in actions
            ):
                actions.append(translated)
        positioning = (
            distillation.positioning.model_dump(mode="json") if distillation is not None else {}
        )
        if positioning.get("statement"):
            positioning["statement"] = _statement_zh(positioning["statement"])
        top_hooks = _counter_top([row.get("hook_type") for row in top_rows])
        bottom_hooks = _counter_top([row.get("hook_type") for row in bottom_rows])
        top_pillars = _counter_top([row.get("pillar") for row in top_rows])
        bottom_pillars = _counter_top([row.get("pillar") for row in bottom_rows])
        top_duration = _median([row.get("duration_seconds") for row in top_rows])
        bottom_duration = _median([row.get("duration_seconds") for row in bottom_rows])
        top_shot = _median([row.get("avg_shot_ms") for row in top_rows])
        bottom_shot = _median([row.get("avg_shot_ms") for row in bottom_rows])

        series_groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            match = re.search(r"第\s*(\d+)\s*期", row["title"])
            if not match:
                continue
            key = re.sub(r"第\s*\d+\s*期.*", "", row["title"]).strip()[:24] or "系列内容"
            series_groups.setdefault(key, []).append(row)
        series_findings: list[dict[str, Any]] = []
        for key, items in series_groups.items():
            scores = [item.get("score") for item in items]
            median_score = _median(scores)
            series_findings.append(
                {
                    "name": key,
                    "count": len(items),
                    "bands": "、".join(str(item.get("band") or "未分层") for item in items),
                    "median_score": round(median_score, 2) if median_score is not None else None,
                }
            )

        top_needs = sorted(
            meaningful_comment_needs,
            key=lambda need: need.get("frequency") or 0,
            reverse=True,
        )[:3]
        comment_topic_hits = [
            {
                "name": _zh(need.get("name")),
                "frequency": need.get("frequency") or 0,
                "preview": need.get("opportunity_preview"),
            }
            for need in top_needs
        ]

        data_health_parts: list[str] = []
        if metric_coverage.get("views", 0) == 0:
            data_health_parts.append(
                "播放量完全缺失，无法计算完播率、互动率（按播放）等漏斗指标，"
                "表现分层主要依赖点赞/评论/分享/收藏"
            )
        data_health_parts.append(
            f"样本共 {len(rows)} 条，其中 {metric_coverage.get('performance_score', 0)} 条有表现分"
        )
        if bands:
            data_health_parts.append(
                "表现分层为 "
                + " / ".join(
                    f"{band} 级 {bands.get(band, 0)} 条"
                    for band in ("S", "A", "B", "C", "D")
                    if bands.get(band)
                )
            )
        data_health_parts.append("结论按账号内相对表现给出，不构成跨账号或因果判断")
        data_health_summary = "；".join(data_health_parts) + "。"

        persona = [_zh(item) for item in positioning.get("persona_signals", [])][:3]
        visual = positioning.get("visual_and_audio_identity") or []
        visual_short = [item.split("；", 1)[0][:24] for item in visual[:2]]
        top_hook_name = _zh(top_hooks[0][0]) if top_hooks else "无明显钩子偏好"
        top_pillar_name = _zh(top_pillars[0][0]) if top_pillars else None
        account_method = (
            f"该账号以「{'、'.join(persona) if persona else '强人设内容'}」为记忆点，"
            f"视觉上以「{'；'.join(visual_short) if visual_short else '竖屏短内容'}」为特征；"
            f"高热度内容更常使用「{top_hook_name}」"
        )
        if top_pillar_name:
            account_method += f"，并偏向「{top_pillar_name}」方向"
        account_method += "。整体像“固定人设 + 悬念钩子反复验证选题，再放大验证成功的方向”的打法。"

        top_likes, bottom_likes = top_bottom_medians.get("likes", (None, None))
        top_comments, bottom_comments = top_bottom_medians.get("comments", (None, None))
        comparative_ratios = {
            "likes": _ratio(top_likes, bottom_likes),
            "comments": _ratio(top_comments, bottom_comments),
            "duration": _ratio(top_duration, bottom_duration),
        }
        signal_quality = [
            {
                "signal": "账号内相对表现",
                "status": "可用于决策",
                "reason": f"{metric_coverage.get('performance_score', 0)} 条视频有表现分，可做 Top/Bottom 对照。",
            },
            {
                "signal": "点赞与评论绝对量",
                "status": "可用于发现差异",
                "reason": "可以识别账号内强弱样本，但没有播放量时不能解释互动效率。",
            },
            {
                "signal": "内容语义与钩子",
                "status": "谨慎使用" if not top_hooks else "可作为假设",
                "reason": (
                    "已过滤未知和降级标签，只把明确识别的语义当作待验证假设。"
                    if top_hooks or top_pillars
                    else "当前没有稳定、明确的语义标签，不能据此给出选题配方。"
                ),
            },
            {
                "signal": "播放—完播—互动漏斗",
                "status": "暂不可用" if metric_coverage.get("views", 0) == 0 else "部分可用",
                "reason": (
                    "播放量缺失，无法区分曝光优势、留存优势和互动优势。"
                    if metric_coverage.get("views", 0) == 0
                    else "已有播放量，仍需结合完播和平均观看时长判断留存。"
                ),
            },
            {
                "signal": "增长与转粉",
                "status": "暂不可用",
                "reason": "缺少第二次账号快照和单条视频转粉，不能判断高互动是否真正带来账号增长。",
            },
        ]

        judgments: list[dict[str, Any]] = []
        interaction_facts: list[str] = []
        if top_likes is not None and bottom_likes is not None:
            fact = f"Top 5 点赞中位数 {_number(top_likes)}，Bottom 5 为 {_number(bottom_likes)}"
            if comparative_ratios["likes"] is not None:
                fact += f"，相差 {comparative_ratios['likes']:.2f} 倍"
            interaction_facts.append(fact + "。")
        if top_comments is not None and bottom_comments is not None:
            fact = (
                f"Top 5 评论中位数 {_number(top_comments)}，Bottom 5 为 {_number(bottom_comments)}"
            )
            if comparative_ratios["comments"] is not None:
                fact += f"，相差 {comparative_ratios['comments']:.2f} 倍"
            interaction_facts.append(fact + "。")
        if interaction_facts:
            judgments.append(
                {
                    "title": "强弱内容之间不是小幅波动，而是存在数量级差距",
                    "verdict": "账号已经证明自己能制造显著高于基线的内容，但还没有证明这种能力可以稳定复现。",
                    "facts": interaction_facts,
                    "mechanism": "点赞与评论同时拉开差距，更像是内容既扩大了认同面，又创造了表达欲；真正值得拆的是用户为何愿意表态，而不是只抄标题或题材名。",
                    "alternatives": [
                        "高表现作品可能获得了更多初始曝光，绝对互动量随曝光同步放大。",
                        "热点、发布时间、投放或外部事件也可能同时推高点赞和评论。",
                    ],
                    "falsifier": "补齐播放量后，如果 Top/Bottom 的点赞率、评论率接近，说明当前差距主要来自曝光，而不是内容说服力。",
                    "decision": "下一轮把 Top 5 当作结构假设库，不把它们直接写成爆款公式；每次只复用一个结构变量，并保留同主题对照。",
                    "indicator": "优先看点赞率、评论率和有效评论占比，而不是继续只看绝对点赞。",
                    "stop_condition": "连续 3 条复用同一结构后仍未高于账号近 20 条中位水平，就停止把该结构视为可复制优势。",
                    "confidence": "中",
                }
            )

        unclassified_top = [row for row in top_rows if _is_unknown_label(row.get("pillar"))]
        if top_pillars and unclassified_top:
            dominant_pillar, dominant_count = top_pillars[0]
            outlier = max(
                unclassified_top,
                key=lambda row: int(row.get("comments") or 0),
            )
            judgments.append(
                {
                    "title": "高表现组混合了不同需求引擎，不能平均成一种爆款公式",
                    "verdict": (
                        f"Top 5 中有 {dominant_count} 条明确属于“{_zh(dominant_pillar)}”，"
                        "同时存在一个语义未分类但评论极高的样本；两者很可能承担不同经营任务。"
                    ),
                    "facts": [
                        f"明确的主导方向占 Top 5 的 {dominant_count}/5。",
                        f"《{outlier['title']}》获得 {_number(outlier.get('comments'))} 条评论，"
                        "但当前语义分析未能可靠归类。",
                    ],
                    "mechanism": (
                        "专业内容可能通过一线经验与细节建立权威；另一类作品可能通过人物关系、"
                        "故事悬念或情绪参与制造评论。它们都能高表现，却不应共享同一评价标准。"
                    ),
                    "alternatives": [
                        "未分类可能只是语义分析降级，并不代表内容机制真的不同。",
                        "异常高评论也可能来自事件性流量，不能直接解释为稳定的人格关系资产。",
                    ],
                    "falsifier": (
                        "对该样本重新做完整转写与云端语义分析；若其用户问题、叙事与评论动机"
                        "和酒店专业内容一致，就应合并解释。"
                    ),
                    "decision": (
                        "暂时把内容分为“专业权威线”和“人格/故事线”两条假设赛道，分别设指标，"
                        "不要用一条线的爆款拉高另一条线的基线。"
                    ),
                    "indicator": (
                        "专业线看收藏、求证与主页访问；人格线看有效讨论、关注与连续追更。"
                        "转粉数据补齐前只做方向性判断。"
                    ),
                    "stop_condition": (
                        "若后续 3 条人格/故事内容无法再产生高于基线的深度评论或关注，"
                        "就把该样本视为事件性离群点。"
                    ),
                    "confidence": "中低",
                }
            )

        if top_duration is not None and bottom_duration is not None:
            longer = top_duration > bottom_duration * 1.15
            judgments.append(
                {
                    "title": (
                        "高表现组更长，反驳了“这个账号只要做短就会更好”"
                        if longer
                        else "时长不是当前样本中最清晰的分水岭"
                    ),
                    "verdict": (
                        "用户可能愿意为完整故事或高信息密度付出更长时间；问题不在秒数本身，而在每一段是否持续兑现。"
                        if longer
                        else "不能从当前时长差异推出机械的秒数配方，应优先检查内容密度与承诺兑现。"
                    ),
                    "facts": [
                        f"Top 5 时长中位数 {_number(top_duration)} 秒，Bottom 5 为 {_number(bottom_duration)} 秒"
                        + (
                            f"，前者约为后者的 {comparative_ratios['duration']:.2f} 倍。"
                            if comparative_ratios["duration"] is not None
                            else "。"
                        )
                    ],
                    "mechanism": "当题材需要过程、冲突或证据时，更长时长可以容纳完整的价值兑现；删短如果同时删掉关键证据，反而会降低信任。",
                    "alternatives": [
                        "长视频可能恰好集中在更强的题材上，真正起作用的是题材而非时长。",
                        "缺少完播率与观看时长，无法确认观众是否真的看完。",
                    ],
                    "falsifier": "若同主题、同开头的短版在完播、互动率和有效评论上全面胜出，则应否定“需要更长承载”的解释。",
                    "decision": "不要统一压缩时长；先按内容任务决定容量，再用删减版与完整版做同主题对照。",
                    "indicator": "平均观看时长、50% 留存、完播率，以及单位观看时长产生的收藏和有效评论。",
                    "stop_condition": "长版没有带来更高平均观看时长或更深评论时，停止为完整叙事额外增加时长。",
                    "confidence": "中低",
                }
            )

        if comment_topic_hits:
            lead_need = comment_topic_hits[0]
            judgments.append(
                {
                    "title": "评论区的价值不在热闹，而在暴露用户下一步要完成的任务",
                    "verdict": f"当前最强的显性需求线索是“{lead_need['name']}”，适合转成回应型内容，而不是只当互动标签。",
                    "facts": [
                        f"该需求在可见评论样本中出现 {lead_need['frequency']} 次。",
                        f"已识别的机会线索：{lead_need['preview']}。",
                    ],
                    "mechanism": "用户主动提问、求证或分享经历，说明内容已经触发了未完成任务；回应这些任务通常比凭空扩题更接近真实需求。",
                    "alternatives": [
                        "可见评论受高赞、置顶和平台排序影响，不代表沉默观众。",
                        "高频评论可能来自争议或玩梗，未必等于关注和消费意愿。",
                    ],
                    "falsifier": "回应型内容如果只增加泛评论，却没有收藏、关注或后续问题，说明该需求的经营价值被高估。",
                    "decision": "把高频问题做成 2 条不同证据形式的回应内容，并把评论分成求答案、求证据、表达情绪和购买行动四类。",
                    "indicator": "有效追问数、收藏率、主页访问或新增关注；暂缺时至少记录高信息评论占比。",
                    "stop_condition": "两轮回应内容都不能产生更具体的追问或收藏，就把该需求降级为互动话题，而非内容支柱。",
                    "confidence": "中",
                }
            )

        high_count = bands.get("S", 0) + bands.get("A", 0)
        if rows:
            judgments.append(
                {
                    "title": "当前瓶颈更可能是复现率，而不是完全没有高表现能力",
                    "verdict": f"当前 {len(rows)} 条样本中有 {high_count} 条处于 S/A 级；经营任务应从“再猜一个爆款”转向“缩小高低表现之间的结构差异”。",
                    "facts": [
                        f"高表现样本占 {high_count}/{len(rows)}。",
                        f"最长低表现连续段为 {stat_flat.get('longest_low_streak') if stat_flat.get('longest_low_streak') is not None else '暂缺'} 条。",
                    ],
                    "mechanism": "偶发高表现说明账号已触碰到有效组合，但低表现连续出现说明团队还没有把有效组合拆成稳定的选题、证据和表达规则。",
                    "alternatives": [
                        "平台分发波动可能放大了看似不稳定的结果。",
                        "当前只取 20 条，样本窗口可能刚好覆盖特殊事件或季节性题材。",
                    ],
                    "falsifier": "扩大到 50 条并补齐播放后，如果相似结构仍呈随机分布，就不应继续把现有 Top 样本解释为稳定能力。",
                    "decision": "建立发布前假设卡和发布后对照表；每周只沉淀一条被重复验证的规则。",
                    "indicator": "同一结构连续 3 次的表现中位数，以及最差一次是否仍高于账号基线。",
                    "stop_condition": "任何规则只由单条爆款支撑时，不进入团队模板。",
                    "confidence": "中",
                }
            )

        experiment_cards: list[dict[str, str]] = []
        if top_hooks:
            experiment_cards.append(
                {
                    "name": "实验 A：开头机制，而不是标题复刻",
                    "hypothesis": f"明确使用“{top_hook_name}”的开头，比同主题的平铺开头更能让用户进入内容。",
                    "control": "同一主题、人物、主体素材、发布时间区间和时长范围；只改变前 3 秒的信息组织。",
                    "metric": "有播放数据时看 3 秒留存和完播；当前先看表现分、评论质量与收藏的方向性变化。",
                    "success": "至少 3 组配对样本中有 2 组优于对照，且最差一组不显著低于账号中位数。",
                    "stop": "只提升绝对互动但互动率不升，或产生点击却没有后续收藏/有效评论时，停止放大。",
                }
            )
        experiment_cards.append(
            {
                "name": "实验 B：完整版与删减版",
                "hypothesis": "高表现来自信息推进和证据完整，而不是单纯来自更长或更短。",
                "control": "同一用户问题和核心结论，制作证据完整版本与删减版本；其他变量尽量一致。",
                "metric": "平均观看时长、完播率、收藏率、有效追问数；缺失项必须在实验前补采。",
                "success": "某一版本在留存与深度互动上同时占优，而不是只在一个绝对量上偶然领先。",
                "stop": "两版差异小于账号自然波动，或题材不同导致不可比时，不做时长结论。",
            }
        )
        if comment_topic_hits:
            experiment_cards.append(
                {
                    "name": "实验 C：评论需求回应",
                    "hypothesis": f"围绕“{comment_topic_hits[0]['name']}”给出具体证据，比泛泛延续热门题材更能形成关注理由。",
                    "control": "同一需求做“直接结论版”和“过程证据版”，每版只保留一个主要信息组织方式。",
                    "metric": "收藏、有效追问、主页访问和关注；没有转粉数据时明确标记为待补。",
                    "success": "回应内容产生更具体的后续问题，并至少有一项深度行为高于近 20 条中位数。",
                    "stop": "只有玩梗或情绪评论增加，深度行为没有改善时停止扩成系列。",
                }
            )

        learning_path: list[str] = []
        if top_hooks:
            learning_path.append(f"第一步：拆解并模仿高热度视频的「{top_hook_name}」与开头结构")
        if comment_topic_hits:
            learning_path.append(
                f"第二步：围绕评论区需求最高的「{comment_topic_hits[0]['name']}」策划 3 条选题"
            )
        if trusted_patterns:
            learning_path.append("第三步：按可信规律设计对照实验，并保留反例验证")
        learning_path.append("第四步：补全播放量与完播数据后，再做漏斗级归因")
        return {
            "account_id": account_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "stats": stats,
            "stat_flat": stat_flat,
            "account": account,
            "metric_coverage": metric_coverage,
            "metric_medians": metric_medians,
            "top_bottom_medians": top_bottom_medians,
            "comparative_ratios": comparative_ratios,
            "median_table": median_table,
            "hook_analysis": {
                "top": [{"name": _zh(name), "count": count} for name, count in top_hooks],
                "bottom": [{"name": _zh(name), "count": count} for name, count in bottom_hooks],
            },
            "pillar_analysis": {
                "top": [{"name": _zh(name), "count": count} for name, count in top_pillars],
                "bottom": [{"name": _zh(name), "count": count} for name, count in bottom_pillars],
            },
            "top_bottom_duration": {
                "top_duration": top_duration,
                "bottom_duration": bottom_duration,
                "top_shot": top_shot,
                "bottom_shot": bottom_shot,
            },
            "series_findings": series_findings,
            "comment_topic_hits": comment_topic_hits,
            "data_health_summary": data_health_summary,
            "signal_quality": signal_quality,
            "judgments": judgments,
            "experiment_cards": experiment_cards,
            "account_method": account_method,
            "learning_path": learning_path,
            "bands": {band: bands.get(band, 0) for band in band_order if bands.get(band)},
            "rows": rows,
            "longform_rows": rows[:200],
            "top_rows": top_rows,
            "bottom_rows": bottom_rows,
            "positioning": positioning,
            "clusters": (
                [item.model_dump(mode="json") for item in distillation.content_clusters]
                if distillation is not None
                else []
            ),
            "patterns": patterns,
            "trusted_patterns": trusted_patterns,
            "appendix_patterns": appendix_patterns,
            "comment_needs": meaningful_comment_needs,
            "strengths": [
                _pattern_name_zh(item)
                for item in (distillation.strengths if distillation is not None else [])
            ],
            "weaknesses": [
                _pattern_name_zh(item)
                for item in (distillation.weaknesses if distillation is not None else [])
            ],
            "copyable": [
                _pattern_name_zh(item)
                for item in (distillation.copyable_factors if distillation is not None else [])
            ],
            "actions": actions,
            "experiments": [
                _translate_known(item)
                for item in (distillation.experiment_plan if distillation is not None else [])
                if not _is_unknown_label(item)
            ],
            "warnings": distillation.warnings if distillation is not None else [],
            "enrichment": enrichment or {},
            "comment_count": comment_analysis.comment_count if comment_analysis else 0,
            "video_refs": {
                row["video_id"]: {
                    "title": row["title"],
                    "short_id": row["short_id"],
                    "extra_tags": row["extra_tags_display"],
                    "band": row["band"],
                    "score": row["score"],
                    "pillar": row["pillar"],
                }
                for row in rows
            },
        }

    def _render_template(
        self,
        payload: dict[str, Any],
        *,
        template_name: str,
        report_label: str,
    ) -> str:
        template_path = Path(__file__).parent / "templates" / template_name
        try:
            environment = Environment(
                undefined=StrictUndefined,
                autoescape=False,
                trim_blocks=True,
                lstrip_blocks=True,
            )

            def _video_refs(video_ids: list[str]) -> str:
                refs: list[str] = []
                for video_id in video_ids:
                    ref = payload.get("video_refs", {}).get(video_id)
                    if ref is None:
                        refs.append(str(video_id))
                        continue
                    refs.append(f"《{ref['title']}》（{ref['short_id']}；{ref['extra_tags']}）")
                return "；".join(refs)

            environment.filters["video_refs"] = _video_refs
            environment.filters["zh"] = _zh
            environment.filters["pattern_effect"] = _effect_summary_zh
            environment.filters["pattern_name"] = _pattern_name_zh
            template = environment.from_string(template_path.read_text(encoding="utf-8"))
            return template.render(**payload).rstrip() + "\n"
        except Exception as exc:
            raise DistillerError(
                ErrorCode.REPORT_GENERATION,
                f"Failed to render {report_label}",
                details={"reason": str(exc), "template": template_name},
            ) from exc

    def _render(self, payload: dict[str, Any]) -> str:
        return self._render_template(
            payload,
            template_name="narrative.md.j2",
            report_label="narrative report",
        )

    def _render_longform(self, payload: dict[str, Any]) -> str:
        return self._render_template(
            payload,
            template_name="longform.md.j2",
            report_label="long-form learning report",
        )
