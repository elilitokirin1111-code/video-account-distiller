from __future__ import annotations

from video_account_distiller.distillation.craft import (
    CRAFT_CATEGORIES,
    CRAFT_CATEGORY_LABELS,
    build_craft_profile,
)
from video_account_distiller.media.pipeline import _opening_technique_tags, _pacing_tags
from video_account_distiller.models import (
    CraftProfile,
    MediaFeatureRecord,
    Platform,
    ShotVisualAnnotation,
)


def _feature(
    video_id: str,
    *,
    shot_count: int = 4,
    average_shot_duration_ms: float = 2000.0,
    visual_annotation_count: int = 1,
    shot_scale: list[str] | None = None,
    camera_movement: list[str] | None = None,
    camera_angle: list[str] | None = None,
    composition: list[str] | None = None,
    lighting: list[str] | None = None,
    opening: list[str] | None = None,
    pacing: list[str] | None = None,
) -> MediaFeatureRecord:
    return MediaFeatureRecord(
        record_id=f"rec_{video_id}",
        media_feature_id=f"mdf_{video_id}",
        analysis_id=f"ana_{video_id}",
        video_id=video_id,
        media_hash="h" * 64,
        duration_ms=9000,
        width=1080,
        height=1920,
        shot_count=shot_count,
        keyframe_count=shot_count,
        average_shot_duration_ms=average_shot_duration_ms,
        silence_ratio=0.1,
        rms_dbfs=-20.0,
        ocr_observation_count=0,
        visual_annotation_count=visual_annotation_count,
        visual_labels=[],
        dominant_colors=[],
        visual_style_tags=[],
        text_overlay_style_tags=[],
        motion_graphic_tags=[],
        branding_tags=[],
        shot_scale_tags=shot_scale or [],
        camera_movement_tags=camera_movement or [],
        camera_angle_tags=camera_angle or [],
        composition_tags=composition or [],
        lighting_tags=lighting or [],
        opening_technique_tags=opening or [],
        pacing_tags=pacing or [],
        analysis_status="complete",
        analysis_path=f"analyses/media/{video_id}/mda_1/media-analysis.json",
        source_platform=Platform.DOUYIN,
        source_type="local_media",
        source_uri=None,
        source_record_id="source",
        collected_at=None,
        run_id="run_1",
        raw_hash="h" * 64,
        data_quality_flags=[],
    )


def test_build_craft_profile_aggregates_tags_with_coverage() -> None:
    features = [
        _feature(
            "v1",
            average_shot_duration_ms=1200.0,
            shot_scale=["特写", "近景"],
            camera_movement=["手持"],
            composition=["居中构图"],
            lighting=["自然光"],
            opening=["特写开场"],
            pacing=["快节奏剪辑"],
        ),
        _feature(
            "v2",
            average_shot_duration_ms=1000.0,
            shot_scale=["特写"],
            camera_movement=["手持"],
            lighting=["自然光"],
            opening=["特写开场"],
            pacing=["快节奏剪辑"],
        ),
        _feature(
            "v3",
            average_shot_duration_ms=900.0,
            shot_scale=["近景"],
            camera_movement=["固定机位"],
            composition=["居中构图"],
            opening=["开场大字幕"],
            pacing=["快节奏剪辑"],
        ),
    ]

    profile = build_craft_profile(features)

    assert profile.analyzed_media_count == 3
    assert profile.annotated_media_count == 3
    assert set(profile.categories) == set(CRAFT_CATEGORIES)
    assert profile.category_denominators["shot_scale"] == 3
    assert profile.category_denominators["pacing"] == 3
    shot_scale = {item.tag: item for item in profile.categories["shot_scale"]}
    assert shot_scale["特写"].video_count == 2
    assert shot_scale["特写"].video_ids == ["v1", "v2"]
    assert shot_scale["特写"].coverage == round(2 / 3, 6)
    assert shot_scale["近景"].video_count == 2
    movements = {item.tag: item for item in profile.categories["camera_movement"]}
    assert movements["手持"].video_count == 2
    assert movements["固定机位"].video_count == 1
    openings = {item.tag: item for item in profile.categories["opening_technique"]}
    assert openings["特写开场"].video_ids == ["v1", "v2"]
    assert [item.tag for item in profile.categories["pacing"]] == ["快节奏剪辑"]
    assert profile.categories["pacing"][0].coverage == 1.0

    assert profile.editing_rhythm is not None
    assert profile.editing_rhythm.analyzed_with_shots == 3
    assert profile.editing_rhythm.median_shot_duration_ms == 1000.0
    assert profile.editing_rhythm.pace_label == "快节奏剪辑"

    signature = profile.signature_style
    assert signature[0] == "剪辑节奏：快节奏剪辑（镜头时长中位数 1.0 秒）"
    assert "景别：特写（67% 覆盖）" in signature
    assert "运镜手法：手持（67% 覆盖）" in signature
    assert "招牌拍法：特写 + 手持 + 居中构图 + 自然光 + 特写开场" in signature
    # Pacing must not be repeated by the per-category loop.
    assert sum(1 for line in signature if "剪辑节奏" in line) == 1


def test_build_craft_profile_handles_empty_and_unannotated_features() -> None:
    empty = build_craft_profile([])
    assert empty.analyzed_media_count == 0
    assert empty.annotated_media_count == 0
    assert all(not summaries for summaries in empty.categories.values())
    assert empty.editing_rhythm is None
    assert empty.signature_style == []
    assert "尚无本地媒体分析，无法蒸馏拍摄手法与表现形式" in empty.unknowns

    unannotated = [
        _feature(
            "v9",
            visual_annotation_count=0,
            shot_count=10,
            average_shot_duration_ms=500.0,
            pacing=["快节奏剪辑"],
        )
    ]
    profile = build_craft_profile(unannotated)
    assert profile.analyzed_media_count == 1
    assert profile.annotated_media_count == 0
    # Vision categories stay empty without annotations; pacing is still derived
    # from measured shots with its own denominator.
    assert profile.categories["shot_scale"] == []
    assert [item.tag for item in profile.categories["pacing"]] == ["快节奏剪辑"]
    assert profile.category_denominators["pacing"] == 1
    assert profile.editing_rhythm is not None
    assert profile.editing_rhythm.pace_label == "快节奏剪辑"
    assert "尚未完成画面语义标注，无法蒸馏视觉拍摄手法与表现形式" in profile.unknowns


def test_build_craft_profile_skips_signature_below_minimum_coverage() -> None:
    features = [
        _feature("a", shot_scale=["特写"], camera_movement=["手持"]),
        _feature("b", shot_scale=["中景"], camera_movement=["推镜"]),
        _feature("c", shot_scale=["全景"], camera_movement=["摇镜"]),
        _feature("d", shot_scale=["远景"], camera_movement=["跟拍"]),
    ]
    profile = build_craft_profile(features)
    # No tag reaches 30% coverage (1/4), so no category line is promoted.
    assert not any("覆盖" in line for line in profile.signature_style)
    assert "招牌拍法" not in profile.signature_style
    assert profile.categories["shot_scale"][0].coverage == round(1 / 4, 6)


def test_pacing_and_opening_helpers_are_deterministic() -> None:
    assert _pacing_tags(1400) == ["快节奏剪辑"]
    assert _pacing_tags(1500) == ["中等节奏剪辑"]
    assert _pacing_tags(3500) == ["中等节奏剪辑"]
    assert _pacing_tags(3600) == ["慢节奏剪辑"]
    assert _pacing_tags(None) == []

    annotation = ShotVisualAnnotation(
        annotation_id="ann_1",
        shot_id="shot_1",
        shot_scale=["特写", "近景"],
        camera_movement=["手持", "跟拍"],
        text_overlay_styles=["大字标题"],
        ocr_observation_ids=["ocr_1"],
    )
    assert set(_opening_technique_tags(annotation)) == {
        "开场大字标题",
        "特写开场",
        "近景开场",
        "手持开场",
        "跟拍开场",
        "开场即出字幕",
    }
    assert _opening_technique_tags(None) == []


def test_craft_profile_schema_validates_counts() -> None:
    profile = build_craft_profile(
        [_feature("v1", shot_scale=["特写"]), _feature("v2", shot_scale=["特写"])]
    )
    CraftProfile.model_validate(profile.model_dump(mode="json"))
    for category in CRAFT_CATEGORIES:
        assert category in CRAFT_CATEGORY_LABELS
