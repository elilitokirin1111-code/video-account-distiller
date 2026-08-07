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

NARRATIVE_VERSION = "0.5.2"

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
    "story_suspense": "悬念",
    "question_challenge": "提问挑战",
    "loss_aversion": "损失厌恶",
    "curiosity": "好奇",
    "promise": "承诺",
    "comment_trigger": "评论触发",
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
    "support": "支持认可",
    "story_suspense": "悬念钩子",
    "morning": "上午发布",
    "performance_score": "表现分",
    "account_stage": "账号阶段",
    "commercial_conversion_path": "商业化转化路径",
    "small_video_sample_no_strong_account_rule": "样本量较小，暂不构成强账号规律",
    "comment_users_are_not_all_viewers": "评论用户不能代表全部观众",
    "platform_ranking_and_pinning_can_bias_visible_comments": "平台排序与置顶可能使可见评论有偏",
    "deleted_or_unexported_comments_can_bias_the_sample": "已删除或未导出的评论可能使样本有偏",
    "direct_identifiers_redacted_from_analysis_copy": "分析副本已对直接标识信息脱敏",
    "patterns_are_observations_or_associations_not_causal_rules": "模式属于观察或统计关联，不代表因果",
    "no_phase4_pattern_is_a_level4_validated_rule": "尚无达到最高验证等级的模式",
    "high_performance": "高表现",
    "low_performance": "低表现",
    "account-local direction=高表现": "账号内方向为高表现",
    "account-local direction=低表现": "账号内方向为低表现",
}


def _zh(value: Any) -> str:
    return ZH_MAP.get(str(value), str(value))


def _pattern_name_zh(value: Any) -> str:
    text = str(value)
    for key, translated in ZH_MAP.items():
        if key and key in text:
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
    counts = Counter(str(value) for value in values if value)
    return counts.most_common(limit)


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
    media = {
        item.video_id: item
        for item in _media_features(project, video_ids)
    }
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
                "published_at": (
                    video.published_at.isoformat() if video.published_at else None
                ),
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
        if narrative_path.is_file() and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "outputs": [self.project.relative(narrative_path)],
            }

        run_id = stable_id("run_dry_", narrative_id)
        if not dry_run:
            scope_hashes = (
                [str(item) for item in distillation.data_scope.values()]
                if distillation
                else []
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

        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "narrative.md").write_text(markdown, encoding="utf-8")
            (output_dir / "run_id.txt").write_text(run_id, encoding="utf-8")
        return {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "outputs": [self.project.relative(narrative_path)],
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
            "publishing_frequency_weekly": _stat_value(
                stats.get("publishing_frequency_weekly")
            ),
            "publication_gap_days_median": (
                stats.get("publication_gap_days") or {}
            ).get("median"),
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
        metric_medians = {
            name: _median([row.get(name) for row in rows]) for name in metric_names
        }
        metric_medians["performance_score"] = _median(
            [row.get("score") for row in rows]
        )
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
        trusted_patterns = [
            pattern
            for pattern in patterns
            if int(pattern.get("maturity_level") or 0) >= 1
            and float(pattern.get("confidence") or 0) >= 0.5
        ]
        appendix_patterns = [
            pattern
            for pattern in patterns
            if not (
                int(pattern.get("maturity_level") or 0) >= 1
                and float(pattern.get("confidence") or 0) >= 0.5
            )
        ]
        comment_needs = (
            [item.model_dump(mode="json") for item in distillation.comment_need_clusters]
            if distillation is not None
            else []
        )
        for need in comment_needs:
            need["opportunity_preview"] = _opportunity_preview(
                need.get("content_opportunities") or []
            )

        def _has_chinese(value: str) -> bool:
            return any("\u4e00" <= char <= "\u9fff" for char in value)

        actions_raw = (
            distillation.action_recommendations if distillation is not None else []
        )
        actions: list[str] = []
        for item in actions_raw:
            translated = _translate_known(item).strip()
            if _has_chinese(translated) and translated not in actions:
                actions.append(translated)
        positioning = (
            distillation.positioning.model_dump(mode="json")
            if distillation is not None
            else {}
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
            series_findings.append(
                {
                    "name": key,
                    "count": len(items),
                    "bands": "、".join(str(item.get("band") or "未分层") for item in items),
                    "median_score": (
                        round(_median(scores), 2) if _median(scores) is not None else None
                    ),
                }
            )

        top_needs = sorted(
            comment_needs,
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
        visual_short = [
            item.split("；", 1)[0][:24] for item in visual[:2]
        ]
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
            "median_table": median_table,
            "hook_analysis": {
                "top": [{"name": _zh(name), "count": count} for name, count in top_hooks],
                "bottom": [
                    {"name": _zh(name), "count": count} for name, count in bottom_hooks
                ],
            },
            "pillar_analysis": {
                "top": [{"name": _zh(name), "count": count} for name, count in top_pillars],
                "bottom": [
                    {"name": _zh(name), "count": count} for name, count in bottom_pillars
                ],
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
            "account_method": account_method,
            "learning_path": learning_path,
            "bands": {
                band: bands.get(band, 0) for band in band_order if bands.get(band)
            },
            "rows": rows,
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
            "comment_needs": comment_needs,
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
                for item in (
                    distillation.copyable_factors if distillation is not None else []
                )
            ],
            "actions": actions,
            "experiments": [
                _translate_known(item)
                for item in (
                    distillation.experiment_plan if distillation is not None else []
                )
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

    def _render(self, payload: dict[str, Any]) -> str:
        template_path = Path(__file__).parent / "templates" / "narrative.md.j2"
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
                    refs.append(
                        f"《{ref['title']}》（{ref['short_id']}；{ref['extra_tags']}）"
                    )
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
                "Failed to render narrative report",
                details={"reason": str(exc)},
            ) from exc
