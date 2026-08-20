from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from video_account_distiller.distillation.knowledge import (
    _fallback_knowledge,
    _validate_source_refs,
)
from video_account_distiller.distillation.video import (
    _fallback_deep_output,
    _validate_deep_output,
    build_craft_summary,
)
from video_account_distiller.features.providers import StructuredFileProvider
from video_account_distiller.media.pipeline import _opening_technique_tags, _pacing_tags
from video_account_distiller.models import (
    AudioFeatures,
    KeyframeEvidence,
    MediaAnalysis,
    MediaMetadata,
    MediaVisionAnnotation,
    ShotSegment,
    ShotVisualAnnotation,
    SingleVideoAnalysis,
    SingleVideoDeepOutput,
    TranscriptSegment,
    VisionTaskTrace,
)


def _media_analysis() -> MediaAnalysis:
    shots = [
        ShotSegment(shot_id="shot_1", index=0, start_ms=0, end_ms=1000, duration_ms=1000),
        ShotSegment(shot_id="shot_2", index=1, start_ms=1000, end_ms=3000, duration_ms=2000),
    ]
    keyframes = [
        KeyframeEvidence(
            keyframe_id="key_1",
            shot_id="shot_1",
            timestamp_ms=500,
            path="analyses/media/v/k/kf.jpg",
            sha256="1" * 64,
        ),
        KeyframeEvidence(
            keyframe_id="key_2",
            shot_id="shot_2",
            timestamp_ms=2000,
            path="analyses/media/v/k/kf2.jpg",
            sha256="2" * 64,
        ),
    ]
    vision = MediaVisionAnnotation(
        shot_annotations=[
            ShotVisualAnnotation(
                annotation_id="ann_1",
                shot_id="shot_1",
                shot_scale=["特写"],
                camera_movement=["手持"],
                camera_angle=["平视"],
                composition=["居中构图"],
                lighting=["自然光"],
                text_overlay_styles=["大字标题"],
                motion_graphics=["贴纸"],
                branding=[],
                ocr_observation_ids=[],
            ),
            ShotVisualAnnotation(
                annotation_id="ann_2",
                shot_id="shot_2",
                shot_scale=["全景", "近景"],
                camera_movement=["固定机位"],
                camera_angle=["俯视"],
                composition=["对称构图"],
                lighting=["暖光"],
                text_overlay_styles=[],
                motion_graphics=[],
                branding=["品牌名"],
                ocr_observation_ids=[],
            ),
        ],
        ocr_observations=[],
    )
    return MediaAnalysis(
        analysis_id="mda_1",
        analysis_version="1.1.1",
        video_id="vid_1",
        account_id="acc_1",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        run_id="run_1",
        status="complete",
        raw_media_path="raw/media/x.mp4",
        metadata=MediaMetadata(
            media_hash="m" * 64,
            file_size_bytes=100,
            backend="fixture",
        ),
        shots=shots,
        keyframes=keyframes,
        audio=AudioFeatures(status="complete", silence_ratio=0.1),
        vision=vision,
        vision_trace=VisionTaskTrace(
            provider="fixture", model="fixture", input_hash="h" * 64, attempts=1, status="success"
        ),
        timeline_path="analyses/media/v/mda_1/timeline.json",
        evidence_index_path="analyses/media/v/mda_1/evidence-index.json",
        warnings_path="analyses/media/v/mda_1/warnings.json",
    )


def _text_analysis() -> SingleVideoAnalysis:
    payload = {
        "analysis_id": "vta_1",
        "analysis_version": "1.3.1",
        "video_id": "vid_1",
        "account_id": "acc_1",
        "generated_at": "2026-01-01T00:00:00Z",
        "run_id": "run_1",
        "status": "complete",
        "blind_analysis_path": "blind.json",
        "evidence_index_path": "evidence.json",
        "warnings_path": "warnings.json",
        "blind_analysis": {
            "video_id": "vid_1",
            "blind_to_performance": True,
            "bundle_hash": "b" * 64,
            "facts": {
                "segment_count": 2,
                "character_count": 10,
                "opening_text": "酒店入住最容易踩的3个坑",
                "closing_text": "记得收藏",
                "facts": [{"category": "number", "text": "3个坑", "evidence_segment_ids": ["1"]}],
                "explicit_cta_texts": ["收藏"],
                "unknowns": [],
            },
            "semantics": {
                "primary_pillar": "酒店经营与运营",
                "secondary_topics": [],
                "audience_tasks": ["提升酒店经营效率"],
                "content_goal": "education",
                "funnel_stage": "consideration",
                "hook": {
                    "primary_type": "number_list",
                    "hook_text": "酒店入住最容易踩的3个坑，你知道吗？",
                    "evidence_segment_ids": ["1"],
                },
                "structure_segments": [
                    {
                        "function": "hook",
                        "start_ms": 0,
                        "end_ms": 1000,
                        "text_summary": "开场提问",
                        "evidence_segment_ids": ["1"],
                    },
                    {
                        "function": "development",
                        "start_ms": 1000,
                        "end_ms": 4000,
                        "text_summary": "三个坑讲解",
                        "evidence_segment_ids": ["1", "2"],
                    },
                ],
                "narrative_type": "list_explainer",
                "information_density": "medium",
                "emotion_timeline": [],
                "cta": {"primary_type": "save", "text": "记得收藏", "evidence_segment_ids": ["2"]},
                "persona_signals": ["酒店一线从业者"],
                "language_signals": ["中文口语化表达"],
                "risk_flags": [],
                "unknowns": [],
                "confidence": 0.8,
            },
            "task_traces": [
                {
                    "task": "video_fact_extraction",
                    "prompt_version": "v1",
                    "prompt_hash": "p" * 64,
                    "provider": "none",
                    "model": "none",
                    "attempts": 0,
                    "status": "degraded",
                    "errors": [],
                }
            ],
            "warnings": [],
        },
        "performance_context": {},
        "warnings": [],
    }
    return SingleVideoAnalysis.model_validate(payload)


def test_build_craft_summary_aggregates_shot_level_counts() -> None:
    summary = build_craft_summary(_media_analysis())

    assert summary.analyzed_shots == 2
    assert summary.shot_scale == {"特写": 1, "全景": 1, "近景": 1}
    assert summary.camera_movement == {"手持": 1, "固定机位": 1}
    assert summary.camera_angle == {"平视": 1, "俯视": 1}
    assert summary.composition == {"居中构图": 1, "对称构图": 1}
    assert summary.lighting == {"自然光": 1, "暖光": 1}
    assert summary.text_overlay_style == {"大字标题": 1}
    assert summary.motion_graphic == {"贴纸": 1}
    assert summary.branding == {"品牌名": 1}
    assert summary.average_shot_duration_ms == 1500.0
    assert summary.silence_ratio == 0.1
    # First shot: 特写 + 手持 + 大字标题 + no OCR (sorted by code point).
    assert summary.opening_techniques == ["开场大字标题", "手持开场", "特写开场"]
    assert summary.pacing_tags == ["中等节奏剪辑"]

    empty = build_craft_summary(None)
    assert empty.analyzed_shots == 0
    assert empty.shot_scale == {}
    assert empty.opening_techniques == []


def test_fallback_deep_output_organizes_observables_deterministically() -> None:
    media = _media_analysis()
    craft = build_craft_summary(media)
    output = _fallback_deep_output(_text_analysis(), media, craft)

    assert "酒店经营与运营" in output.topic.topic_statement
    assert "数字清单切入" in output.topic.topic_angle
    assert "清单式讲解" in output.topic.topic_formula
    assert output.expression.subtitle_style == "大字标题"
    assert "持续活跃" in output.expression.audio_expression
    assert output.craft.shot_scale_profile == "全景×1、特写×1、近景×1"
    assert output.craft.pacing == "中等节奏剪辑"
    assert output.copy_checklist.craft
    assert any("确定性降级" in item for item in output.unknowns)

    no_media = _fallback_deep_output(_text_analysis(), None, build_craft_summary(None))
    assert no_media.expression.subtitle_style == "未见字幕/艺术字标注"
    assert no_media.craft.shot_scale_profile == "未见标注"
    assert any("缺少本地媒体分析" in item for item in no_media.unknowns)


def test_knowledge_fallback_preserves_attribution_and_source_intervals() -> None:
    segment = TranscriptSegment(
        segment_id="1",
        video_id="vid_1",
        start_ms=100,
        end_ms=900,
        text="视频说有三个常见问题",
        source="fixture",
        record_id="tr_1",
        source_platform="douyin",
        source_type="fixture",
        source_record_id="src_1",
        raw_hash="a" * 64,
        run_id="run_1",
    )

    output = _fallback_knowledge(_text_analysis(), [segment])

    assert output.knowledge_items[0].knowledge_type == "data"
    assert output.knowledge_items[0].attribution == "video_statement"
    assert output.knowledge_items[0].source_refs[0].segment_id == "1"
    assert output.knowledge_items[0].source_refs[0].start_ms == 100
    assert "外部事实核验" in output.limitations[0]

    output.knowledge_items[0].source_refs.append(
        output.knowledge_items[0].source_refs[0].model_copy(update={"segment_id": "invented"})
    )
    _validate_source_refs(
        output,
        valid_segments={"1"},
        valid_shots=set(),
        valid_observations=set(),
    )
    assert [ref.segment_id for ref in output.knowledge_items[0].source_refs] == ["1"]


def test_deep_output_citation_filter_drops_fabricated_ids() -> None:
    media = _media_analysis()
    output = _fallback_deep_output(_text_analysis(), media, build_craft_summary(media))
    assert output.evidence_segment_ids == []
    assert output.evidence_shot_ids == []
    _validate_deep_output(output, {"1", "2"}, {"shot_1", "shot_2"})
    assert output.evidence_segment_ids == []
    assert output.evidence_shot_ids == []

    fabricated = SingleVideoDeepOutput.model_validate(
        {
            "topic": {
                "topic_statement": "s",
                "topic_angle": "a",
                "target_audience": [],
                "information_increment": "i",
                "memory_point": "m",
                "topic_formula": "f",
            },
            "expression": {
                "opening_form": "o",
                "subtitle_style": "s",
                "packaging_features": [],
                "audio_expression": "a",
                "editing_style": "e",
            },
            "craft": {
                "shot_scale_profile": "s",
                "camera_profile": "c",
                "composition_profile": "c",
                "lighting_profile": "l",
                "opening_technique": "o",
                "pacing": "p",
            },
            "copy_checklist": {
                "topic": [],
                "structure": [],
                "craft": [],
                "expression": [],
                "avoid": [],
            },
            "unknowns": [],
            "evidence_segment_ids": ["1", "fake"],
            "evidence_shot_ids": ["shot_1", "nope"],
        }
    )
    _validate_deep_output(fabricated, {"1", "2"}, {"shot_1", "shot_2"})
    assert fabricated.evidence_segment_ids == ["1"]
    assert fabricated.evidence_shot_ids == ["shot_1"]


def test_structured_file_provider_serves_deep_distillation_candidates(tmp_path: Path) -> None:
    path = tmp_path / "deep.json"
    path.write_text(
        '{"model_name": "fixture", "single_video_deep_distillation": [{'
        '"topic": {"topic_statement": "s", "topic_angle": "a", "target_audience": [], '
        '"information_increment": "i", "memory_point": "m", "topic_formula": "f"}, '
        '"expression": {"opening_form": "o", "subtitle_style": "s", "packaging_features": [], '
        '"audio_expression": "a", "editing_style": "e"}, '
        '"craft": {"shot_scale_profile": "s", "camera_profile": "c", "composition_profile": "c", '
        '"lighting_profile": "l", "opening_technique": "o", "pacing": "p"}, '
        '"copy_checklist": {}, "unknowns": []}]}',
        encoding="utf-8",
    )
    provider = StructuredFileProvider(path)
    result = provider.generate_structured("", SingleVideoDeepOutput)
    assert result.topic.topic_statement == "s"
    assert provider.input_hash is not None


def test_pacing_and_opening_helpers_agree_with_craft_summary() -> None:
    media = _media_analysis()
    summary = build_craft_summary(media)
    assert summary.pacing_tags == _pacing_tags(summary.average_shot_duration_ms)
    first_annotation = media.vision.shot_annotations[0]
    assert summary.opening_techniques == _opening_technique_tags(first_annotation)
