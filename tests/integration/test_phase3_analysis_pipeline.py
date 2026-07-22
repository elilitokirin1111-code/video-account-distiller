from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.models import (
    SingleVideoAnalysis,
    VideoAnalysisEvidenceIndex,
)
from video_account_distiller.status import project_status
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import read_json
from video_account_distiller.validation import validate_project


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found.update(_keys(item))
        return found
    if isinstance(value, list):
        list_found: set[str] = set()
        for item in value:
            list_found.update(_keys(item))
        return list_found
    return set()


def _semantic_segment_ids(analysis: SingleVideoAnalysis) -> set[str]:
    semantics = analysis.blind_analysis.semantics
    found = set(semantics.primary_pillar_evidence_segment_ids)
    found.update(semantics.hook.evidence_segment_ids)
    found.update(semantics.cta.evidence_segment_ids)
    for segment in semantics.structure_segments:
        found.update(segment.evidence_segment_ids)
    for point in semantics.emotion_timeline:
        found.update(point.evidence_segment_ids)
    for fact in analysis.blind_analysis.facts.facts:
        found.update(fact.evidence_segment_ids)
    return found


def test_transcript_import_is_normalized_and_idempotent(
    phase3_project: ProjectLayout,
) -> None:
    status = project_status(phase3_project)
    assert status["imports"]["by_entity"]["transcripts"] == 1
    assert status["normalized"]["transcripts"] == 4
    assert status["last_transcript_at"] is not None


def test_blind_analysis_outputs_are_traceable_and_content_addressed(
    phase3_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    video_id = stable_id("vid_", "douyin", "p2-01")
    raw_before = {
        path.relative_to(phase3_project.root): path.read_bytes()
        for path in (phase3_project.root / "raw").rglob("*")
        if path.is_file()
    }
    model_output = fixtures_dir / "phase3" / "model-output-retry.json"
    service = VideoAnalysisService(phase3_project)
    result = service.analyze(
        video_id=video_id,
        model_output=model_output,
        max_attempts=2,
    )
    outputs = [phase3_project.root / Path(path) for path in result["outputs"]]
    assert all(path.is_file() for path in outputs)
    analysis = SingleVideoAnalysis.model_validate(read_json(outputs[0]))
    evidence = VideoAnalysisEvidenceIndex.model_validate(read_json(outputs[3]))
    blind_payload = read_json(outputs[2])

    assert analysis.status == "complete"
    assert analysis.blind_analysis.blind_to_performance is True
    assert not {
        "views",
        "likes",
        "performance_score",
        "performance_band",
        "engagement_rate_by_view",
        "completion_efficiency",
        "is_promoted",
    }.intersection(_keys(blind_payload))
    assert _semantic_segment_ids(analysis) <= set(evidence.segment_to_evidence)
    assert set(analysis.performance_context.evidence_ids.values()) <= {
        item.evidence_id for item in evidence.items
    }
    assert all(source.raw_hash for item in evidence.items for source in item.sources)
    report_text = outputs[1].read_text(encoding="utf-8")
    assert "单视频文本拆解报告" in report_text
    assert "盲分析声明" in report_text
    assert "不证明任何内容标签导致" in report_text
    assert "single_video_analysis_not_account_rule" in analysis.warnings

    repeated = service.analyze(
        video_id=video_id,
        model_output=model_output,
        max_attempts=2,
    )
    assert repeated["already_generated"] is True
    assert repeated["analysis"]["analysis_id"] == analysis.analysis_id
    for relative, content in raw_before.items():
        assert (phase3_project.root / relative).read_bytes() == content
    raw_model_outputs = list((phase3_project.root / "raw" / "model-outputs").glob("*.json"))
    assert len(raw_model_outputs) == 1
    assert json.loads(raw_model_outputs[0].read_text(encoding="utf-8"))["model_name"]

    status = project_status(phase3_project)
    assert status["artifacts"]["video_analyses"] == 1
    assert status["last_video_analysis_at"] is not None

    validated = validate_project(phase3_project)
    assert validated.error_count == 0
    assert validated.stats["video_analyses"] == 1
    assert validated.stats["model_outputs"] == 1


def test_validation_detects_performance_leak_in_blind_artifact(
    phase3_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    result = VideoAnalysisService(phase3_project).analyze(
        video_id="p2-01",
        model_output=fixtures_dir / "phase3" / "model-output-retry.json",
        max_attempts=2,
    )
    blind_path = phase3_project.root / result["outputs"][2]
    blind_payload = read_json(blind_path)
    blind_payload["views"] = 123
    blind_path.write_text(
        json.dumps(blind_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    validated = validate_project(phase3_project)
    assert validated.error_count == 1
    assert validated.issues[0].code == "analysis_artifact_invalid"
    assert "performance fields" in validated.issues[0].message


def test_missing_provider_degrades_without_strong_conclusions(
    phase3_project: ProjectLayout,
) -> None:
    result = VideoAnalysisService(phase3_project).analyze(
        video_id=stable_id("vid_", "douyin", "p2-01"),
        dry_run=True,
    )
    analysis = SingleVideoAnalysis.model_validate(result["analysis"])
    assert analysis.status == "degraded"
    assert analysis.blind_analysis.semantics.confidence <= 0.2
    assert analysis.blind_analysis.semantics.primary_pillar == "unknown"
    assert "single_video_analysis_not_account_rule" in analysis.warnings
    assert all("validated_rule" not in warning for warning in analysis.warnings)
