"""Project-level integrity and schema validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from video_account_distiller.models import (
    BlindContentAnalysis,
    DataQualityIssue,
    SingleVideoAnalysis,
    VideoAnalysisEvidenceIndex,
)
from video_account_distiller.normalization.pipeline import MODEL_BY_ENTITY
from video_account_distiller.quality import QualityReport, write_quality_report
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import read_json

PERFORMANCE_KEYS = {
    "views",
    "likes",
    "comments",
    "shares",
    "saves",
    "performance_score",
    "performance_band",
    "engagement_rate_by_view",
    "completion_efficiency",
    "is_promoted",
}


def _validate_staging(path: Path, model_type: type[BaseModel]) -> list[str]:
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            model_type.model_validate_json(line)
        except ValidationError as exc:
            errors.append(f"{path.name}:{line_number}: {exc}")
    return errors


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found.update(_nested_keys(item))
        return found
    if isinstance(value, list):
        list_found: set[str] = set()
        for item in value:
            list_found.update(_nested_keys(item))
        return list_found
    return set()


def _analysis_segment_ids(analysis: SingleVideoAnalysis) -> set[str]:
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


def _validate_video_analysis(path: Path, project: ProjectLayout) -> list[str]:
    errors: list[str] = []
    directory = path.parent
    expected_paths = {
        "report": directory / "report.md",
        "blind": directory / "blind-analysis.json",
        "evidence": directory / "evidence-index.json",
        "warnings": directory / "warnings.json",
    }
    missing = [name for name, item in expected_paths.items() if not item.is_file()]
    if missing:
        return [f"{project.relative(path)}: missing artifacts: {', '.join(sorted(missing))}"]
    try:
        analysis = SingleVideoAnalysis.model_validate(read_json(path))
        blind_payload = read_json(expected_paths["blind"])
        forbidden = sorted(PERFORMANCE_KEYS.intersection(_nested_keys(blind_payload)))
        if forbidden:
            return [
                f"{project.relative(path)}: blind analysis contains performance fields: {forbidden}"
            ]
        blind = BlindContentAnalysis.model_validate(blind_payload)
        evidence = VideoAnalysisEvidenceIndex.model_validate(read_json(expected_paths["evidence"]))
        warnings = read_json(expected_paths["warnings"])
    except (OSError, ValueError, ValidationError) as exc:
        return [f"{project.relative(path)}: {exc}"]

    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        errors.append("warnings.json must contain a JSON array of strings")
    if analysis.analysis_id != directory.name:
        errors.append("analysis_id does not match its content-addressed directory")
    if analysis.video_id != directory.parent.name:
        errors.append("video_id does not match its analysis directory")
    if analysis.blind_analysis != blind:
        errors.append("embedded blind analysis differs from blind-analysis.json")
    if evidence.analysis_id != analysis.analysis_id or evidence.video_id != analysis.video_id:
        errors.append("evidence index identity does not match analysis.json")
    missing_segments = sorted(_analysis_segment_ids(analysis) - set(evidence.segment_to_evidence))
    if missing_segments:
        errors.append(
            f"analysis references transcript segments without evidence: {missing_segments}"
        )
    evidence_ids = {item.evidence_id for item in evidence.items}
    missing_evidence = sorted(
        set(analysis.performance_context.evidence_ids.values()) - evidence_ids
    )
    if missing_evidence:
        errors.append(f"performance context references missing evidence: {missing_evidence}")
    expected_declared = {
        "blind_analysis_path": project.relative(expected_paths["blind"]),
        "evidence_index_path": project.relative(expected_paths["evidence"]),
        "warnings_path": project.relative(expected_paths["warnings"]),
    }
    for field, expected in expected_declared.items():
        if getattr(analysis, field) != expected:
            errors.append(f"{field} does not point to the colocated artifact")
    return [f"{project.relative(path)}: {message}" for message in errors]


def validate_project(project: ProjectLayout) -> QualityReport:
    """Verify raw hashes, schemas, and Phase 3 analysis evidence boundaries."""

    state = project.load_state()
    input_hashes = sorted({receipt.raw_hash for receipt in state.imports})
    manifest = project.begin_run("validate", input_hashes=input_hashes)
    issues: list[DataQualityIssue] = []
    platforms = {receipt.platform for receipt in state.imports}

    for receipt in state.imports:
        raw_path = project.root / receipt.raw_path
        if not raw_path.is_file() or sha256_file(raw_path) != receipt.raw_hash:
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, receipt.raw_hash, "integrity"),
                    run_id=manifest.run_id,
                    severity="error",
                    code="raw_integrity",
                    entity=receipt.entity,
                    message=f"Raw input missing or hash mismatch: {receipt.raw_path}",
                    raw_hash=receipt.raw_hash,
                )
            )

    for entity, model_type in MODEL_BY_ENTITY.items():
        for path in sorted((project.root / "staging" / entity).glob("*.jsonl")):
            for message in _validate_staging(path, model_type):
                issues.append(
                    DataQualityIssue(
                        issue_id=stable_id("dqi_", manifest.run_id, entity, message),
                        run_id=manifest.run_id,
                        severity="error",
                        code="schema_invalid",
                        entity=entity,
                        message=message,
                    )
                )

    model_output_paths = sorted((project.root / "raw" / "model-outputs").glob("*.json"))
    for path in model_output_paths:
        if sha256_file(path) != path.stem:
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, str(path), "integrity"),
                    run_id=manifest.run_id,
                    severity="error",
                    code="raw_integrity",
                    entity="model_outputs",
                    message=f"Raw model output hash mismatch: {project.relative(path)}",
                )
            )

    analysis_paths = sorted((project.root / "analyses" / "videos").glob("*/*/analysis.json"))
    for path in analysis_paths:
        for message in _validate_video_analysis(path, project):
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, project.relative(path), message),
                    run_id=manifest.run_id,
                    severity="error",
                    code="analysis_artifact_invalid",
                    entity="video_analyses",
                    message=message,
                )
            )

    warnings: list[str] = []
    if len(platforms) > 1:
        warnings.append(
            "Multiple platforms are present. Raw metrics are not directly comparable; "
            "use account-local normalized metrics."
        )
    report = QualityReport(
        run_id=manifest.run_id,
        entity="project",
        input_hashes=input_hashes,
        stats={
            "imports": len(state.imports),
            "model_outputs": len(model_output_paths),
            "platforms": len(platforms),
            "video_analyses": len(analysis_paths),
            "errors": sum(issue.severity == "error" for issue in issues),
            "warnings": sum(issue.severity == "warning" for issue in issues) + len(warnings),
        },
        issues=issues,
        warnings=warnings,
    )
    report_paths = write_quality_report(report, project.runs_dir / manifest.run_id)
    project.finish_run(
        manifest,
        success=report.error_count == 0,
        processed_counts=report.stats,
        output_files=[project.relative(path) for path in report_paths],
        warnings=warnings,
        errors=[issue.message for issue in issues if issue.severity == "error"],
    )
    return report
