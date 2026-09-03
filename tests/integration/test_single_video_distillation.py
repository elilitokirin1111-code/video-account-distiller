from __future__ import annotations

import json
from array import array
from pathlib import Path

import pytest
from pydantic import BaseModel

import video_account_distiller.distillation.video as video_distillation_module
from video_account_distiller.distillation.account_knowledge import (
    AccountVideoKnowledgeService,
    _title_document_stem,
)
from video_account_distiller.distillation.knowledge import SingleVideoKnowledgeService
from video_account_distiller.distillation.video import SingleVideoDistillationService
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.media import LocalMediaAnalysisService, SceneDetectionResult
from video_account_distiller.models import (
    AccountVideoKnowledgeManifest,
    MediaMetadata,
    MediaVisionAnnotation,
    MediaVisionBundle,
    ShotVisualAnnotation,
    SingleVideoDistillation,
    SingleVideoKnowledgeDistillation,
    Video,
)
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import read_json
from video_account_distiller.validation import validate_project


class FixtureMediaBackend:
    available = True
    name = "fixture-ffmpeg"
    version = "1"

    def probe(self, source: Path, media_hash: str) -> MediaMetadata:
        return MediaMetadata(
            media_hash=media_hash,
            container="mp4",
            duration_ms=9000,
            width=1080,
            height=1920,
            frame_rate=25,
            video_codec="h264",
            audio_codec="aac",
            audio_channels=1,
            audio_sample_rate=8000,
            file_size_bytes=source.stat().st_size,
            backend=self.name,
            backend_version=self.version,
        )

    def detect_scenes(
        self, source: Path, *, duration_ms: int, threshold: float, max_shots: int
    ) -> SceneDetectionResult:
        del source, duration_ms, threshold, max_shots
        return SceneDetectionResult([0, 2000, 5000, 9000], [])

    def extract_frame(self, source: Path, *, timestamp_ms: int, width: int, output: Path) -> None:
        del source, width
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"jpeg-{timestamp_ms}".encode())

    def decode_audio_pcm(self, source: Path, *, sample_rate: int, max_seconds: int) -> bytes:
        del source, sample_rate, max_seconds
        return array("h", [1200] * 72_000).tobytes()


class FixtureVisionProvider:
    provider_name = "fixture-vision"
    model_name = "fixture-v1"

    def __init__(self) -> None:
        self.raw_responses: list[dict[str, object]] = []

    @property
    def input_hash(self) -> str | None:
        return None

    def analyze(self, bundle: MediaVisionBundle) -> MediaVisionAnnotation:
        annotations = []
        for index, shot in enumerate(bundle.shots):
            annotations.append(
                ShotVisualAnnotation(
                    annotation_id=f"ann_{index}",
                    shot_id=shot.shot_id,
                    summary=f"镜头{index}",
                    labels=[],
                    shot_scale=["特写"] if index == 0 else ["全景"],
                    camera_movement=["手持"] if index == 0 else ["固定机位"],
                    camera_angle=["平视"],
                    composition=["居中构图"] if index == 0 else ["对称构图"],
                    lighting=["自然光"],
                    text_overlay_styles=["大字标题"] if index == 0 else [],
                    ocr_observation_ids=[],
                )
            )
        return MediaVisionAnnotation(shot_annotations=annotations, ocr_observations=[])


def _deep_candidate() -> dict[str, object]:
    return {
        "executive_summary": {
            "one_sentence": "用客诉场景切入，拆解酒店前台的三步处理法。",
            "detailed_summary": (
                "视频先提出酒店前台常见的客诉难题，再依次说明确认诉求、给出方案和"
                "跟进结果三个步骤，最后提醒从业者把流程落实到服务话术。"
            ),
            "core_message": "客诉处理要先理解问题，再给方案并闭环跟进。",
            "content_goal": "教育酒店一线人员掌握客诉处理流程",
            "target_viewer": ["酒店前台", "店长"],
            "viewer_takeaways": ["三步客诉处理法", "服务话术需要形成闭环"],
        },
        "structure_breakdown": [
            {
                "sequence": 1,
                "role": "hook",
                "start_ms": 0,
                "end_ms": 2000,
                "content_summary": "提出客诉处理难题",
                "creative_purpose": "快速点名一线工作痛点",
                "expression": "口播提问",
                "visual": "特写、大字标题",
                "audio": "口播；BGM 未见可靠输入",
                "pacing": "开场快速进入主题",
                "emotion": "紧张感",
                "transition": "转入三步处理流程",
                "evidence_segment_ids": [],
                "evidence_shot_ids": [],
            },
            {
                "sequence": 2,
                "role": "development",
                "start_ms": 2000,
                "end_ms": 9000,
                "content_summary": "依次说明确认、方案与跟进",
                "creative_purpose": "交付可执行的方法",
                "expression": "清单式讲解",
                "visual": "全景与固定机位",
                "audio": "口播；BGM 未见可靠输入",
                "pacing": "按步骤推进",
                "emotion": "信任感",
                "transition": "用执行提醒收束",
                "evidence_segment_ids": [],
                "evidence_shot_ids": [],
            },
        ],
        "topic": {
            "topic_statement": "一条关于酒店客诉处理的深度拆解",
            "topic_angle": "痛点切入：先讲客诉场景",
            "target_audience": ["酒店前台", "店长"],
            "information_increment": "完整服务流程与话术",
            "memory_point": "三步处理法",
            "topic_formula": "痛点场景 + 流程拆解",
            "selection_notes": ["选材：真实工作场景"],
        },
        "expression": {
            "opening_form": "口播提问开场",
            "subtitle_style": "大字标题",
            "packaging_features": ["进度条贴纸"],
            "audio_expression": "口播 + 轻快 BGM",
            "editing_style": "快节奏切换",
            "expression_notes": [],
        },
        "craft": {
            "shot_scale_profile": "特写为主",
            "camera_profile": "手持跟拍",
            "composition_profile": "居中构图",
            "lighting_profile": "自然光",
            "opening_technique": "特写开场",
            "pacing": "快节奏剪辑",
            "craft_notes": [],
        },
        "copy_checklist": {
            "topic": ["客诉场景切入", "流程拆解"],
            "structure": ["问题-流程-结果"],
            "craft": ["手持跟拍"],
            "expression": ["大字标题"],
            "avoid": ["避免空泛说教"],
        },
        "strengths": [
            {
                "finding": "痛点明确且方法可执行",
                "why_it_matters": "受众能快速判断内容与自己的工作是否相关。",
                "evidence_segment_ids": [],
                "evidence_shot_ids": [],
            }
        ],
        "weaknesses": [
            {
                "finding": "结果证明不足",
                "why_it_matters": "现有输入没有案例结果，方法可信度仍需验证。",
                "evidence_segment_ids": [],
                "evidence_shot_ids": [],
            }
        ],
        "priority_improvements": [
            {
                "priority": 1,
                "problem": "缺少案例结果",
                "action": "下一版加入一个客诉处理前后对比案例。",
                "expected_effect": "增强方法的可理解性，实际表现需上线验证。",
                "evidence_segment_ids": [],
                "evidence_shot_ids": [],
            }
        ],
        "evaluation": {
            "score_basis": "model_assessment",
            "overall_score": 99,
            "rating": "优先复刻候选",
            "score_confidence": "high",
            "evidence_coverage": 1,
            "verdict": "结构清晰且易于执行，但案例证明需要增强。",
            "replicability": "high",
            "dimensions": [
                {
                    "dimension": dimension,
                    "score": score,
                    "weight": 1,
                    "rationale": "fixture evidence",
                    "evidence_segment_ids": [],
                    "evidence_shot_ids": [],
                }
                for dimension, score in [
                    ("topic", 8.0),
                    ("hook", 7.0),
                    ("content_value", 8.0),
                    ("structure", 8.0),
                    ("expression", 7.0),
                    ("visual_craft", 7.0),
                    ("pacing", 7.0),
                    ("audio_packaging", 6.0),
                    ("emotion", 6.0),
                    ("conversion", 5.0),
                ]
            ],
        },
        "unknowns": [],
        "evidence_segment_ids": [],
        "evidence_shot_ids": [],
    }


def _write_deep_output(path: Path, candidate: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"model_name": "fixture-deep", "single_video_deep_distillation": [candidate]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _analyze_text(project: ProjectLayout) -> None:
    VideoAnalysisService(project).analyze(video_id="p2-01")


def test_single_video_deep_distillation_full_chain_with_model(
    phase3_project: ProjectLayout, tmp_path: Path
) -> None:
    _analyze_text(phase3_project)
    source = tmp_path / "hotel.mp4"
    source.write_bytes(b"offline-hotel-media")
    LocalMediaAnalysisService(phase3_project, backend=FixtureMediaBackend()).analyze(
        video_id="p2-01",
        file=source,
        provider=FixtureVisionProvider(),
    )
    deep_file = tmp_path / "deep.json"
    _write_deep_output(deep_file, _deep_candidate())

    result = SingleVideoDistillationService(phase3_project).distill(
        video_id="p2-01", model_output=deep_file
    )
    assert result["ok"] is True
    distillation = SingleVideoDistillation.model_validate(result["distillation"])
    assert distillation.status == "complete"
    assert distillation.deep_trace is not None
    assert distillation.deep_trace.status == "success"
    assert distillation.media_analysis_id is not None
    assert distillation.text_analysis_id is not None
    assert distillation.craft_summary.analyzed_shots == 3
    assert "特写" in distillation.craft_summary.shot_scale
    assert distillation.craft_summary.opening_techniques == ["开场大字标题", "手持开场", "特写开场"]
    assert distillation.analysis_version == "2.0.0"
    assert distillation.executive_summary is not None
    assert "三个步骤" in distillation.executive_summary.detailed_summary
    assert len(distillation.structure_breakdown) == 2
    assert distillation.topic.topic_statement == "一条关于酒店客诉处理的深度拆解"
    assert distillation.copy_checklist.topic == ["客诉场景切入", "流程拆解"]
    assert distillation.strengths[0].finding == "痛点明确且方法可执行"
    assert distillation.priority_improvements[0].priority == 1
    assert distillation.evaluation is not None
    assert distillation.evaluation.score_basis == "model_assessment"
    assert distillation.evaluation.overall_score != 99
    assert sum(item.weight for item in distillation.evaluation.dimensions) == 100
    assert not any(warning.startswith("deep_model") for warning in distillation.warnings)
    assert all(path for path in result["outputs"])
    assert all((phase3_project.root / path).is_file() for path in result["outputs"])

    report = (phase3_project.root / result["outputs"][1]).read_text(encoding="utf-8")
    assert "## 执行摘要" in report
    assert "## 综合评判" in report
    assert "## 完整创作结构拆解" in report
    assert "## 优势、短板与优先改进" in report
    assert "## 选材（为什么值得做）" in report
    assert "## 表现形式（怎么讲）" in report
    assert "## 拍摄手法（怎么拍）" in report
    assert "## 可复制清单" in report
    assert "镜头级画像" in report

    repeated = SingleVideoDistillationService(phase3_project).distill(
        video_id="p2-01", model_output=deep_file
    )
    assert repeated["already_generated"] is True
    assert repeated["distillation"]["distillation_id"] == distillation.distillation_id

    validation = validate_project(phase3_project)
    assert validation.error_count == 0


def test_single_video_deep_distillation_degrades_without_model(
    phase3_project: ProjectLayout,
) -> None:
    _analyze_text(phase3_project)
    result = SingleVideoDistillationService(phase3_project).distill(video_id="p2-01")
    distillation = SingleVideoDistillation.model_validate(result["distillation"])
    assert distillation.status == "degraded"
    assert distillation.deep_trace is not None
    assert distillation.deep_trace.status == "degraded"
    assert "deep_model_unavailable_deterministic_fallback" in distillation.warnings
    assert distillation.topic.topic_statement
    assert distillation.copy_checklist.topic
    assert distillation.executive_summary is not None
    assert distillation.structure_breakdown
    assert distillation.evaluation is not None
    assert distillation.evaluation.score_basis == "provisional_rule_score"
    assert distillation.media_analysis_id is None
    assert any("缺少本地媒体分析" in item for item in distillation.unknowns)
    assert validate_project(phase3_project, persist=False).error_count == 0


def test_single_video_deep_cache_rebuilds_incomplete_artifact(
    phase3_project: ProjectLayout,
) -> None:
    _analyze_text(phase3_project)
    service = SingleVideoDistillationService(phase3_project)
    first = service.distill(video_id="p2-01")
    report_path = phase3_project.root / first["outputs"][1]
    report_path.unlink()

    rebuilt = service.distill(video_id="p2-01")

    assert rebuilt["already_generated"] is False
    assert rebuilt["distillation"]["distillation_id"] == first["distillation"]["distillation_id"]
    assert report_path.is_file()


def test_single_video_deep_strict_mode_rejects_degraded_cache(
    phase3_project: ProjectLayout,
) -> None:
    _analyze_text(phase3_project)
    service = SingleVideoDistillationService(phase3_project)
    degraded = service.distill(video_id="p2-01")
    assert degraded["distillation"]["status"] == "degraded"

    with pytest.raises(DistillerError) as exc_info:
        service.distill(video_id="p2-01", strict_model=True)

    assert exc_info.value.code == ErrorCode.MODEL_UNAVAILABLE


def test_single_video_deep_cache_keys_provider_endpoint_and_prompt_version(
    phase3_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _analyze_text(phase3_project)

    class _FixtureCloudProvider:
        provider_name = "cloud"

        def __init__(
            self,
            *,
            model: str,
            base_url: str,
            timeout_seconds: float,
            api_key: str | None,
        ) -> None:
            del timeout_seconds, api_key
            self.model_name = model
            self.base_url = base_url.rstrip("/")

        def generate_structured(
            self,
            prompt: str,
            response_model: type[BaseModel],
            *,
            temperature: float = 0.0,
        ) -> BaseModel:
            del prompt, temperature
            return response_model.model_validate(_deep_candidate())

    monkeypatch.setattr(
        video_distillation_module,
        "CloudChatTextProvider",
        _FixtureCloudProvider,
    )
    service = SingleVideoDistillationService(phase3_project)
    endpoint_a = service.distill(
        video_id="p2-01",
        deep_provider="cloud",
        deep_model="fixture-deep",
        deep_base_url="https://endpoint-a.example/v1",
    )
    endpoint_b = service.distill(
        video_id="p2-01",
        deep_provider="cloud",
        deep_model="fixture-deep",
        deep_base_url="https://endpoint-b.example/v1",
    )
    endpoint_b_cached = service.distill(
        video_id="p2-01",
        deep_provider="cloud",
        deep_model="fixture-deep",
        deep_base_url="https://endpoint-b.example/v1",
    )

    assert (
        endpoint_a["distillation"]["distillation_id"]
        != endpoint_b["distillation"]["distillation_id"]
    )
    assert endpoint_b_cached["already_generated"] is True
    monkeypatch.setattr(
        video_distillation_module,
        "DEEP_DISTILLATION_PROMPT_VERSION",
        "single-video-deep-distillation-test-v2",
    )
    prompt_v2 = service.distill(
        video_id="p2-01",
        deep_provider="cloud",
        deep_model="fixture-deep",
        deep_base_url="https://endpoint-b.example/v1",
    )
    assert (
        prompt_v2["distillation"]["distillation_id"]
        != endpoint_b["distillation"]["distillation_id"]
    )


def test_single_video_knowledge_mode_uses_isolated_artifact_paths(
    phase3_project: ProjectLayout,
) -> None:
    _analyze_text(phase3_project)

    result = SingleVideoKnowledgeService(phase3_project).distill(video_id="p2-01")
    artifact = SingleVideoKnowledgeDistillation.model_validate(result["knowledge"])

    assert artifact.distillation_mode == "knowledge"
    assert artifact.knowledge_id.startswith("svk_")
    assert artifact.knowledge.knowledge_items
    expected_names = ["knowledge.json", "knowledge.md", "evidence.json", "warnings.json"]
    assert [Path(path).name for path in result["outputs"]] == expected_names
    assert all(f"knowledge/{artifact.knowledge_id}/" in path for path in result["outputs"])
    assert all((phase3_project.root / path).is_file() for path in result["outputs"])
    assert "external_fact_check_not_performed" in artifact.warnings

    repeated = SingleVideoKnowledgeService(phase3_project).distill(video_id="p2-01")
    assert repeated["already_generated"] is True
    assert repeated["knowledge"]["knowledge_id"] == artifact.knowledge_id


def test_account_video_knowledge_creates_one_import_document_per_eligible_video(
    phase3_project: ProjectLayout,
) -> None:
    _analyze_text(phase3_project)
    all_videos = read_models(phase3_project.normalized_dir / "videos.parquet", Video)
    target = next(item for item in all_videos if item.platform_video_id == "p2-01")
    account_videos = [item for item in all_videos if item.account_id == target.account_id]
    account_id = account_videos[0].account_id
    service = AccountVideoKnowledgeService(phase3_project)

    preview = service.distill(account_id=account_id, provider="none", dry_run=True)
    assert preview["eligible_count"] == 1
    assert len(preview["skipped"]) == len(account_videos) - 1
    assert preview["plan"]["document_shape"] == "one_markdown_per_video"

    selected_preview = service.distill(
        account_id=account_id,
        video_ids=[target.video_id],
        provider="none",
        dry_run=True,
    )
    assert selected_preview["requested_count"] == 1
    assert selected_preview["eligible_count"] == 1
    assert selected_preview["skipped"] == []

    result = service.distill(account_id=account_id, provider="none")
    manifest = AccountVideoKnowledgeManifest.model_validate(result["manifest"])
    assert manifest.requested_count == len(account_videos)
    assert manifest.eligible_count == 1
    assert len(manifest.documents) == 1
    assert manifest.skipped_count == len(account_videos) - 1
    document_path = phase3_project.root / manifest.documents[0].document_path
    document = document_path.read_text(encoding="utf-8")
    assert document.startswith("---\nsource: video-account-distiller")
    assert "document_type: video_knowledge" in document
    assert "distillation_mode: knowledge" in document
    assert "# " in document
    assert document_path.parent.name == "documents"
    assert document_path.stem != manifest.documents[0].video_id
    assert document_path.stem == _title_document_stem(target.title, target.video_id)

    repeated = service.distill(account_id=account_id, provider="none")
    assert repeated["already_generated"] is True
    assert repeated["manifest"]["manifest_id"] == manifest.manifest_id


def test_single_video_deep_distillation_uses_media_analysis_when_present(
    phase3_project: ProjectLayout, tmp_path: Path
) -> None:
    _analyze_text(phase3_project)
    source = tmp_path / "hotel.mp4"
    source.write_bytes(b"offline-hotel-media")
    LocalMediaAnalysisService(phase3_project, backend=FixtureMediaBackend()).analyze(
        video_id="p2-01",
        file=source,
        provider=FixtureVisionProvider(),
    )
    result = SingleVideoDistillationService(phase3_project).distill(video_id="p2-01")
    distillation = SingleVideoDistillation.model_validate(result["distillation"])
    assert distillation.media_analysis_id is not None
    assert distillation.craft_summary.analyzed_shots == 3
    assert "特写" in distillation.craft.shot_scale_profile
    assert distillation.status == "degraded"
    # The fallback must still surface the measured craft evidence.
    evidence = read_json(phase3_project.root / distillation.evidence_index_path)
    assert any(item["label"] == "video.craft_summary" for item in evidence["items"])
    assert validate_project(phase3_project, persist=False).error_count == 0
