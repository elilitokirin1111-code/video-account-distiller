from __future__ import annotations

from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.models import AccountDistillation, MediaFeatureRecord
from video_account_distiller.sampling.dataset import load_account_dataset
from video_account_distiller.storage.parquet import write_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import read_json


def _craft_feature(video_id: str, *, band: str, index: int) -> MediaFeatureRecord:
    high = band in {"S", "A"}
    low = band in {"C", "D"}
    if high:
        movement = ["手持"]
    elif low:
        movement = ["固定机位"] + (["手持"] if index % 4 == 0 else [])
    else:
        movement = ["摇镜"]
    return MediaFeatureRecord(
        record_id=f"mdf_craft_{index}",
        media_feature_id=f"mdf_craft_{index}",
        analysis_id=f"mda_craft_{index}",
        video_id=video_id,
        media_hash=f"{index:064x}",
        duration_ms=9000,
        width=1080,
        height=1920,
        shot_count=6,
        keyframe_count=6,
        average_shot_duration_ms=1200.0 if high else 2600.0,
        silence_ratio=0.1,
        rms_dbfs=-20.0,
        ocr_observation_count=1,
        visual_annotation_count=2,
        visual_labels=["酒店客房"],
        dominant_colors=["暖金色"],
        visual_style_tags=[],
        text_overlay_style_tags=["大字标题"] if high else [],
        motion_graphic_tags=[],
        branding_tags=[],
        shot_scale_tags=["特写", "近景"] if high else ["全景"],
        camera_movement_tags=movement,
        camera_angle_tags=["平视"],
        composition_tags=["居中构图"] if high else [],
        lighting_tags=["自然光"] if high else ["暖光"],
        opening_technique_tags=["特写开场"] if high else (["开场即出字幕"] if low else []),
        pacing_tags=["快节奏剪辑"] if high else ["中等节奏剪辑"],
        analysis_status="complete",
        analysis_path=f"analyses/media/{video_id}/mda_craft_{index}/media-analysis.json",
        source_platform="douyin",
        source_type="local_media",
        source_uri=None,
        source_record_id="source",
        collected_at=None,
        run_id="run_craft",
        raw_hash=f"{index:064x}",
        data_quality_flags=[],
    )


def test_craft_distillation_mines_shooting_technique_patterns(
    phase4_project: ProjectLayout,
) -> None:
    from video_account_distiller.utils.ids import stable_id

    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    dataset = load_account_dataset(phase4_project, account_id)
    features = [
        _craft_feature(
            record.video.video_id,
            band=record.derived.performance_band if record.derived else "B",
            index=index,
        )
        for index, record in enumerate(dataset.records)
    ]
    assert len(features) >= 20
    write_models(phase4_project.normalized_dir / "media_features.parquet", features)

    payload = AccountDistillationService(phase4_project).distill(
        account_id=account_id, dry_run=True
    )["distillation"]
    result = AccountDistillation.model_validate(payload)

    craft = result.craft_profile
    assert craft is not None
    assert craft.analyzed_media_count == len(features)
    assert craft.annotated_media_count == len(features)
    assert craft.editing_rhythm is not None
    assert craft.editing_rhythm.median_shot_duration_ms is not None
    movement = {item.tag: item for item in craft.categories["camera_movement"]}
    assert movement["手持"].video_count >= 3
    assert movement["固定机位"].video_count >= 3
    assert any("运镜手法" in line or "招牌拍法" in line for line in craft.signature_style)

    craft_patterns = [item for item in result.patterns if item.pattern_type == "craft"]
    assert craft_patterns, "craft patterns must be mined from vision craft tags"
    hand_held = [
        item
        for item in craft_patterns
        if item.feature_conditions.get("craft_category") == "camera_movement"
        and item.feature_conditions.get("feature_value") == "手持"
    ]
    assert hand_held, "hand-held camera pattern must exist"
    pattern = hand_held[0]
    assert pattern.support_count >= 3
    assert pattern.counterexample_video_ids
    assert pattern.replicability == "high"
    assert "高表现" in pattern.name or pattern.support_video_ids
    # Every craft pattern must cite evidence.
    all_evidence_ids = [eid for item in result.patterns for eid in item.evidence_ids]
    assert all_evidence_ids

    assert any("运镜手法" in line for line in result.positioning.visual_and_audio_identity)
    assert not any(warning.startswith("craft_profile") for warning in result.warnings), (
        "annotated media is sufficient, no craft coverage warning expected"
    )

    dry = AccountDistillationService(phase4_project).distill(account_id=account_id, dry_run=True)
    assert dry["distillation"]["craft_profile"]["annotated_media_count"] == len(features)


def test_craft_distillation_report_and_knowledge_profile_include_craft(
    phase4_project: ProjectLayout,
) -> None:
    from video_account_distiller.utils.ids import stable_id

    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    dataset = load_account_dataset(phase4_project, account_id)
    features = [
        _craft_feature(
            record.video.video_id,
            band=record.derived.performance_band if record.derived else "B",
            index=index,
        )
        for index, record in enumerate(dataset.records)
    ]
    write_models(phase4_project.normalized_dir / "media_features.parquet", features)

    service = AccountDistillationService(phase4_project)
    result = service.distill(account_id=account_id)
    assert result["ok"] is True

    report = read_json(phase4_project.root / result["outputs"][0])
    assert report["craft_profile"] is not None
    markdown = (phase4_project.root / result["outputs"][1]).read_text(encoding="utf-8")
    assert "## 拍摄手法与表现形式画像" in markdown
    assert "景别" in markdown
    assert "运镜手法" in markdown

    profile_md = (
        phase4_project.root / "knowledge-base" / "accounts" / f"{account_id}.md"
    ).read_text(encoding="utf-8")
    assert "Craft signature:" in profile_md
