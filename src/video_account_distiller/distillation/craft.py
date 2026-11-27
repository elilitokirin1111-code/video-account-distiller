"""Deterministic account-level distillation of shooting techniques and expression forms.

Per-video craft tags come from the local vision model's per-shot annotations
(shot scale, camera motion, angle, composition, lighting, text overlay styles,
motion graphics, branding) plus deterministic opening-technique and
editing-rhythm tags computed in the media pipeline. This module aggregates them
into one traceable account profile whose coverage numbers can feed pattern
mining and benchmark comparisons. All calculations stay deterministic and
outside prompts; tags remain observations, never causal rules.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

from video_account_distiller.metrics.calculations import median
from video_account_distiller.models import (
    CraftEditingRhythm,
    CraftProfile,
    CraftTagSummary,
    MediaFeatureRecord,
)

# Editing-rhythm thresholds shared with the media pipeline so that per-video
# pacing tags and the account-level pace label always agree.
PACING_FAST_MS = 1_500
PACING_MEDIUM_MS = 3_500

CRAFT_CATEGORIES: tuple[str, ...] = (
    "shot_scale",
    "camera_movement",
    "camera_angle",
    "composition",
    "lighting",
    "text_overlay_style",
    "motion_graphic",
    "branding",
    "opening_technique",
    "pacing",
)

CRAFT_CATEGORY_LABELS: dict[str, str] = {
    "shot_scale": "景别",
    "camera_movement": "运镜手法",
    "camera_angle": "机位角度",
    "composition": "构图",
    "lighting": "光线",
    "text_overlay_style": "字幕与艺术字",
    "motion_graphic": "动效与贴纸",
    "branding": "品牌露出",
    "opening_technique": "开场手法",
    "pacing": "剪辑节奏",
}

# Vision-dependent categories; their coverage denominators are the number of
# media records that carry at least one visual annotation.
_VISION_CATEGORIES: frozenset[str] = frozenset(
    {
        "shot_scale",
        "camera_movement",
        "camera_angle",
        "composition",
        "lighting",
        "text_overlay_style",
        "motion_graphic",
        "branding",
        "opening_technique",
    }
)

_TAG_ATTRIBUTES: dict[str, str] = {
    "shot_scale": "shot_scale_tags",
    "camera_movement": "camera_movement_tags",
    "camera_angle": "camera_angle_tags",
    "composition": "composition_tags",
    "lighting": "lighting_tags",
    "text_overlay_style": "text_overlay_style_tags",
    "motion_graphic": "motion_graphic_tags",
    "branding": "branding_tags",
    "opening_technique": "opening_technique_tags",
    "pacing": "pacing_tags",
}

_SIGNATURE_MIN_COVERAGE = 0.3
_MAX_SIGNATURE_CATEGORY_LINES = 10


def _pace_label(median_shot_duration_ms: float | None) -> str | None:
    if median_shot_duration_ms is None:
        return None
    if median_shot_duration_ms < PACING_FAST_MS:
        return "快节奏剪辑"
    if median_shot_duration_ms <= PACING_MEDIUM_MS:
        return "中等节奏剪辑"
    return "慢节奏剪辑"


def _editing_rhythm(features: Sequence[MediaFeatureRecord]) -> CraftEditingRhythm | None:
    with_shots = [item for item in features if item.shot_count > 0]
    if not with_shots:
        return None
    durations = [
        float(item.average_shot_duration_ms)
        for item in with_shots
        if item.average_shot_duration_ms is not None
    ]
    shot_counts = [float(item.shot_count) for item in with_shots]
    return CraftEditingRhythm(
        analyzed_with_shots=len(with_shots),
        median_shot_duration_ms=median(durations),
        pace_label=_pace_label(median(durations)),
        shot_count_median=median(shot_counts),
    )


def build_craft_profile(features: Sequence[MediaFeatureRecord]) -> CraftProfile:
    """Aggregate per-video craft tags into one content-addressed account profile."""
    analyzed = list(features)
    annotated = [item for item in analyzed if item.visual_annotation_count > 0]
    analyzed_count = len(analyzed)
    annotated_count = len(annotated)
    denominators = {
        category: (annotated_count if category in _VISION_CATEGORIES else analyzed_count)
        for category in CRAFT_CATEGORIES
    }
    by_category: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for category in CRAFT_CATEGORIES:
        attribute = _TAG_ATTRIBUTES[category]
        for item in analyzed:
            tags = getattr(item, attribute)
            if not tags:
                continue
            if category in _VISION_CATEGORIES and item.visual_annotation_count == 0:
                continue
            for tag in tags:
                by_category[category][tag].add(item.video_id)

    categories: dict[str, list[CraftTagSummary]] = {}
    for category in CRAFT_CATEGORIES:
        denominator = max(denominators[category], 1)
        summaries = [
            CraftTagSummary(
                tag=tag,
                video_count=len(video_ids),
                video_ids=sorted(video_ids),
                coverage=round(len(video_ids) / denominator, 6),
            )
            for tag, video_ids in sorted(by_category[category].items())
        ]
        summaries.sort(key=lambda item: (-item.coverage, item.tag))
        categories[category] = summaries

    rhythm = _editing_rhythm(analyzed)
    signature: list[str] = []
    if rhythm is not None and rhythm.pace_label is not None:
        signature.append(
            f"剪辑节奏：{rhythm.pace_label}"
            + (
                f"（镜头时长中位数 {rhythm.median_shot_duration_ms / 1000:.1f} 秒）"
                if rhythm.median_shot_duration_ms is not None
                else ""
            )
        )
    for category in CRAFT_CATEGORIES:
        if category == "pacing":
            continue
        summaries = categories[category]
        if not summaries:
            continue
        top = summaries[0]
        if top.coverage < _SIGNATURE_MIN_COVERAGE:
            continue
        signature.append(f"{CRAFT_CATEGORY_LABELS[category]}：{top.tag}（{top.coverage:.0%} 覆盖）")
        if len(signature) >= _MAX_SIGNATURE_CATEGORY_LINES + 1:
            break
    # One compound line captures the account's signature combination, e.g.
    # 近景 + 手持 + 自然光 + 大字标题.
    combination = [
        summary.tag
        for category in CRAFT_CATEGORIES
        if category != "pacing"
        for summary in categories[category][:1]
        if summary.coverage >= 0.4
    ]
    if len(combination) >= 2:
        signature.append("招牌拍法：" + " + ".join(combination[:6]))

    unknowns: list[str] = []
    if analyzed_count == 0:
        unknowns.append("尚无本地媒体分析，无法蒸馏拍摄手法与表现形式")
    elif annotated_count == 0:
        unknowns.append("尚未完成画面语义标注，无法蒸馏视觉拍摄手法与表现形式")
    elif all(not summaries for summaries in categories.values()):
        unknowns.append("视觉标注未提供可聚合的拍摄手法标签")
    if rhythm is None:
        unknowns.append("无可用镜头时长，无法蒸馏剪辑节奏")

    coverage_balance = Counter(
        category
        for category in CRAFT_CATEGORIES
        for summary in categories[category]
        if summary.coverage >= 0.6
    )
    if len(coverage_balance) == 1:
        unknowns.append("仅单一拍摄手法维度达到高覆盖，组合表达证据有限")

    return CraftProfile(
        analyzed_media_count=analyzed_count,
        annotated_media_count=annotated_count,
        categories=categories,
        category_denominators=denominators,
        editing_rhythm=rhythm,
        signature_style=list(dict.fromkeys(signature)),
        unknowns=unknowns,
    )
