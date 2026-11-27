"""Chinese presentation helpers for human-readable reports.

Persisted JSON deliberately keeps stable English enum values and diagnostic
codes.  Markdown reports, however, are operator-facing and should explain the
same state in Chinese instead of leaking machine vocabulary.  This module is
the single boundary between those two representations.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

REPORT_LABELS: dict[str, str] = {
    # Completion and availability states.
    "complete": "完整生成",
    "success": "成功",
    "degraded": "部分环节未完成（已保留有效结果）",
    "failed": "处理失败",
    "fail": "未通过",
    "pass": "通过",
    "error": "错误",
    "running": "处理中",
    "pending": "待处理",
    "partial": "部分完成",
    "completed": "已完成",
    "skipped": "已跳过",
    "reused": "已复用",
    "available": "可用",
    "unavailable": "不可用",
    "unknown": "仅凭当前资料无法确定",
    "unclassified": "未分类",
    "none": "无",
    # Confidence, relevance, and cohorts.
    "high": "高",
    "medium": "中",
    "middle": "中",
    "low": "低",
    "insufficient": "当前样本不足",
    "review_required": "需要复核",
    "insufficient_runs": "运行次数不足",
    # Evidence classifications.
    "fact": "事实",
    "observed_fact": "已观察事实",
    "statistical_association": "统计关联",
    "semantic_annotation": "语义标注",
    "model_inference": "模型推断",
    "hypothesis": "待验证假设",
    "experimental_rule": "待验证规则",
    "recommendation": "建议",
    "warning": "风险提示",
    "classification": "分类",
    "confidence": "置信度",
    "status": "状态",
    "evidence": "证据",
    "provider": "模型服务",
    "schema": "数据结构",
    "rubric": "评分规则",
    "claim": "观点陈述",
    "number": "数字信息",
    "entity": "实体信息",
    "offer": "优惠或提议",
    "instruction": "操作说明",
    "other": "其他",
    # Creative scoring dimensions.
    "topic": "选题",
    "hook": "开场钩子",
    "content_value": "内容价值",
    "structure": "内容结构",
    "expression": "表达方式",
    "visual_craft": "镜头与画面",
    "pacing": "节奏",
    "audio_packaging": "声音与包装",
    "emotion": "情绪",
    "conversion": "行动转化",
    # Structure roles.
    "problem": "问题呈现",
    "value_promise": "价值承诺",
    "development": "主体展开",
    "proof": "证据支撑",
    "peak": "信息或情绪峰值",
    "conclusion": "结论收束",
    "cta": "行动引导",
    "loop": "首尾呼应",
    # Knowledge types and attribution.
    "knowledge_point": "知识点",
    "concept": "概念",
    "method": "方法",
    "case": "案例",
    "data": "数据",
    "news": "新闻信息",
    "creator_opinion": "创作者观点",
    "inference": "推断",
    "video_statement": "视频原文陈述",
    "transcript": "字幕原文",
    "ocr": "画面文字",
    "visual": "画面证据",
    # Provider names remain stable in JSON; reports add a readable description.
    "cloud": "云端模型",
    "ollama": "Ollama 本地模型",
    "llamacpp": "llama.cpp 本地模型",
    "openai": "OpenAI 云端模型",
    "deepseek": "DeepSeek 云端模型",
    "bailian": "阿里云百炼模型",
    "structured_file": "结构化结果文件",
    # Model task names.
    "single_video_deep_distillation": "单视频深度创作拆解",
    "single_video_knowledge_extraction": "单视频知识提炼",
    "video_fact_extraction": "视频事实提取",
    "video_semantic_labeling": "视频语义标注",
    "comment_intent": "评论意图识别",
    # Cloud-analysis templates and reasoning levels.
    "account_health": "账号体检",
    "content_strategy": "内容策略",
    "growth_plan": "增长计划",
    "minimal": "极简",
    "xhigh": "很高",
    "max": "最高",
    # Data provenance and common content labels.
    "public": "公开数据",
    "authorized_private": "已授权私有数据",
    "model_inferred": "模型推断数据",
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "bilibili": "哔哩哔哩",
    "weibo": "微博",
    "youtube": "优管",
    "food": "餐饮",
    "room": "客房",
    "service": "服务",
    "list_explainer": "清单讲解",
    "process_explainer": "流程讲解",
    "case_story": "案例故事",
    "direct_explainer": "直接讲解",
    "education": "知识讲解",
    "experience_sharing": "经验分享",
    "information_sharing": "信息分享",
    "awareness": "认知建立",
    "consideration": "对比考虑",
    "content_type": "内容类型字段",
    "derivedmetrics": "派生表现指标",
    "null": "缺失",
    "morning": "上午",
    "afternoon": "下午",
    "evening": "晚间",
    "semantic_pillar": "语义内容方向",
    "content_type_proxy": "内容类型代理",
    "mixed": "混合来源",
    # Data-quality entities, counters, and issue codes. Unknown keys remain
    # available as backticked technical references in the Markdown report.
    "normalization": "数据标准化",
    "project": "项目",
    "accounts": "账号",
    "audience_profiles": "受众画像",
    "metrics": "指标快照",
    "transcripts": "字幕",
    "videos": "视频",
    "raw_inputs": "原始输入",
    "video_analyses": "视频分析",
    "video_distillations": "视频创作拆解",
    "media_analyses": "媒体分析",
    "media_features": "媒体特征",
    "media_enrichments": "媒体增强",
    "benchmark_profiles": "对标画像",
    "local_knowledge": "本地知识产物",
    "input_rows": "输入行数",
    "expanded_rows": "展开后行数",
    "accepted_rows": "接受行数",
    "rejected_rows": "拒绝行数",
    "duplicate_rows": "重复行数",
    "imports": "导入批次",
    "model_outputs": "模型输出",
    "vision_outputs": "视觉模型输出",
    "raw_media": "原始媒体",
    "platforms": "平台",
    "rules": "运营规律",
    "rubrics": "评分规则",
    "knowledge_artifacts": "知识产物",
    "duplicate_record": "重复记录",
    "duplicate_record_conflict": "重复记录冲突",
    "schema_invalid": "数据结构校验失败",
    "raw_integrity": "原始数据完整性异常",
    "analysis_artifact_invalid": "分析产物无效",
    "media_artifact_invalid": "媒体产物无效",
    "media_enrichment_artifact_invalid": "媒体增强产物无效",
    "benchmark_profile_artifact_invalid": "对标画像无效",
    "closed_loop_artifact_invalid": "闭环产物无效",
    "collaboration_artifact_invalid": "协作产物无效",
    "knowledge_artifact_invalid": "知识产物无效",
    # Common hook, CTA, and emotion enums surfaced by deterministic fallback.
    "result_first": "结果前置",
    "counterintuitive": "反直觉",
    "strong_conflict": "强冲突",
    "pain_point": "痛点切入",
    "identity_callout": "人群点名",
    "number_list": "数字清单",
    "time_pressure": "时间紧迫",
    "loss_aversion": "损失规避",
    "secret_reveal": "秘密揭示",
    "failure_review": "失败复盘",
    "before_after": "前后对比",
    "question_challenge": "提问挑战",
    "story_suspense": "故事悬念",
    "authority": "权威背书",
    "social_proof": "社会证明",
    "controversial_stance": "争议观点",
    "explicit_benefit": "明确利益点",
    "process_demo": "过程演示",
    "direct_demo": "直接演示",
    "comment": "引导评论",
    "save": "引导收藏",
    "share": "引导分享",
    "follow": "引导关注",
    "direct_message": "引导私信",
    "profile": "引导查看主页",
    "product": "引导查看产品",
    "community": "引导加入社群",
    "next_episode": "引导观看下一集",
    "calm": "平静",
    "curiosity": "好奇",
    "tension": "紧张",
    "conflict": "冲突",
    "surprise": "惊喜",
    "resonance": "共鸣",
    "anxiety": "焦虑",
    "satisfaction": "满足",
    "trust": "信任",
    "action": "行动",
    # Comment sentiment and intent enums.
    "supportive": "支持",
    "opposed": "反对",
    "neutral": "中性",
    "support": "支持",
    "oppose": "反对",
    "follow_up": "继续追问",
    "request_tutorial": "请求教程",
    "request_link": "索要链接",
    "purchase_intent": "购买意向",
    "share_experience": "分享经历",
    "suggestion": "建议",
    "knowledge_contribution": "补充知识",
    "question_evidence": "质疑证据",
    "price_objection": "价格异议",
    "feature_objection": "功能异议",
    "identity_signal": "身份信号",
    "emotional_expression": "情绪表达",
    "joke": "玩笑",
    "irrelevant": "无关内容",
    "spam_or_ad": "垃圾信息或广告",
    # Frequent metric keys from model-generated experiment suggestions.
    "views": "播放量",
    "likes": "点赞数",
    "comments": "评论数",
    "shares": "分享数",
    "saves": "收藏数",
    "engagement_rate": "互动率",
    "engagement_rate_by_view": "按播放量计算的互动率",
    "completion_rate": "完播率",
    "completion_efficiency": "完播效率",
    "follower_growth": "粉丝增长",
    "performance_score": "表现分",
    "public_interaction_proxy": "公开互动代理指标",
    "provisional_rule_score": "暂定规则评分",
    "model_assessment": "模型创作评估",
    "pattern": "规律",
    "same": "相同",
    "different": "不同",
    "directly_test": "可直接进入小范围测试",
    "adapt_then_test": "适配后再测试",
    "understand_only": "仅供理解",
    "do_not_migrate": "不建议迁移",
    "below_p25": "低于历史第 25 百分位",
    "within_p25_p75": "处于历史中间区间",
    "above_p75": "高于历史第 75 百分位",
    "strengthen": "加强",
    "weaken": "弱化",
    "narrow": "缩小适用范围",
    "hold": "保持",
    "deprecate": "停用",
    "active": "启用",
    "true": "是",
    "false": "否",
    "guaranteed_outcome": "包含结果保证性表述",
    "unsupported_superlative": "包含缺少证据支持的极限表述",
    "sensitive_claim": "包含需要重点核验的敏感表述",
    "proposed": "待审批",
    "candidate": "候选",
    "experimental": "实验中",
    "validated": "已验证",
    "deprecated": "已停用",
    "rejected": "已拒绝",
    # Pattern risks and confounders.
    "association_not_causation": "仅为统计关联，不能据此认定因果",
    "views_unavailable_proxy_is_not_view_efficiency": ("缺少播放量，当前互动代理不等同于播放效率"),
    "publication_age_not_normalized": "发布时间差异尚未完全校正",
    "no_observed_counterexample_in_current_sample": "当前样本尚未观察到反例",
    "promoted_video_excluded": "已排除广告或投流视频",
    "robust_outlier_excluded": "已排除稳健统计识别的异常视频",
    "platform_mechanism_difference": "平台分发机制不同",
    "source_pattern_has_confounders": "来源规律仍存在混杂因素",
}

REPORT_TEXT_PHRASES: dict[str, str] = {
    # Model-authored reports sometimes quote internal evidence field paths.
    # Keep stable IDs in machine artifacts, but spell these paths out for readers.
    "craft_summary.average_shot_duration_ms": "拍摄摘要中的平均镜头时长",
    "craft_summary.text_overlay_style": "拍摄摘要中的字幕样式",
    "craft_summary.pacing_tags": "拍摄摘要中的节奏标签",
    "semantics.emotion_timeline": "语义分析中的情绪时间线",
    "semantics.structure_segments": "语义分析中的内容结构",
    "semantics.cta.primary_type": "语义分析中的行动引导类型",
    "audio.has_audio": "音频分析中的音轨状态",
    "audio.status": "音频分析状态",
    "no BGM mentioned": "未提及背景音乐",
    "model provider unavailable; deterministic fallback used": (
        "模型服务不可用，已使用本地规则继续整理"
    ),
    "ocr_observations": "画面文字证据",
    "transcript_segments": "字幕片段",
    "shot_annotations": "镜头标注",
    "ocr_texts": "画面文字",
    "craft_summary": "拍摄摘要",
    "semantics.内容结构": "语义分析中的内容结构",
    "semantics.行动引导": "语义分析中的行动引导",
    "semantics.": "语义分析中的",
    "audio.": "音频分析中的",
    "decode_failed": "音频解码失败",
    "BGM": "背景音乐",
    "ASR": "语音转写",
    "Robust Z-score": "稳健标准分",
    "Phase 2": "第二阶段",
    "Phase 3": "第三阶段",
    "Phase 4": "第四阶段",
}


REPORT_WARNING_MESSAGES: dict[str, str] = {
    "Dry run: no project files or state were changed.": (
        "本次为预检，未修改任何项目文件或运行状态。"
    ),
    "Transcript hash already imported for this video.": (
        "这份字幕此前已为该视频导入，本次复用了现有记录。"
    ),
    "Transcript timing is unavailable for one or more segments.": (
        "部分字幕片段缺少时间位置，依赖时间线的分析可能不完整。"
    ),
    (
        "Multiple platforms are present. Raw metrics are not directly comparable; "
        "use account-local normalized metrics."
    ): ("项目包含多个平台；不同平台的原始指标不能直接比较，请使用各账号内部的标准化指标。"),
    "single_video_analysis_not_account_rule": (
        "本结论只适用于这一条视频，不能直接当作账号长期规律。"
    ),
    "text_only_analysis_does_not_infer_visual_or_audio_features": (
        "本页是字幕与文案分析，不据此猜测画面或声音；视听结论请以媒体分析和创作拆解为准。"
    ),
    "performance_was_attached_after_blind_labels_and_does_not_prove_causality": (
        "表现数据在内容标注完成后才关联，只用于背景对照，不能证明某种内容设计导致了结果。"
    ),
    "transcript_contains_low_confidence_segments": (
        "部分字幕转写置信度偏低，涉及专有名词、数字和关键措辞时应回听原视频复核。"
    ),
    "comment_users_are_not_all_viewers": (
        "评论用户不代表全部观看者，评论洞察不能直接外推到完整受众。"
    ),
    "platform_ranking_and_pinning_can_bias_visible_comments": (
        "平台排序和置顶机制会影响可见评论，当前评论样本可能存在展示偏差。"
    ),
    "deleted_or_unexported_comments_can_bias_the_sample": (
        "已删除或未能采集的评论不在样本中，评论分布可能因此偏移。"
    ),
    "deep_model_unavailable_deterministic_fallback": (
        "深度模型未成功启用，系统已改用本地规则整理；创作判断与评分精度会下降。"
    ),
    "deep_model_output_degraded_after_retries": (
        "深度模型多次返回不符合结构要求的结果，系统已改用本地规则整理；建议检查模型配置后重试。"
    ),
    "media_analysis_missing_craft_and_expression_limited": (
        "缺少媒体分析，拍摄手法、画面、声音和节奏判断不完整。"
    ),
    "no_visual_annotations_shot_craft_unknown": (
        "已识别镜头，但视觉模型没有产出可靠标注，暂时无法判断景别、运镜、构图和光线。"
    ),
    "external_fact_check_not_performed": (
        "本报告只提炼视频表达的内容，尚未对其中的事实执行外部核验。"
    ),
    "knowledge_model_unavailable_deterministic_fallback": (
        "知识提炼模型未成功启用，系统已依据现有字幕和分析结果进行规则化整理。"
    ),
    "media_analysis_missing_visual_and_ocr_evidence_limited": (
        "缺少媒体分析，画面内容和画面文字证据不完整。"
    ),
    "ffmpeg_unavailable_media_analysis_degraded": (
        "未找到可用的视频解码组件，画面、声音和镜头分析未能完整执行。"
    ),
    "ffmpeg_unavailable_audio_unknown": "未找到可用的音频解码组件，声音信息暂无法判断。",
    "media_duration_unknown": "未能读取视频时长，镜头时间线和节奏判断可能不完整。",
    "no_decodable_audio_stream": "没有检测到可解码的音轨，声音信息暂无法判断。",
    "decoded_audio_was_empty": "音轨解码后没有有效声音数据，声音信息暂无法判断。",
    "no_audio_stream_in_metadata": "视频元数据中没有音轨，声音分析已跳过。",
    "audio_decode_failed": "音轨解码失败，声音相关结论暂不可用。",
    "target_pillar_missing": "内容候选未指定目标方向，方向匹配项无法评分。",
    "no_account_rule_matched_script_features": "当前脚本没有匹配到可用的账号规律。",
    "no_validated_rule_supports_prediction": "尚无已验证规律支撑本次预测，预测置信度已下调。",
    "actual_snapshot_is_promoted": "实际表现快照来自广告或投流内容，不适合更新自然流量规律。",
    "actual_snapshot_is_robust_outlier": "实际表现快照属于统计异常样本，不适合直接更新规律。",
    "retro_snapshot_not_eligible_for_rule_or_rubric_updates": (
        "本次复盘快照存在混杂因素，不会用于更新规律或评分权重。"
    ),
    "transcript_coverage_incomplete": "部分视频缺少完整字幕，依赖字幕的结论覆盖不完整。",
    "transcript_contains_unreadable_characters": (
        "字幕中存在无法解码的字符，模型输入已用“此处转写无法辨认”标记；相关结论需回听原视频复核。"
    ),
    "media_analysis_degraded": "媒体分析未完整完成，当前仅保留已成功提取的结果。",
    "small_video_sample_no_strong_account_rule": (
        "视频样本少于 30 条，只能形成描述性观察，暂不作为稳定账号规律。"
    ),
    "comment_analysis_missing": "尚未获得可用的评论分析，用户需求判断暂不完整。",
    "semantic_video_analysis_coverage_low": (
        "完成语义分析的视频较少，账号定位和内容方向仅覆盖当前已分析样本。"
    ),
    "semantic_unknown_values_excluded_from_strategy": (
        "未识别的内容语义已从策略结论中排除，避免把未知项误当成内容方向。"
    ),
    "unusable_content_type_proxy_excluded_from_strategy": (
        "部分采集内容类型只是数字或内部代码，已从内容方向分析中排除。"
    ),
    "degraded_semantic_analyses_reduce_account_confidence": (
        "部分视频语义分析为降级结果，账号级结论的置信度已相应下调。"
    ),
    "semantic_confidence_mean_below_operational_threshold": (
        "语义分析平均置信度未达到运营决策门槛，当前建议应先小范围验证。"
    ),
    "actionable_patterns_withheld_due_to_low_semantic_quality": (
        "语义质量不足，系统没有把弱关联升级为可直接执行的规律。"
    ),
    "comment_unknown_clusters_excluded_from_strategy": ("未识别的评论类别已从策略结论中排除。"),
    "media_analysis_coverage_low": ("完成画面与声音分析的视频较少，视听风格结论覆盖不完整。"),
    "craft_profile_vision_annotations_low": ("可靠的画面语义标注不足，拍摄手法画像暂不完整。"),
    "craft_profile_no_aggregatable_craft_tags": (
        "现有媒体分析没有形成可汇总的拍摄标签，暂时无法提炼稳定拍法。"
    ),
    "no_pattern_met_minimum_support": (
        "当前没有规律获得足够样本支持，系统未生成可直接执行的规律。"
    ),
    "patterns_use_public_interaction_proxy_not_view_efficiency": (
        "当前规律依据公开互动的账号内相对排序，不等同于播放效率。"
    ),
    "pattern_performance_basis_unavailable": ("缺少可比较的表现指标，当前无法建立强弱样本对照。"),
    "patterns_are_observations_or_associations_not_causal_rules": (
        "报告中的规律属于观察或统计关联，不代表因果关系。"
    ),
    "no_phase4_pattern_is_a_level4_validated_rule": (
        "当前没有经过最高等级验证的规律，采用前仍需小范围实验。"
    ),
    "comment_sample_partial": "评论样本不完整，评论洞察只代表当前可见样本。",
    "comment_labels_include_low_confidence_fallbacks": (
        "部分评论标签来自低置信度备用识别，建议抽样复核。"
    ),
    "comment_unknown_intent_rate_high": ("评论意图未识别比例较高，建议补充模型识别或人工复核。"),
    "direct_identifiers_redacted_from_analysis_copy": ("分析副本已隐藏评论用户的直接身份信息。"),
    "部分视频缺少指标快照，相关汇总保留为 null。": (
        "部分视频缺少指标快照，相关汇总明确标记为“缺失”，不会按 0 计算。"
    ),
    "部分视频尚未计算 DerivedMetrics，表现对照覆盖不完整。": (
        "部分视频尚未计算派生表现指标，强弱表现对照覆盖不完整。"
    ),
    "数据包含 Robust Z-score 异常样本，报告保留但单独标记。": (
        "数据包含按稳健标准分识别的异常样本，报告予以保留并单独标记。"
    ),
    "Phase 2 使用 content_type 作为内容支柱代理；语义内容支柱将在 Phase 3 标注。": (
        "当前报告使用已清洗的内容类型作为临时方向；完成语义分析后会改用语义内容方向。"
    ),
}


_TECHNICAL_ERROR_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"insufficient[_ ]quota|quota.*(?:exhaust|limit)", re.IGNORECASE),
        "模型账户额度不足，请补充额度或切换可用模型后重试。",
    ),
    (
        re.compile(r"invalid[_ ]api[_ ]key|unauthori[sz]ed|\b401\b", re.IGNORECASE),
        "模型密钥无效或没有调用权限，请在设置中更新密钥后重试。",
    ),
    (
        re.compile(r"forbidden|permission|\b403\b", re.IGNORECASE),
        "当前模型或知识库权限不足，请检查账号授权范围。",
    ),
    (
        re.compile(r"timed?\s*out|timeout", re.IGNORECASE),
        "模型服务响应超时，请检查网络后重试；长视频可适当延长超时时间。",
    ),
    (
        re.compile(r"schema|validation|invalid json|json decode", re.IGNORECASE),
        "模型返回的结构不符合要求，系统已尝试修复；建议切换结构化输出更稳定的模型后重试。",
    ),
    (
        re.compile(r"connection|network|name resolution|urlerror", re.IGNORECASE),
        "无法连接模型服务，请检查网络、服务地址和本地代理后重试。",
    ),
    (
        re.compile(r"provider.*unavailable|no .*provider.*configured", re.IGNORECASE),
        "尚未配置可用的模型服务，系统只能使用本地规则整理。",
    ),
)


def _string_value(value: Any) -> str:
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def display_label(value: Any) -> str:
    """Translate a stable enum/code when it is shown to an operator."""

    text = _string_value(value)
    if text in {"S", "A", "B", "C", "D"}:
        return f"{text} 档"
    return REPORT_LABELS.get(text.casefold(), text)


def display_text(value: Any) -> str:
    """Translate known machine tokens embedded in otherwise readable text."""

    text = _string_value(value)
    if not text:
        return text
    direct = REPORT_LABELS.get(text.casefold())
    if direct is not None:
        return direct
    for phrase, translated in REPORT_TEXT_PHRASES.items():
        text = re.sub(re.escape(phrase), translated, text, flags=re.IGNORECASE)
    for key, translated in sorted(REPORT_LABELS.items(), key=lambda item: -len(item[0])):
        if not re.fullmatch(r"[a-z0-9_]+", key):
            continue
        text = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])",
            translated,
            text,
            flags=re.IGNORECASE,
        )
    return text


def display_warning(value: Any) -> str:
    """Turn a warning code or raw provider error into an actionable Chinese note."""

    text = _string_value(value)
    if not text:
        return "未提供具体告警原因，请查看任务详情。"
    direct = REPORT_WARNING_MESSAGES.get(text)
    if direct is not None:
        return direct
    if text.startswith("Input hash already imported; no files were changed."):
        if "Existing provenance is unknown" in text:
            return (
                "该输入文件此前已导入，本次未修改项目文件；原记录的数据来源层级未知，"
                "系统没有覆盖其来源信息。"
            )
        return "该输入文件此前已导入，本次未修改项目文件。"
    if match := re.fullmatch(r"comment_collection_degraded:(\d+)", text):
        return f"有 {match.group(1)} 条评论在采集或解析时未完整处理，评论洞察覆盖不完整。"
    if match := re.fullmatch(r"video_knowledge_failed:(.+)", text):
        return f"视频 {match.group(1)} 的知识提炼失败，请查看跳过清单后重试。"
    if match := re.fullmatch(r"growth_fields_unavailable:(.+)", text):
        fields = "、".join(part for part in match.group(1).split(",") if part)
        return f"账号增长字段暂不可用（{fields or '未注明字段'}），相关趋势不参与结论。"
    if text.startswith("small_sample:"):
        return "视频样本少于 30 条，只能形成描述性观察，不能直接视为稳定规律。"
    if text.startswith("missing_derived_metrics:"):
        return "部分视频缺少派生表现指标，分层抽样和强弱表现对照不完整。"
    if text.startswith("promoted_content_present:"):
        return "样本包含广告或投流内容，相关表现不能直接归因于内容本身。"
    if text.startswith("missing_publish_time:"):
        return "部分视频缺少发布时间，近期样本覆盖可能不完整。"
    if match := re.match(r"sampling_gap: performance band (.+) is not represented", text):
        return f"抽样未覆盖表现等级 {match.group(1)}，分层对照可能存在缺口。"
    if match := re.match(r"sampling_gap: major content pillar (.+) is not represented", text):
        return f"抽样未覆盖主要内容方向 {display_text(match.group(1))}，方向对照可能存在缺口。"
    if text.startswith("video_detail_degraded:"):
        parts = text.split(":", 2)
        video_id = parts[1] if len(parts) > 1 else "未标识视频"
        return f"视频 {video_id} 的详情采集不完整，系统已保留能够读取的数据。"
    if text.startswith("metadata_decode_failed:"):
        return "视频元数据读取失败，画面尺寸、时长及后续镜头判断可能不完整。"
    if text.startswith("scene_detection_failed_single_shot_fallback:"):
        return "镜头切分失败，系统已把整段视频作为单一镜头继续处理。"
    if text.startswith("keyframe_extraction_failed:"):
        return "部分镜头的代表画面提取失败，视觉分析可能遗漏这些镜头。"
    if text.startswith("audio_analysis_failed:"):
        return "声音分析失败，报告已保留画面和文本结果。"
    if text.startswith("vision_schema:"):
        return "视觉模型返回的结构不完整，系统已保留能够验证的画面结果。"
    if text.startswith("baseline_snapshot_age_mismatch:"):
        return "部分历史快照的观察时长不一致，预测基线的可比性已下调。"
    if text.startswith("prediction_metric_insufficient_sample:"):
        return "部分预测指标的历史样本不足，未纳入本次预测区间。"
    if text.startswith("snapshot_age_outside_target_tolerance:"):
        return "实际快照时间偏离目标观察时点，复盘结论仅供参考。"
    if text.startswith("cross_platform_accounts_excluded_from_interaction_ranking:"):
        return "跨平台账号已从互动排序中排除，避免直接比较不同平台的原始指标。"
    if text.startswith("cross_platform_baselines_kept_separate:"):
        return "跨平台基线已单独保留，不与目标平台的原始表现直接合并。"
    for pattern, message in _TECHNICAL_ERROR_RULES:
        if pattern.search(text):
            return message
    if re.search(r"[\u4e00-\u9fff]", text):
        return display_text(text)
    return "处理过程中出现技术异常，系统已保留可用结果；请打开任务详情查看原因并重试。"


def create_report_environment(
    *,
    trim_blocks: bool = False,
    lstrip_blocks: bool = False,
) -> Environment:
    """Create the shared strict Jinja environment used by Markdown reports."""

    environment = Environment(
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=trim_blocks,
        lstrip_blocks=lstrip_blocks,
    )
    environment.filters.update(
        report_label=display_label,
        report_text=display_text,
        report_warning=display_warning,
    )
    return environment


def render_report_template(path: Path, **context: Any) -> str:
    """Render one Markdown template with the shared Chinese display filters."""

    template = create_report_environment().from_string(path.read_text(encoding="utf-8"))
    return template.render(**context)
