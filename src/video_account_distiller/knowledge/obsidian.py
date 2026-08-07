"""Local Obsidian vault export for curated account knowledge."""

from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights import AnalysisContextService
from video_account_distiller.knowledge.exporter import (
    ACCOUNT_REDACT_FIELDS,
    DEFAULT_MAX_EXPORT_BYTES,
    KnowledgeExportService,
    _safe_source_path,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json
from video_account_distiller.models import Video

OBSIDIAN_SCHEMA_VERSION = "1.0.0"
VAULT_SUBFOLDER = "视频账号蒸馏"
HUMAN_DIR_NAME = "分析报告"
MACHINE_DIR_NAME = "AI学习沉淀知识库"

_OBSIDIAN_ZH = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "unknown": "未知",
    "observed_fact": "已观察事实",
    "statistical_association": "统计关联",
    "hypothesis": "假设",
    "recommendation": "建议",
    "claim": "观点",
    "number": "数据",
    "instruction": "操作指引",
    "question": "提问",
    "other": "其他",
    "pain_point": "痛点",
    "story_suspense": "悬念",
    "question_challenge": "提问挑战",
    "loss_aversion": "损失厌恶",
    "curiosity": "好奇",
    "promise": "承诺",
    "complete": "完成",
    "degraded": "降级",
    "failed": "失败",
    "success": "成功",
    "reused": "复用",
    "skipped": "跳过",
    "mediacrawler": "抖音本地浏览器",
    "tikhub": "TikHub API",
    "association_not_causation": "关联不代表因果",
    "small_sample": "样本量较小",
    "not_experimental": "未经实验验证",
    "insufficient_history": "历史快照不足",
    "no_observed_counterexample_in_current_sample": "当前样本中未见反例",
    "failure": "失败规律",
    "提问_evidence": "证据质疑",
    "evidence": "证据",
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
    "high": "高",
    "medium": "中",
    "low": "低",
}


def _zh_text(value: Any) -> str:
    return _OBSIDIAN_ZH.get(str(value), str(value))


def _pattern_name_zh_obs(value: Any) -> str:
    text = str(value)
    for key, translated in _OBSIDIAN_ZH.items():
        if key and key in text:
            text = text.replace(key, translated)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"([\u4e00-\u9fff]) ([的与和])", r"\1\2", text)
    return text


def _effect_zh_obs(pattern: dict[str, Any]) -> str:
    text = str(pattern.get("effect_summary") or "")
    text = re.sub(r"eligible=(\d+)", r"可比样本 \1 条", text)
    text = re.sub(r"high=(\d+)", r"高表现 \1 条", text)
    text = re.sub(r"low=(\d+)", r"低表现 \1 条", text)
    text = text.replace("account-local direction=高表现", "账号内方向为高表现")
    text = text.replace("account-local direction=低表现", "账号内方向为低表现")
    text = text.replace(";", "；").replace("； ", "；").strip()
    return text


def _opportunity_preview_obs(items: list[str]) -> str:
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


def _video_ref_text(video_ids: list[str], video_meta: dict[str, dict[str, Any]]) -> str:
    refs: list[str] = []
    for video_id in video_ids:
        meta = video_meta.get(video_id)
        if meta is None:
            refs.append(str(video_id))
            continue
        refs.append(f"《{meta.get('title') or video_id}》（{meta.get('short_id') or video_id[-8:]}）")
    return "；".join(refs)


def _json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _sanitize_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|#^\[\]]', "", value).strip().strip(".")
    return cleaned or fallback


def _frontmatter(metadata: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{dumped}\n---\n"


def _wrap_report(
    title: str,
    text: str,
    tags: list[str],
    **extra: Any,
) -> str:
    metadata = {
        "tags": ["视频账号蒸馏", *tags],
        "title": title,
        **extra,
    }
    return _frontmatter(metadata) + "\n" + text.rstrip() + "\n"


def _gpt_report_zh(text: str) -> str:
    """Translate common English tokens in a cloud GPT analysis report."""

    classification_zh = {
        "observed_fact": "已观察事实",
        "statistical_association": "统计关联",
        "hypothesis": "假设",
        "recommendation": "建议",
        "unknown": "未知",
    }
    confidence_zh = {"high": "高", "medium": "中", "low": "低", "unknown": "未知"}

    def _evidence_label(ref: str) -> str:
        lowered = ref.casefold()
        if lowered.startswith("context://account"):
            return "账号快照"
        if lowered.startswith("context://data-availability"):
            return "数据可用性"
        if lowered.startswith("context://growth"):
            return "增长轨迹"
        if lowered.startswith("context://limitations"):
            return "数据局限"
        if lowered.startswith("context://analysis_contract"):
            return "分析规范"
        if lowered.startswith("context://artifacts/"):
            return f"分析产物（{ref.rsplit('/', 1)[-1]}）"
        if lowered.endswith("report.json"):
            return "账号体检报告"
        if lowered.endswith("distillation.json"):
            return "账号蒸馏"
        if lowered.endswith("enrichment.json"):
            return "媒体增强"
        if lowered.endswith("profile.json"):
            return "对标画像"
        if lowered.endswith("analysis.json"):
            return "视频分析"
        return ref

    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("- 类型："):
            value = line[len("- 类型：") :].strip()
            lines.append(f"- 类型：{classification_zh.get(value, value)}")
        elif line.startswith("- 置信度："):
            value = line[len("- 置信度：") :].strip()
            lines.append(f"- 置信度：{confidence_zh.get(value, value)}")
        elif line.startswith("- 证据：") or line.startswith("- 证据来源："):
            value = line.split("：", 1)[1].strip()
            labels = [_evidence_label(ref.strip()) for ref in value.split(",") if ref.strip()]
            lines.append(f"- 证据来源：{'、'.join(labels)}")
        else:
            lines.append(line)
    return "\n".join(lines)


_LEGACY_ZH = {
    "Pattern": "模式数量",
    "unknown": "未识别",
    "Entertainment": "娱乐",
    "entertainment": "娱乐",
    "content_creation": "内容创作",
    "culture": "文化",
    "account_stage": "账号阶段",
    "commercial_conversion_path": "商业化转化路径",
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
    "association_not_causation": "关联不代表因果",
}


def _legacy_report_zh(text: str) -> str:
    """Translate and clean legacy English-heavy report text for the human folder."""

    result = text
    for key, value in _LEGACY_ZH.items():
        result = re.sub(rf"\b{re.escape(key)}\b", value, result)
    result = re.sub(r"evi_[0-9a-f]{6,}", "[证据]", result)
    result = re.sub(r"(-?\d+\.\d{4,})", lambda m: f"{float(m.group(1)):.2f}", result)
    result = re.sub(r"\s{2,}", " ", result)
    return result


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(str(item) for item in headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _pattern_file_stem(pattern: dict[str, Any]) -> str:
    pattern_id = str(pattern.get("pattern_id") or "")
    short = pattern_id[-6:] if len(pattern_id) >= 6 else pattern_id
    name = str(pattern.get("name") or pattern_id or "pattern")
    safe = _sanitize_name(name, "pattern")
    return f"模式-{safe}-{short}"


class ObsidianVaultExporter:
    """Write bounded, privacy-aware account knowledge into a local Obsidian vault."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def _resolve_vault(self, vault_path: str | None) -> Path:
        configured: str | None = None
        try:
            configured = load_config(self.project.config_path).knowledge.obsidian_vault_path
        except DistillerError:
            pass
        candidate = (vault_path or "").strip() or (configured or "").strip()
        if not candidate:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Obsidian vault path is required",
                details={
                    "next": (
                        "pass vault_path or configure knowledge.obsidian_vault_path "
                        "in distiller.yaml"
                    )
                },
            )
        path = Path(candidate).expanduser().resolve()
        if not path.is_dir():
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Obsidian vault path does not exist or is not a directory",
                details={"vault_path": str(path)},
            )
        return path

    def _payload(
        self,
        *,
        account_id: str,
        max_video_analyses: int,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str], str, dict[str, Any]]:
        context = AnalysisContextService(self.project).build(
            account_id=account_id,
            max_video_analyses=max_video_analyses,
        )
        account = context.get("account")
        if account is None:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                "Account is not available in normalized data",
                details={"account_id": account_id},
            )
        payload = copy.deepcopy(context)
        payload.pop("generated_at", None)
        folder_hint = account.get("display_name") or account.get("handle") or account_id
        original_account = copy.deepcopy(account)
        redacted_fields: list[str] = []
        config = load_config(self.project.config_path)
        if config.privacy.redact_usernames_in_reports:
            for field in ACCOUNT_REDACT_FIELDS:
                if account.get(field) is not None:
                    account[field] = None
                    redacted_fields.append(f"account.{field}")
        safe_sources = sorted(
            {
                safe
                for value in payload.get("source_paths", [])
                if isinstance(value, str) and (safe := _safe_source_path(value)) is not None
            }
        )
        payload["source_paths"] = safe_sources
        payload["privacy"] = {
            "contains_raw_comments": False,
            "redacted_fields": redacted_fields,
        }
        return payload, account, safe_sources, str(folder_hint), original_account

    def _folder_name(self, account_id: str, folder_hint: str) -> str:
        return _sanitize_name(folder_hint, account_id)

    def _render_readme(
        self,
        *,
        payload: dict[str, Any],
        account: dict[str, Any],
        folder_name: str,
        account_id: str,
        gpt_payload: dict[str, Any] | None = None,
        report_stems: list[str] | None = None,
    ) -> str:
        availability = payload.get("data_availability") or {}
        video_analyses = payload.get("artifacts", {}).get("video_analyses") or []
        patterns = self._load_patterns()
        metadata = {
            "aliases": [folder_name],
            "tags": ["视频账号蒸馏", "账号"],
            "account_id": account_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "source_project": (payload.get("project") or {}).get("project_name"),
        }
        lines = [
            _frontmatter(metadata),
            f"# {folder_name}",
            "",
            "> 本笔记由 Video Account Distiller 从公开账号分析产物生成，"
            "仅包含经筛选的派生知识，不含原始评论、签名视频地址或凭据。",
            "",
            "## 数据可用性",
            "",
            _table(
                ["项目", "数量"],
                [
                    ["账号视频", availability.get("account_videos", 0)],
                    ["指标快照", availability.get("metric_snapshots", 0)],
                    ["公开评论", availability.get("public_comments", 0)],
                    ["已分析视频（上下文内）", availability.get("analyzed_videos_in_context", 0)],
                ],
            ),
            "",
            "## 仓库结构说明",
            "",
            "| 目录 | 内容 |",
            "|---|---|",
            "| `分析报告/` | 运营可读的笔记与报告（当前目录） |",
            "| `AI学习沉淀知识库/` | 知识包、模式、单条视频明细、原始 JSON 等结构化沉淀 |",
            "",
            "## AI 学习沉淀知识库",
            "",
            "- [[知识包]]",
            "- [[蒸馏原始数据]]",
            "- [[05-模式与规律]]",
            "- [[视频分析明细]]",
            "",
            "## 笔记导航",
            "",
            "- [[01-账号快照]]",
            "- [[03-媒体分析]]",
            "- [[04-视频分析]]",
            "",
        ]
        if report_stems:
            lines.extend(["- [[报告-账号体检]]", "- [[报告-账号蒸馏]]", "- [[报告-深度运营分析]]", ""])
        if gpt_payload is not None:
            lines.extend(
                [
                    "- [[06-云端深度分析]]",
                    "",
                ]
            )
        lines.extend(
            [
                f"## 已分析视频（{len(video_analyses)}）",
                "",
            ]
        )
        lines.append("- 单条视频的模型分析明细见「AI学习沉淀知识库/视频分析明细」。")
        if gpt_payload is not None:
            result = gpt_payload.get("result") or {}
            lines.extend(
                [
                    "",
                    "## 云端深度分析",
                    "",
                    (
                        "- 模型："
                        f"{gpt_payload.get('returned_model') or gpt_payload.get('requested_model')}"
                    ),
                    f"- 模板：{gpt_payload.get('template')}",
                    f"- 生成时间：{gpt_payload.get('generated_at')}",
                    f"- 摘要：{str(result.get('executive_summary') or '-')[:120]}",
                    "",
                ]
            )
        if report_stems:
            lines.extend(
                [
                    "",
                    "## 报告",
                    "",
                ]
            )
            lines.extend(f"- [[{stem}]]" for stem in report_stems)
            lines.append("")
        lines.extend(["", f"## 模式与规律（{len(patterns)}）", ""])
        lines.append("- 模式与规律的结构化明细见「AI学习沉淀知识库/05-模式与规律」。")
        lines.extend(["", "## 局限", ""])
        lines.extend(f"- {item}" for item in payload.get("limitations", []))
        lines.extend(["", "## 证据溯源", ""])
        lines.extend(f"- `{item}`" for item in payload.get("source_paths", []))
        return "\n".join(lines).rstrip() + "\n"

    def _latest_gpt_analysis(self, account_id: str) -> dict[str, Any] | None:
        candidates: list[tuple[str, dict[str, Any]]] = []
        root = self.project.root / "analyses" / "gpt" / account_id
        if not root.is_dir():
            return None
        for path in sorted(root.glob("*/analysis.json")):
            try:
                payload = read_json(path)
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
                continue
            candidates.append((str(payload.get("generated_at") or ""), payload))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], str(item[1].get("analysis_id") or "")))[
            1
        ]

    def _latest_report_path(
        self,
        account_id: str,
        prefix: str,
        filename: str,
    ) -> Path | None:
        root = self.project.root / "reports" / "accounts" / account_id
        if not root.is_dir():
            return None
        candidates = [
            path
            for directory in root.glob(f"{prefix}_*")
            if (path := directory / filename).is_file()
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: (path.stat().st_mtime, str(path)))

    def _render_gpt_note(self, payload: dict[str, Any]) -> str:
        result = payload.get("result") or {}
        metadata = {
            "tags": ["视频账号蒸馏", "云端深度分析"],
            "analysis_id": payload.get("analysis_id"),
            "generated_at": payload.get("generated_at"),
            "provider": payload.get("provider"),
            "model": payload.get("returned_model") or payload.get("requested_model"),
            "template": payload.get("template"),
        }
        lines = [
            _frontmatter(metadata),
            "# 06 · 云端深度分析",
            "",
            "> 所属账号：[[README]]",
            "",
            f"- 分析 ID：`{payload.get('analysis_id')}`",
            f"- 生成时间：{payload.get('generated_at')}",
            f"- 服务商：{payload.get('provider')}",
            f"- 模型：{payload.get('returned_model') or payload.get('requested_model')}",
            f"- 模板：{payload.get('template')}",
            f"- 推理强度：{payload.get('reasoning_effort')}",
            "",
            "## 摘要",
            "",
            str(result.get("executive_summary") or "-"),
            "",
            "## 主要发现",
            "",
        ]
        findings = result.get("findings") or []
        if findings:
            for finding in findings:
                lines.extend(
                    [
                        f"### {finding.get('title')}",
                        "",
                        f"- 类型：{finding.get('classification')}",
                        f"- 置信度：{finding.get('confidence')}",
                        f"- 结论：{finding.get('statement')}",
                        (
                            f"- 证据：{', '.join(finding.get('evidence_refs') or [])}"
                            if finding.get("evidence_refs")
                            else "- 证据：-"
                        ),
                        "",
                    ]
                )
        else:
            lines.append("- 无发现。")
        actions = result.get("priority_actions") or []
        lines.extend(["## 优先行动", ""])
        if actions:
            for action in actions:
                lines.append(f"- **{action.get('priority')}** {action.get('action')}")
                if action.get("rationale"):
                    lines.append(f"  - 理由：{action.get('rationale')}")
                if action.get("evidence_refs"):
                    lines.append(f"  - 证据：{', '.join(action.get('evidence_refs'))}")
        else:
            lines.append("- 无优先行动。")
        experiments = result.get("experiments") or []
        lines.extend(["", "## 实验建议", ""])
        if experiments:
            for experiment in experiments:
                lines.append(f"- **假设**：{experiment.get('hypothesis')}")
                lines.append(f"  - 动作：{experiment.get('action')}")
                lines.append(f"  - 主指标：{experiment.get('primary_metric')}")
                lines.append(f"  - 观察窗口：{experiment.get('observation_window')}")
        else:
            lines.append("- 本次未生成实验建议。")
        limitations = result.get("limitations") or payload.get("limitations") or []
        lines.extend(["", "## 局限", ""])
        lines.extend(f"- {item}" for item in limitations)
        lines.extend(["", "## 溯源", ""])
        lines.append(
            f"- `analyses/gpt/{payload.get('account_id')}/{payload.get('analysis_id')}/analysis.json`"
        )
        return "\n".join(lines).rstrip() + "\n"

    def _render_account_note(
        self,
        *,
        payload: dict[str, Any],
        account: dict[str, Any],
        folder_name: str,
        original_account: dict[str, Any] | None = None,
    ) -> str:
        source = original_account or account
        metadata = {
            "tags": ["视频账号蒸馏", "账号"],
            "aliases": [folder_name],
        }

        def _fmt(value: Any) -> str:
            if isinstance(value, (int, float)):
                return f"{value:,.0f}"
            if value is None:
                return "未知"
            return str(value).replace("\r\n", " ").replace("\n", " ")

        account_rows = [
            ["显示名称", source.get("display_name")],
            ["账号", source.get("handle")],
            ["简介", source.get("bio")],
            ["主页", source.get("profile_url")],
            [
                "认证",
                "已认证"
                if source.get("verified") is True
                else ("未认证" if source.get("verified") is False else "未知"),
            ],
            ["粉丝", _fmt(source.get("follower_count_current"))],
            ["关注", _fmt(source.get("following_count_current"))],
            ["获赞", _fmt(source.get("total_likes_current"))],
            ["作品数", _fmt(source.get("video_count_current"))],
            ["快照时间", source.get("snapshot_at")],
        ]
        lines = [
            _frontmatter(metadata),
            "# 01 · 账号快照",
            "",
            f"> 所属账号：[[README|{folder_name}]]",
            "",
            _table(["字段", "值"], account_rows),
            "",
            "## 数据可用性",
            "",
            _table(
                ["项目", "数量"],
                [
                    ["账号视频", (payload.get("data_availability") or {}).get("account_videos", 0)],
                    [
                        "指标快照记录（累计）",
                        (payload.get("data_availability") or {}).get("metric_snapshots", 0),
                    ],
                    ["公开评论", (payload.get("data_availability") or {}).get("public_comments", 0)],
                    [
                        "已分析视频",
                        (payload.get("data_availability") or {}).get("analyzed_videos_in_context", 0),
                    ],
                ],
            ),
            "",
            "## 观察到的增长",
            "",
        ]
        growth = payload.get("growth") or {}
        growth_status = _zh_text(str(growth.get("status") or "未知"))
        lines.extend(
            [
                f"- 增长轨迹状态：{growth_status}",
                "- 更多增长与影响力细节请阅读《报告-深度运营分析》。",
                "",
            ]
        )
        lines.extend(
            [
                "## 账号影响力概览",
                "",
                _table(
                    ["维度", "数值"],
                    [
                        ["当前粉丝数", _fmt(source.get("follower_count_current"))],
                        ["当前获赞总数", _fmt(source.get("total_likes_current"))],
                        ["当前作品数", _fmt(source.get("video_count_current"))],
                        [
                            "认证状态",
                            "已认证"
                            if source.get("verified") is True
                            else ("未认证" if source.get("verified") is False else "未知"),
                        ],
                    ],
                ),
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _render_distillation_note(self, *, payload: dict[str, Any]) -> str:
        artifacts = payload.get("artifacts") or {}
        metadata = {
            "tags": ["视频账号蒸馏", "机器数据", "蒸馏"],
        }
        lines = [
            _frontmatter(metadata),
            "# 蒸馏原始数据（机器可读）",
            "",
            "> 本文件保留原始蒸馏 JSON，供程序或进阶用户查阅；日常阅读请看「分析报告」下的报告。",
            "",
        ]
        distillation = artifacts.get("account_distillation")
        report = artifacts.get("account_health_report")
        if distillation:
            lines.extend(["## 账号蒸馏", "", _json_block(distillation.get("data")), ""])
        if report:
            lines.extend(["## 账号健康报告", "", _json_block(report.get("data")), ""])
        if not distillation and not report:
            lines.append("暂无蒸馏或健康报告产物。")
        return "\n".join(lines).rstrip() + "\n"

    def _render_distillation_human(
        self,
        *,
        payload: dict[str, Any],
        video_meta: dict[str, dict[str, Any]],
    ) -> str:
        distillation = (payload.get("artifacts") or {}).get("account_distillation")
        data = distillation.get("data") if distillation else None
        metadata = {
            "tags": ["视频账号蒸馏", "报告", "蒸馏"],
            "title": "账号蒸馏报告（深度解读）",
        }
        lines = [
            _frontmatter(metadata),
            "# 账号蒸馏报告（深度解读）",
            "",
            "> 所属账号：[[README]]",
            "",
        ]
        if not data:
            lines.append("暂无蒸馏数据。")
            return "\n".join(lines).rstrip() + "\n"

        def _has_chinese(value: str) -> bool:
            return any("\u4e00" <= char <= "\u9fff" for char in value)

        scope = data.get("data_scope") or {}
        positioning = data.get("positioning") or {}
        statement = _pattern_name_zh_obs(positioning.get("statement") or "暂无定位描述")
        persona = [_zh_text(item) for item in positioning.get("persona_signals", [])][:3]
        visual = positioning.get("visual_and_audio_identity") or []
        visual_short = [
            item.split("；", 1)[0][:24].lstrip("以")
            for item in visual[:2]
        ]
        clusters = data.get("content_clusters") or []
        best = max(
            clusters,
            key=lambda cluster: cluster.get("median_performance_score") or -99,
            default=None,
        )
        worst = min(
            clusters,
            key=lambda cluster: cluster.get("median_performance_score") or 99,
            default=None,
        )

        lines.extend(
            [
                "## 一句话定位",
                "",
                statement,
                "",
                "## 账号打法总结",
                "",
            ]
        )
        method = f"该账号以「{'、'.join(persona) if persona else '强人设内容'}」为记忆点"
        if visual_short:
            method += f"，视觉上以「{'；'.join(visual_short)}」为特征"
        if best:
            best_name = (
                "未识别方向"
                if str(best.get("name") or "").lower() == "unknown"
                else _zh_text(best.get("name"))
            )
            best_score = best.get("median_performance_score")
            method += (
                f"；当前表现最好的方向是「{best_name}」"
                f"（表现分中位数 {round(best_score, 2) if best_score is not None else '暂无'}）"
            )
        if worst and worst.get("name") != (best or {}).get("name"):
            worst_name = (
                "未识别方向"
                if str(worst.get("name") or "").lower() == "unknown"
                else _zh_text(worst.get("name"))
            )
            method += f"，最弱的方向是「{worst_name}」"
        method += "。建议把高表现方向系列化，弱方向先做小成本试探再决定是否放大。"
        lines.append(method)
        lines.extend(
            [
                "",
                "## 人设与视听风格",
                "",
                "- 人设信号："
                + (
                    "；".join(_zh_text(item) for item in positioning.get("persona_signals", []))
                    or "待补充"
                ),
                "- 视听风格："
                + (
                    "；".join(positioning.get("visual_and_audio_identity", []))
                    or "待补充本地视频分析"
                ),
                "- 仍未知："
                + (
                    "；".join(_zh_text(item) for item in positioning.get("unknowns", []))
                    or "无"
                ),
                "",
                "## 内容簇深度解读",
                "",
            ]
        )
        if clusters:
            for cluster in sorted(
                clusters,
                key=lambda item: item.get("median_performance_score") or 0,
                reverse=True,
            ):
                name = (
                    "未识别（语义分析未给出方向）"
                    if str(cluster.get("name") or "").lower() == "unknown"
                    else _zh_text(cluster.get("name"))
                )
                score = cluster.get("median_performance_score")
                rate = cluster.get("high_performance_rate")
                lines.append(f"### {name}（{cluster.get('video_count', 0)} 条）")
                lines.append(
                    f"- 表现分中位数：{round(score, 2) if score is not None else '暂无'}；"
                    f"高表现率：{round(rate * 100) if rate is not None else '暂无'}%"
                )
                members = _video_ref_text(cluster.get("video_ids") or [], video_meta)
                if members:
                    lines.append(f"- 代表视频：{members}")
                if rate is None:
                    verdict = "暂无高表现率数据，建议继续补充样本。"
                elif rate >= 0.5:
                    verdict = "值得复制：该方向高表现比例高，建议作为主攻方向并做系列化。"
                elif rate <= 0.2:
                    verdict = "谨慎：该方向高表现比例低，建议只做少量试探，不轻易投入。"
                else:
                    verdict = "观察：样本有限，建议继续积累后再判断。"
                lines.extend([f"- 解读：{verdict}", ""])
        else:
            lines.append("- 暂无内容簇。")

        patterns = data.get("patterns") or []
        trusted = [
            pattern
            for pattern in patterns
            if int(pattern.get("maturity_level") or 0) >= 1
            and float(pattern.get("confidence") or 0) >= 0.5
        ]
        appendix = [pattern for pattern in patterns if pattern not in trusted]
        lines.extend(["## 可信规律", ""])
        if trusted:
            for pattern in trusted:
                lines.append(f"### {_pattern_name_zh_obs(pattern.get('name'))}")
                lines.append(f"- 规律描述：{_effect_zh_obs(pattern)}")
                lines.append(
                    f"- 类型：{_zh_text(pattern.get('pattern_type'))} ｜ "
                    f"成熟度：第 {pattern.get('maturity_level')} 级 ｜ "
                    f"置信度：{round(float(pattern.get('confidence') or 0) * 100)}% ｜ "
                    f"可复现性：{_zh_text(pattern.get('replicability'))}"
                )
                support = _video_ref_text(pattern.get("support_video_ids") or [], video_meta)
                counter = _video_ref_text(
                    pattern.get("counterexample_video_ids") or [],
                    video_meta,
                )
                lines.append(f"- 支持样本：{support or '无'}")
                lines.append(f"- 反例：{counter or '当前样本未观察到，需主动验证'}")
                risks = pattern.get("risks") or []
                if risks:
                    lines.append(f"- 风险：{'；'.join(_zh_text(item) for item in risks)}")
                lines.append("")
        else:
            lines.append("- 暂无达到可信门槛的规律（成熟度 ≥1 且置信度 ≥50%）。")
        if appendix:
            lines.extend(["", "## 其他规律（未达可信门槛，仅作参考）", ""])
            for pattern in appendix:
                lines.append(
                    f"- {_pattern_name_zh_obs(pattern.get('name'))}"
                    f"（置信度 {round(float(pattern.get('confidence') or 0) * 100)}%，"
                    f"成熟度第 {pattern.get('maturity_level')} 级）"
                )
            lines.append("")

        needs = data.get("comment_need_clusters") or []
        top_needs = sorted(
            needs,
            key=lambda need: need.get("frequency") or 0,
            reverse=True,
        )[:3]
        lines.extend(
            [
                "## 评论区选题机会",
                "",
                "| 需求 | 评论数 | 建议方向 |",
                "|---|---:|---|",
            ]
        )
        for need in top_needs:
            lines.append(
                f"| {_zh_text(need.get('name'))} | {need.get('frequency', 0)} | "
                f"{_opportunity_preview_obs(need.get('content_opportunities') or [])} |"
            )
        lines.extend(
            [
                "",
                "## 数据体检",
                "",
                f"- 样本：{scope.get('video_count', 0)} 条视频；评论 {scope.get('comment_count', 0)} 条",
                f"- 已做语义分析：{scope.get('analyzed_video_count', 0)} 条；"
                f"已做媒体分析：{scope.get('analyzed_media_count', 0)} 条",
                f"- 内容簇：{scope.get('content_cluster_count', 0)} 个；"
                f"模式：{scope.get('pattern_count', 0)} 条",
                "- 结论按账号内相对表现给出；模式属于观察/关联，不代表因果。",
                "",
                "## 学习路径建议",
                "",
            ]
        )
        learning: list[str] = []
        if best:
            learning.append(f"第一步：把「{_zh_text(best.get('name'))}」方向系列化，优先复刻其中的高表现视频")
        if top_needs:
            learning.append(
                f"第二步：围绕「{_zh_text(top_needs[0].get('name'))}」评论需求策划 3 条选题"
            )
        if trusted:
            learning.append("第三步：按可信规律做对照实验，保留反例验证")
        learning.append("第四步：补全播放量与完播数据后，再做漏斗级归因")
        for index, step in enumerate(learning, start=1):
            lines.append(f"{index}. {step}")
        lines.append("")

        strengths = [
            _pattern_name_zh_obs(item)
            for item in (data.get("strengths") or [])
        ]
        weaknesses = [
            _pattern_name_zh_obs(item)
            for item in (data.get("weaknesses") or [])
        ]
        copyable = [
            _pattern_name_zh_obs(item)
            for item in (data.get("copyable_factors") or [])
        ]
        actions: list[str] = []
        for item in data.get("action_recommendations") or []:
            translated = _pattern_name_zh_obs(item).strip()
            if _has_chinese(translated) and translated not in actions:
                actions.append(translated)
        experiments = [
            _pattern_name_zh_obs(item)
            for item in (data.get("experiment_plan") or [])
        ]
        if strengths:
            lines.extend(["## 可借鉴优势", ""])
            lines.extend(f"- {item}" for item in strengths)
            lines.append("")
        if weaknesses:
            lines.extend(["## 需要规避的短板", ""])
            lines.extend(f"- {item}" for item in weaknesses)
            lines.append("")
        if copyable:
            lines.extend(["## 可复制因子", ""])
            lines.extend(f"- {item}" for item in copyable)
            lines.append("")
        if actions:
            lines.extend(["## 行动建议", ""])
            lines.extend(f"- {item}" for item in actions)
            lines.append("")
        if experiments:
            lines.extend(["## 30 天实验草案", ""])
            lines.extend(f"- {item}" for item in experiments)
            lines.append("")

        warnings = data.get("warnings") or []
        if warnings:
            lines.extend(["## 限制与警告", ""])
            lines.extend(f"- {_zh_text(item)}" for item in warnings)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _video_meta(self, account_id: str) -> dict[str, dict[str, Any]]:
        meta: dict[str, dict[str, Any]] = {}
        for video in read_models(self.project.normalized_dir / "videos.parquet", Video):
            if video.account_id != account_id:
                continue
            meta[video.video_id] = {
                "title": video.title or "(无标题)",
                "short_id": video.video_id[-8:],
                "hashtags": list(video.hashtags or []),
                "content_type": video.content_type,
                "tags_text": " ".join(f"#{tag}" for tag in (video.hashtags or [])),
            }
        return meta

    def _render_media_note(self, *, payload: dict[str, Any]) -> str:
        enrichment = (payload.get("artifacts") or {}).get("media_enrichment")
        metadata = {
            "tags": ["视频账号蒸馏", "媒体分析"],
        }
        lines = [
            _frontmatter(metadata),
            "# 03 · 媒体分析（概览）",
            "",
            "> 所属账号：[[README]]",
            "> 单条视频的画面、转写、视觉明细见「AI学习沉淀知识库」下的结构化数据。",
            "",
        ]
        if enrichment is None or enrichment.get("data") is None:
            lines.append("暂无媒体增强产物。")
            return "\n".join(lines).rstrip() + "\n"
        data = enrichment["data"]
        lines.extend(
            [
                "## 处理结果",
                "",
                _table(
                    ["项目", "数量"],
                    [
                        ["计划分析", data.get("requested_limit")],
                        ["实际处理", data.get("selected_count")],
                        ["完成", data.get("completed_count")],
                        ["降级", data.get("degraded_count")],
                        ["失败", data.get("failed_count")],
                    ],
                ),
                "",
                f"- 采集源：{_zh_text(data.get('source_provider') or '未知')}",
                f"- 生成时间：{data.get('generated_at')}",
                "",
                "## 说明",
                "",
                "- 若存在失败视频，请优先查看《报告-账号蒸馏》中的样本说明。",
                "- 详细的单条视频状态表已归档到「AI学习沉淀知识库/视频分析明细」。",
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _render_video_notes(
        self,
        *,
        payload: dict[str, Any],
        video_meta: dict[str, dict[str, Any]],
    ) -> tuple[str, list[tuple[str, str]]]:
        video_analyses = payload.get("artifacts", {}).get("video_analyses") or []
        metadata = {
            "tags": ["视频账号蒸馏", "视频分析", "机器数据"],
        }
        lines = [
            _frontmatter(metadata),
            "# 视频分析明细（结构化）",
            "",
            "> 所属账号：[[README]]",
            "> 单条视频的模型分析产物；日常阅读请看「分析报告」中的《报告-深度运营分析》。",
            "",
        ]
        notes: list[tuple[str, str]] = []
        for index, item in enumerate(video_analyses, start=1):
            data = item.get("data") or {}
            video_id = str(data.get("video_id") or f"video-{index}")
            short = video_id[-8:]
            filename = f"视频-{index:02d}-{short}.md"
            note_title = f"视频-{index:02d}-{short}"
            meta = video_meta.get(video_id) or {}
            display = f"{meta.get('title') or note_title}"
            lines.append(f"- [[{note_title}]] {display}")
            notes.append((filename, self._render_video_note(data, note_title, meta)))
        if not notes:
            lines.append("暂无已分析视频。")
        return "\n".join(lines).rstrip() + "\n", notes

    def _render_video_index_human(self) -> str:
        metadata = {
            "tags": ["视频账号蒸馏", "视频分析", "分析报告"],
        }
        return (
            _frontmatter(metadata)
            + "\n"
            + "\n".join(
                [
                    "# 04 · 视频分析",
                    "",
                    "> 所属账号：[[README]]",
                    "",
                    "单条视频的模型分析明细已归档到「AI学习沉淀知识库/视频分析明细」，"
                    "供程序与进阶查阅。",
                    "",
                    "日常阅读建议：",
                    "",
                    "- 《报告-深度运营分析》中的高热度/低热度视频盘点",
                    "- 《报告-账号蒸馏》中的内容方向与拍摄手法结论",
                    "",
                ]
            )
            + "\n"
        )

    def _render_video_note(
        self,
        data: dict[str, Any],
        note_title: str,
        meta: dict[str, Any] | None = None,
    ) -> str:
        meta = meta or {}
        blind = data.get("blind_analysis") or {}
        facts = blind.get("facts") or {}
        semantics = blind.get("semantics") or {}
        metadata = {
            "tags": ["视频账号蒸馏", "视频分析", "机器数据"],
            "title": meta.get("title"),
            "video_id": data.get("video_id"),
            "short_id": meta.get("short_id"),
            "hashtags": meta.get("hashtags") or [],
            "content_type": meta.get("content_type"),
            "generated_at": data.get("generated_at"),
            "status": data.get("status"),
        }
        lines = [
            _frontmatter(metadata),
            f"# {note_title}",
            "",
            f"- 视频标题：{meta.get('title') or '未知'}",
            f"- 标签：{meta.get('tags_text') or '无'}",
            f"- 视频 ID：`{data.get('video_id')}`",
            f"- 生成时间：{data.get('generated_at')}",
            f"- 状态：{data.get('status')}",
            "",
            "> 所属账号：[[README]]",
            "",
            "## 核心事实",
            "",
        ]
        fact_items = facts.get("facts") or []
        if fact_items:
            for fact in fact_items:
                category = _zh_text(fact.get("category"))
                lines.append(f"- **{category}**：{fact.get('text')}")
        else:
            lines.append("- 无提取事实。")
        lines.extend(
            [
                "",
                "## 语义结构",
                "",
                f"- 内容支柱：{semantics.get('primary_pillar')}",
                f"- 次要主题：{', '.join(semantics.get('secondary_topics') or [])}",
                f"- 叙事类型：{semantics.get('narrative_type')}",
                f"- 漏斗阶段：{semantics.get('funnel_stage')}",
                f"- 信息密度：{semantics.get('information_density')}",
                f"- 置信度：{semantics.get('confidence')}",
                "",
                "### 钩子",
                "",
            ]
        )
        hook = semantics.get("hook") or {}
        if hook:
            lines.extend(
                [
                    f"- 类型：{hook.get('primary_type')}"
                    + (
                        f"（{', '.join(_zh_text(item) for item in (hook.get('secondary_types') or []))}）"
                        if hook.get("secondary_types")
                        else ""
                    ),
                    f"- 文案：{hook.get('hook_text')}",
                    f"- 承诺：{hook.get('promise')}",
                    f"- 好奇缺口：{hook.get('curiosity_gap')}",
                ]
            )
        else:
            lines.append("- 无钩子信息。")
        cta = semantics.get("cta") or {}
        if cta:
            lines.extend(
                [
                    "",
                    "### CTA",
                    "",
                    f"- 类型：{_zh_text(cta.get('primary_type'))}",
                    f"- 文案：{cta.get('text')}",
                    f"- 对齐分：{cta.get('alignment_score')}",
                ]
            )
        persona_signals = semantics.get("persona_signals") or []
        risk_flags = semantics.get("risk_flags") or []
        warnings = data.get("warnings") or []
        lines.extend(["", "### 信号与风险", ""])
        lines.append(f"- 人设信号：{', '.join(persona_signals) if persona_signals else '-'}")
        lines.append(
            f"- 风险标记：{', '.join(_zh_text(item) for item in risk_flags) if risk_flags else '-'}"
        )
        lines.append(
            f"- 分析警告：{', '.join(_zh_text(item) for item in warnings) if warnings else '-'}"
        )
        return "\n".join(lines).rstrip() + "\n"

    def _load_patterns(self) -> list[dict[str, Any]]:
        patterns: list[dict[str, Any]] = []
        pattern_dir = self.project.root / "knowledge-base" / "patterns"
        if not pattern_dir.is_dir():
            return patterns
        for path in sorted(pattern_dir.glob("*.json")):
            try:
                value = read_json(path)
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(value, dict):
                patterns.append(value)
        return patterns

    def _render_pattern_notes(self) -> list[tuple[str, str]]:
        notes: list[tuple[str, str]] = []
        for pattern in self._load_patterns():
            pattern_id = str(pattern.get("pattern_id") or stable_id("pat_", str(pattern)))
            name = str(pattern.get("name") or pattern_id)
            stem = _pattern_file_stem(pattern)
            metadata = {
                "tags": ["视频账号蒸馏", "模式", str(pattern.get("pattern_type") or "pattern")],
                "pattern_id": pattern_id,
                "confidence": pattern.get("confidence"),
                "maturity_level": pattern.get("maturity_level"),
                "created_at": pattern.get("created_at"),
            }
            lines = [
                _frontmatter(metadata),
                f"# 模式 · {name}",
                "",
                f"- 类型：{pattern.get('pattern_type')}",
                f"- 描述：{pattern.get('description')}",
                f"- 目标指标：{', '.join(pattern.get('target_metrics') or [])}",
                f"- 支持样本：{pattern.get('support_count')}",
                f"- 反例：{pattern.get('counterexample_count')}",
                f"- 效果：{pattern.get('effect_summary')}",
                f"- 置信度：{pattern.get('confidence')}",
                f"- 成熟度：{pattern.get('maturity_level')}",
                f"- 可复现性：{pattern.get('replicability')}",
                f"- 风险：{', '.join(pattern.get('risks') or [])}",
                f"- 证据：{', '.join(pattern.get('evidence_ids') or [])}",
                "",
                "## 特征条件",
                "",
                _json_block(pattern.get("feature_conditions")),
                "",
                "## 支持视频",
                "",
                "\n".join(
                    f"- `{item}`"
                    for item in sorted(pattern.get("support_video_ids") or [], key=str)
                ),
                "",
                "## 反例视频",
                "",
                "\n".join(
                    f"- `{item}`"
                    for item in sorted(pattern.get("counterexample_video_ids") or [], key=str)
                ),
                "",
            ]
            notes.append((f"{stem}.md", "\n".join(lines).rstrip() + "\n"))
        return notes

    def _render_pattern_index(self) -> str:
        patterns = self._load_patterns()
        metadata = {
            "tags": ["视频账号蒸馏", "模式"],
        }
        lines = [
            _frontmatter(metadata),
            "# 05 · 模式与规律",
            "",
            "> 所属账号：[[README]]",
            "",
        ]
        if patterns:
            for pattern in patterns:
                lines.append(f"- [[{_pattern_file_stem(pattern)}]]")
        else:
            lines.append("暂无达到支持阈值的模式。")
        return "\n".join(lines).rstrip() + "\n"

    def export_account(
        self,
        *,
        account_id: str,
        vault_path: str | None = None,
        max_video_analyses: int = 10,
        max_export_bytes: int = DEFAULT_MAX_EXPORT_BYTES,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if max_video_analyses < 1 or max_video_analyses > 25:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "max_video_analyses must be between 1 and 25",
            )
        payload, account, safe_sources, folder_hint, original_account = self._payload(
            account_id=account_id,
            max_video_analyses=max_video_analyses,
        )
        folder_name = self._folder_name(account_id, folder_hint)
        vault = self._resolve_vault(vault_path)
        target = vault / VAULT_SUBFOLDER / folder_name
        gpt_payload = self._latest_gpt_analysis(account_id)
        video_meta = self._video_meta(account_id)
        report_notes: list[tuple[str, str]] = []
        report_specs = [
            ("报告-账号体检", "rpt", "report.md", ["报告", "账号体检"]),
            ("报告-账号蒸馏", "dst", "report.md", ["报告", "蒸馏"]),
            ("报告-深度运营分析", "narr", "narrative.md", ["报告", "深度运营分析"]),
        ]
        for stem, prefix, filename, tags in report_specs:
            if prefix == "dst":
                continue
            report_path = self._latest_report_path(account_id, prefix, filename)
            if report_path is not None:
                report_text = report_path.read_text(encoding="utf-8")
                if prefix != "narr":
                    report_text = _legacy_report_zh(report_text)
                report_notes.append(
                    (
                        f"{stem}.md",
                        _wrap_report(
                            stem.replace("报告-", ""),
                            report_text,
                            tags,
                        ),
                    )
                )
        report_notes.append(
            (
                "报告-账号蒸馏.md",
                self._render_distillation_human(
                    payload=payload,
                    video_meta=video_meta,
                ),
            )
        )
        export_result = KnowledgeExportService(self.project).export_account(
            account_id=account_id,
            max_video_analyses=max_video_analyses,
            max_export_bytes=max_export_bytes,
            dry_run=dry_run,
        )
        curated_size = int(export_result["manifest"]["byte_size"])
        video_index, video_notes = self._render_video_notes(
            payload=payload,
            video_meta=video_meta,
        )
        human_planned: list[tuple[str, str]] = [
            ("README.md", self._render_readme(
                payload=payload,
                account=account,
                folder_name=folder_name,
                account_id=account_id,
                gpt_payload=gpt_payload,
                report_stems=[name.removesuffix(".md") for name, _ in report_notes],
            )),
            ("01-账号快照.md", self._render_account_note(
                payload=payload,
                account=account,
                folder_name=folder_name,
                original_account=original_account,
            )),
            ("03-媒体分析.md", self._render_media_note(payload=payload)),
            ("04-视频分析.md", self._render_video_index_human()),
            *report_notes,
        ]
        if gpt_payload is not None:
            analysis_id = str(gpt_payload.get("analysis_id") or "")
            gpt_report_path = (
                self.project.root / "analyses" / "gpt" / account_id / analysis_id / "report.md"
            )
            if gpt_report_path.is_file():
                human_planned.append(
                    (
                        "06-云端深度分析.md",
                        _wrap_report(
                            "云端深度分析报告",
                            _gpt_report_zh(gpt_report_path.read_text(encoding="utf-8")),
                            ["云端深度分析"],
                            analysis_id=analysis_id,
                            generated_at=gpt_payload.get("generated_at"),
                            model=(
                                gpt_payload.get("returned_model")
                                or gpt_payload.get("requested_model")
                            ),
                        ),
                    )
                )
            else:
                human_planned.append(("06-云端深度分析.md", self._render_gpt_note(gpt_payload)))
        machine_planned: list[tuple[str, str]] = [
            ("蒸馏原始数据.md", self._render_distillation_note(payload=payload)),
            ("05-模式与规律.md", self._render_pattern_index()),
            ("视频分析明细.md", video_index),
            *video_notes,
            *self._render_pattern_notes(),
        ]
        total_bytes = (
            curated_size
            + sum(len(text.encode("utf-8")) for _, text in human_planned)
            + sum(len(text.encode("utf-8")) for _, text in machine_planned)
        )
        if total_bytes > max_export_bytes:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Obsidian export exceeds the configured size limit",
                details={
                    "byte_size": total_bytes,
                    "max_export_bytes": max_export_bytes,
                    "suggestion": "Reduce max_video_analyses",
                },
            )
        human_dir = target / HUMAN_DIR_NAME
        machine_dir = target / MACHINE_DIR_NAME
        relative_files = [
            (VAULT_SUBFOLDER + "/" + folder_name + "/" + HUMAN_DIR_NAME + "/" + name).replace(
                "\\", "/"
            )
            for name, _ in human_planned
        ] + [
            (
                VAULT_SUBFOLDER + "/" + folder_name + "/" + MACHINE_DIR_NAME + "/" + name
            ).replace("\\", "/")
            for name, _ in machine_planned
        ] + [
            (
                VAULT_SUBFOLDER + "/" + folder_name + "/" + MACHINE_DIR_NAME + "/知识包.md"
            ).replace("\\", "/"),
            (
                VAULT_SUBFOLDER
                + "/"
                + folder_name
                + "/"
                + MACHINE_DIR_NAME
                + "/obsidian-manifest.json"
            ).replace("\\", "/"),
        ]
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "vault_path": str(vault),
                "account_folder": VAULT_SUBFOLDER + "/" + folder_name,
                "human_dir": VAULT_SUBFOLDER + "/" + folder_name + "/" + HUMAN_DIR_NAME,
                "machine_dir": VAULT_SUBFOLDER + "/" + folder_name + "/" + MACHINE_DIR_NAME,
                "files": sorted(relative_files),
                "byte_size": total_bytes,
            }

        human_dir.mkdir(parents=True, exist_ok=True)
        machine_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for name, text in human_planned:
            atomic_write_text(human_dir / name, text)
            written.append(
                (
                    VAULT_SUBFOLDER + "/" + folder_name + "/" + HUMAN_DIR_NAME + "/" + name
                ).replace("\\", "/")
            )
        for name, text in machine_planned:
            atomic_write_text(machine_dir / name, text)
            written.append(
                (
                    VAULT_SUBFOLDER + "/" + folder_name + "/" + MACHINE_DIR_NAME + "/" + name
                ).replace("\\", "/")
            )
        for old_dir_name in ("人读报告", "机器数据"):
            old_dir = target / old_dir_name
            if old_dir.is_dir() and old_dir.resolve().parent == target.resolve():
                shutil.rmtree(old_dir)
        legacy_names = [
            "README.md",
            "01-账号快照.md",
            "02-账号蒸馏.md",
            "03-媒体分析.md",
            "04-视频分析.md",
            "05-模式与规律.md",
            "06-云端深度分析.md",
            "知识包.md",
            "obsidian-manifest.json",
        ]
        for name in legacy_names:
            legacy_path = target / name
            if legacy_path.is_file():
                legacy_path.unlink()
        for pattern in ("报告-*.md", "视频-*.md", "模式-*.md"):
            for legacy_path in target.glob(pattern):
                if legacy_path.is_file():
                    legacy_path.unlink()
        curated_source = self.project.root / Path(export_result["document_path"])
        curated_dest = machine_dir / "知识包.md"
        if curated_source.is_file():
            shutil.copyfile(curated_source, curated_dest)
            written.append(
                (
                    VAULT_SUBFOLDER
                    + "/"
                    + folder_name
                    + "/"
                    + MACHINE_DIR_NAME
                    + "/知识包.md"
                ).replace("\\", "/")
            )
        manifest = {
            "schema_version": OBSIDIAN_SCHEMA_VERSION,
            "export_id": stable_id("obs_", account_id, folder_name),
            "account_id": account_id,
            "vault_path": str(vault),
            "account_folder": VAULT_SUBFOLDER + "/" + folder_name,
            "human_dir": VAULT_SUBFOLDER + "/" + folder_name + "/" + HUMAN_DIR_NAME,
            "machine_dir": VAULT_SUBFOLDER + "/" + folder_name + "/" + MACHINE_DIR_NAME,
            "generated_at": datetime.now(UTC).isoformat(),
            "payload_hash": sha256_json(payload),
            "source_paths": safe_sources,
            "files": sorted(written),
            "byte_size": total_bytes,
        }
        atomic_write_json(machine_dir / "obsidian-manifest.json", manifest)
        return {
            "ok": True,
            "dry_run": False,
            "vault_path": str(vault),
            "account_folder": VAULT_SUBFOLDER + "/" + folder_name,
            "human_dir": VAULT_SUBFOLDER + "/" + folder_name + "/" + HUMAN_DIR_NAME,
            "machine_dir": VAULT_SUBFOLDER + "/" + folder_name + "/" + MACHINE_DIR_NAME,
            "files": sorted(written),
            "manifest": manifest,
            "export": export_result,
            "byte_size": total_bytes,
        }
