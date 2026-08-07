"""Project-level integrity and schema validation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from video_account_distiller.models import (
    AccountBenchmarkProfile,
    AccountDistillation,
    AccountMediaEnrichment,
    ArtifactEvidenceIndex,
    AuthorizedExportManifest,
    BatchResult,
    BenchmarkComparison,
    BlindContentAnalysis,
    CommentAnalysis,
    ContentCandidate,
    DataQualityIssue,
    MediaAnalysis,
    MediaEvidenceIndex,
    MediaFeatureRecord,
    Prediction,
    Publication,
    Retro,
    Rubric,
    Rule,
    RunManifest,
    ScoreResult,
    SingleVideoAnalysis,
    SnapshotScheduleResult,
    SyncReceipt,
    TeamConfig,
    VideoAnalysisEvidenceIndex,
)
from video_account_distiller.normalization.pipeline import MODEL_BY_ENTITY
from video_account_distiller.quality import QualityReport, write_quality_report
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import read_json
from video_account_distiller.validators import (
    validate_collection_batches,
    validate_openkb_artifacts,
)

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
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").split("\n"),
        start=1,
    ):
        line = line.rstrip("\r")
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


def _validate_media_analysis(path: Path, project: ProjectLayout) -> list[str]:
    errors: list[str] = []
    directory = path.parent
    expected = {
        "timeline": directory / "timeline.json",
        "report": directory / "report.md",
        "evidence": directory / "evidence-index.json",
        "warnings": directory / "warnings.json",
    }
    missing = [name for name, item in expected.items() if not item.is_file()]
    if missing:
        return [f"{project.relative(path)}: missing artifacts: {', '.join(sorted(missing))}"]
    try:
        analysis = MediaAnalysis.model_validate(read_json(path))
        evidence = MediaEvidenceIndex.model_validate(read_json(expected["evidence"]))
        timeline = read_json(expected["timeline"])
        warnings = read_json(expected["warnings"])
    except (OSError, ValueError, ValidationError) as exc:
        return [f"{project.relative(path)}: {exc}"]
    if analysis.analysis_id != directory.name:
        errors.append("analysis_id does not match its content-addressed directory")
    if analysis.video_id != directory.parent.name:
        errors.append("video_id does not match its media analysis directory")
    if evidence.analysis_id != analysis.analysis_id or evidence.video_id != analysis.video_id:
        errors.append("evidence index identity does not match media-analysis.json")
    if evidence.media_hash != analysis.metadata.media_hash:
        errors.append("evidence media hash does not match metadata")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        errors.append("warnings.json must contain a JSON array of strings")
    elif warnings != analysis.warnings:
        errors.append("embedded warnings differ from warnings.json")
    declared = {
        "timeline_path": project.relative(expected["timeline"]),
        "evidence_index_path": project.relative(expected["evidence"]),
        "warnings_path": project.relative(expected["warnings"]),
    }
    for field, expected_path in declared.items():
        if getattr(analysis, field) != expected_path:
            errors.append(f"{field} does not point to the colocated artifact")
    raw_media = (project.root / analysis.raw_media_path).resolve()
    if not raw_media.is_relative_to(project.root):
        errors.append("raw_media_path escapes the project root")
    elif not raw_media.is_file() or sha256_file(raw_media) != analysis.metadata.media_hash:
        errors.append("immutable raw media is missing or its hash changed")
    evidence_items = {item.evidence_id: item for item in evidence.items}
    media_items = [item for item in evidence.items if item.kind == "media"]
    if not any(
        item.path == analysis.raw_media_path and item.sha256 == analysis.metadata.media_hash
        for item in media_items
    ):
        errors.append("media evidence does not point to the immutable raw copy")
    for keyframe in analysis.keyframes:
        keyframe_path = (project.root / keyframe.path).resolve()
        expected_keyframe = (directory / "keyframes" / f"{keyframe.keyframe_id}.jpg").resolve()
        if keyframe_path != expected_keyframe:
            errors.append(f"keyframe path is not colocated: {keyframe.keyframe_id}")
        elif not keyframe_path.is_file() or sha256_file(keyframe_path) != keyframe.sha256:
            errors.append(f"keyframe is missing or its hash changed: {keyframe.keyframe_id}")
        evidence_id = stable_id("evi_", analysis.analysis_id, "keyframe", keyframe.keyframe_id)
        item = evidence_items.get(evidence_id)
        if item is None or item.path != keyframe.path or item.sha256 != keyframe.sha256:
            errors.append(f"keyframe evidence is missing or inconsistent: {keyframe.keyframe_id}")
    if not isinstance(timeline, dict):
        errors.append("timeline.json root must be an object")
    else:
        if timeline.get("analysis_id") != analysis.analysis_id:
            errors.append("timeline identity does not match media analysis")
        expected_shots = [item.model_dump(mode="json") for item in analysis.shots]
        expected_frames = [item.model_dump(mode="json") for item in analysis.keyframes]
        if timeline.get("shots") != expected_shots:
            errors.append("timeline shots differ from media-analysis.json")
        if timeline.get("keyframes") != expected_frames:
            errors.append("timeline keyframes differ from media-analysis.json")
    if analysis.vision is not None:
        by_shot = {item.shot_id: item for item in analysis.shots}
        for observation in analysis.vision.ocr_observations:
            shot = by_shot[observation.shot_id]
            if observation.start_ms < shot.start_ms or observation.end_ms > shot.end_ms:
                errors.append(f"OCR timestamp falls outside its shot: {observation.observation_id}")
    return [f"{project.relative(path)}: {message}" for message in errors]


def _validate_media_features(project: ProjectLayout) -> list[str]:
    path = project.normalized_dir / "media_features.parquet"
    if not path.is_file():
        return []
    errors: list[str] = []
    try:
        records = read_models(path, MediaFeatureRecord)
    except (OSError, ValueError, ValidationError) as exc:
        return [f"{project.relative(path)}: {exc}"]
    seen: set[str] = set()
    for item in records:
        if item.analysis_id in seen:
            errors.append(f"duplicate media feature analysis_id: {item.analysis_id}")
        seen.add(item.analysis_id)
        analysis_path = project.root / item.analysis_path
        if not analysis_path.is_file():
            errors.append(f"media feature analysis is missing: {item.analysis_id}")
    return [f"{project.relative(path)}: {message}" for message in errors]


def _validate_phase4_artifact(
    path: Path,
    project: ProjectLayout,
    model_type: type[CommentAnalysis] | type[AccountDistillation] | type[BenchmarkComparison],
) -> list[str]:
    errors: list[str] = []
    directory = path.parent
    evidence_path = directory / "evidence-index.json"
    warnings_path = directory / "warnings.json"
    report_path = directory / "report.md"
    missing = [
        item.name for item in (evidence_path, warnings_path, report_path) if not item.is_file()
    ]
    if missing:
        return [f"{project.relative(path)}: missing artifacts: {', '.join(sorted(missing))}"]
    try:
        artifact = model_type.model_validate(read_json(path))
        evidence = ArtifactEvidenceIndex.model_validate(read_json(evidence_path))
        warnings = read_json(warnings_path)
    except (OSError, ValueError, ValidationError) as exc:
        return [f"{project.relative(path)}: {exc}"]
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        errors.append("warnings.json must contain a JSON array of strings")
    evidence_ids = {item.evidence_id for item in evidence.items}
    referenced: set[str] = set()
    artifact_id: str
    account_ids: set[str]
    if isinstance(artifact, CommentAnalysis):
        artifact_id = artifact.analysis_id
        account_ids = {artifact.account_id}
        referenced.update(item.evidence_id for item in artifact.signals)
        referenced.update(item.evidence_id for item in artifact.need_clusters)
        if artifact.evidence_index_path != project.relative(evidence_path):
            errors.append("evidence_index_path does not point to the colocated artifact")
        if artifact.warnings_path != project.relative(warnings_path):
            errors.append("warnings_path does not point to the colocated artifact")
    elif isinstance(artifact, AccountDistillation):
        artifact_id = artifact.distillation_id
        account_ids = {artifact.account_id}
        referenced.update(artifact.positioning.evidence_ids)
        referenced.update(item.evidence_id for item in artifact.content_clusters)
        referenced.update(item.evidence_id for item in artifact.comment_need_clusters)
        for pattern in artifact.patterns:
            referenced.update(pattern.evidence_ids)
            knowledge_path = (
                project.root / "knowledge-base" / "patterns" / f"{pattern.pattern_id}.json"
            )
            if not knowledge_path.is_file():
                errors.append(f"knowledge Pattern missing: {project.relative(knowledge_path)}")
        if artifact.evidence_index_path != project.relative(evidence_path):
            errors.append("evidence_index_path does not point to the colocated artifact")
        if artifact.warnings_path != project.relative(warnings_path):
            errors.append("warnings_path does not point to the colocated artifact")
    else:
        artifact_id = artifact.comparison_id
        account_ids = {artifact.target_account_id, *artifact.benchmark_account_ids}
        for item in artifact.transfer_matrix:
            referenced.update(item.evidence_ids)
        if artifact.evidence_index_path != project.relative(evidence_path):
            errors.append("evidence_index_path does not point to the colocated artifact")
        if artifact.warnings_path != project.relative(warnings_path):
            errors.append("warnings_path does not point to the colocated artifact")
    if artifact_id != evidence.artifact_id:
        errors.append("artifact identity does not match evidence-index.json")
    if account_ids != set(evidence.account_ids):
        errors.append("artifact account IDs do not match evidence-index.json")
    missing_evidence = sorted(referenced - evidence_ids)
    if missing_evidence:
        errors.append(f"artifact references missing evidence: {missing_evidence}")
    empty_sources = sorted(
        item.evidence_id
        for item in evidence.items
        if item.evidence_id in referenced and not item.sources
    )
    if empty_sources:
        errors.append(f"referenced evidence has no normalized sources: {empty_sources}")
    return [f"{project.relative(path)}: {message}" for message in errors]


def _validate_benchmark_profile(path: Path, project: ProjectLayout) -> list[str]:
    """Validate a reusable cross-account profile and its retained sources."""

    errors: list[str] = []
    try:
        profile = AccountBenchmarkProfile.model_validate(read_json(path))
        warnings_path = path.parent / "warnings.json"
        if not warnings_path.is_file() or read_json(warnings_path) != profile.warnings:
            errors.append("warnings.json does not match the profile")
        if profile.profile_id != path.parent.name:
            errors.append("profile path does not match profile_id")
        if profile.account_id != path.parents[2].name:
            errors.append("profile path does not match account_id")
        if not profile.input_hashes:
            errors.append("profile input_hashes must not be empty")
        source_found = False
        for source_path in (project.root / "reports" / "accounts" / profile.account_id).glob(
            "*/distillation.json"
        ):
            source_payload = read_json(source_path)
            if (
                isinstance(source_payload, dict)
                and source_payload.get("distillation_id") == profile.source_distillation_id
            ):
                source_found = True
                break
        if not source_found:
            errors.append("source distillation is missing")
    except (OSError, ValueError, ValidationError) as exc:
        return [f"{project.relative(path)}: {exc}"]
    return [f"{project.relative(path)}: {message}" for message in errors]


def _validate_evidence_companions(
    *,
    artifact_id: str,
    account_ids: set[str],
    evidence_path: Path,
    warnings_path: Path,
    report_path: Path,
    project: ProjectLayout,
    referenced_evidence_ids: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    missing = [
        item.name for item in (evidence_path, warnings_path, report_path) if not item.is_file()
    ]
    if missing:
        return [f"missing artifacts: {', '.join(sorted(missing))}"]
    try:
        evidence = ArtifactEvidenceIndex.model_validate(read_json(evidence_path))
        warnings = read_json(warnings_path)
    except (OSError, ValueError, ValidationError) as exc:
        return [str(exc)]
    if evidence.artifact_id != artifact_id:
        errors.append("artifact identity does not match evidence-index.json")
    if set(evidence.account_ids) != account_ids:
        errors.append("artifact account IDs do not match evidence-index.json")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        errors.append("warnings.json must contain a JSON array of strings")
    if referenced_evidence_ids is not None:
        evidence_ids = {item.evidence_id for item in evidence.items}
        missing_ids = sorted(referenced_evidence_ids - evidence_ids)
        if missing_ids:
            errors.append(f"artifact references missing evidence: {missing_ids}")
        empty_sources = sorted(
            item.evidence_id
            for item in evidence.items
            if item.evidence_id in referenced_evidence_ids and not item.sources
        )
        if empty_sources:
            errors.append(f"referenced evidence has no normalized sources: {empty_sources}")
    return errors


def _validate_score(path: Path, project: ProjectLayout) -> list[str]:
    errors: list[str] = []
    directory = path.parent
    try:
        score = ScoreResult.model_validate(read_json(path))
    except (OSError, ValueError, ValidationError) as exc:
        return [f"{project.relative(path)}: {exc}"]
    if score.score_id != directory.name:
        errors.append("score_id does not match its content-addressed directory")
    if score.account_id != directory.parent.name:
        errors.append("account_id does not match scoring directory")
    candidate_path = project.root / "candidates" / score.candidate_id / "candidate.json"
    try:
        candidate = ContentCandidate.model_validate(read_json(candidate_path))
        script_path = project.root / candidate.script_path
        if not script_path.is_file() or sha256_file(script_path) != candidate.script_hash:
            errors.append("candidate script is missing or its immutable hash changed")
    except (OSError, ValueError, ValidationError) as exc:
        errors.append(f"candidate invalid: {exc}")
    rubric_paths = list(
        (project.root / "knowledge-base" / "rubrics" / score.account_id).glob(
            f"{score.rubric_id}.json"
        )
    )
    if not rubric_paths:
        errors.append("score Rubric is missing")
    else:
        try:
            Rubric.model_validate(read_json(rubric_paths[0]))
        except (OSError, ValueError, ValidationError) as exc:
            errors.append(f"score Rubric invalid: {exc}")
    errors.extend(
        _validate_evidence_companions(
            artifact_id=score.score_id,
            account_ids={score.account_id},
            evidence_path=directory / "evidence-index.json",
            warnings_path=directory / "warnings.json",
            report_path=directory / "report.md",
            project=project,
            referenced_evidence_ids=set(score.evidence_ids),
        )
    )
    if score.evidence_index_path != project.relative(directory / "evidence-index.json"):
        errors.append("evidence_index_path does not point to the colocated artifact")
    if score.warnings_path != project.relative(directory / "warnings.json"):
        errors.append("warnings_path does not point to the colocated artifact")
    return [f"{project.relative(path)}: {message}" for message in errors]


def _validate_prediction(path: Path, project: ProjectLayout) -> list[str]:
    errors: list[str] = []
    directory = path.parent
    try:
        prediction = Prediction.model_validate(read_json(path))
    except (OSError, ValueError, ValidationError) as exc:
        return [f"{project.relative(path)}: {exc}"]
    if prediction.prediction_id != directory.name:
        errors.append("prediction_id does not match its content-addressed directory")
    if prediction.prediction_id != stable_id("pred_", prediction.input_hash):
        errors.append("prediction_id does not match immutable input_hash")
    score_paths = list((project.root / "reports" / "scoring").glob("*/*/score.json"))
    if not any(item.parent.name == prediction.score_id for item in score_paths):
        errors.append("linked score is missing")
    errors.extend(
        _validate_evidence_companions(
            artifact_id=prediction.prediction_id,
            account_ids={prediction.account_id},
            evidence_path=directory / "evidence-index.json",
            warnings_path=directory / "warnings.json",
            report_path=directory / "report.md",
            project=project,
        )
    )
    if prediction.evidence_index_path != project.relative(directory / "evidence-index.json"):
        errors.append("evidence_index_path does not point to the colocated artifact")
    if prediction.warnings_path != project.relative(directory / "warnings.json"):
        errors.append("warnings_path does not point to the colocated artifact")
    return [f"{project.relative(path)}: {message}" for message in errors]


def _validate_publication(path: Path, project: ProjectLayout) -> list[str]:
    errors: list[str] = []
    try:
        publication = Publication.model_validate(read_json(path))
    except (OSError, ValueError, ValidationError) as exc:
        return [f"{project.relative(path)}: {exc}"]
    if publication.publication_id != path.parent.name:
        errors.append("publication_id does not match its content-addressed directory")
    if publication.publication_id != stable_id("pub_", publication.input_hash):
        errors.append("publication_id does not match immutable input_hash")
    if publication.prediction_id is not None:
        prediction_path = (
            project.root / "predictions" / publication.prediction_id / "prediction.json"
        )
        if not prediction_path.is_file():
            errors.append("linked prediction is missing")
    candidate_path = project.root / "candidates" / publication.candidate_id / "candidate.json"
    if not candidate_path.is_file():
        errors.append("linked candidate is missing")
    return [f"{project.relative(path)}: {message}" for message in errors]


def _validate_retro(path: Path, project: ProjectLayout) -> list[str]:
    errors: list[str] = []
    directory = path.parent
    try:
        retro = Retro.model_validate(read_json(path))
    except (OSError, ValueError, ValidationError) as exc:
        return [f"{project.relative(path)}: {exc}"]
    if retro.retro_id != directory.name:
        errors.append("retro_id does not match its content-addressed directory")
    if retro.publication_id != directory.parent.name:
        errors.append("publication_id does not match Retro directory")
    if set(retro.supported_rule_ids).intersection(retro.counterexample_rule_ids):
        errors.append("supported and counterexample Rule IDs overlap")
    for proposal in retro.rule_change_proposals:
        rule_path = (
            project.root
            / "knowledge-base"
            / "rules"
            / proposal.rule_id
            / f"{proposal.from_version}.json"
        )
        if not rule_path.is_file():
            errors.append(f"source Rule version is missing: {proposal.rule_id}")
    for experiment in retro.next_experiments:
        experiment_path = (
            project.root / "knowledge-base" / "experiments" / f"{experiment.experiment_id}.json"
        )
        if not experiment_path.is_file():
            errors.append(f"next experiment artifact is missing: {experiment.experiment_id}")
    review_path = (
        project.root
        / "knowledge-base"
        / "reviews"
        / retro.publication_id
        / retro.retro_id
        / "retro.json"
    )
    if not review_path.is_file():
        errors.append("knowledge-base review copy is missing")
    errors.extend(
        _validate_evidence_companions(
            artifact_id=retro.retro_id,
            account_ids={retro.account_id},
            evidence_path=directory / "evidence-index.json",
            warnings_path=directory / "warnings.json",
            report_path=directory / "report.md",
            project=project,
        )
    )
    if retro.evidence_index_path != project.relative(directory / "evidence-index.json"):
        errors.append("evidence_index_path does not point to the colocated artifact")
    if retro.warnings_path != project.relative(directory / "warnings.json"):
        errors.append("warnings_path does not point to the colocated artifact")
    return [f"{project.relative(path)}: {message}" for message in errors]


def validate_project(project: ProjectLayout, *, persist: bool = True) -> QualityReport:
    """Verify raw hashes and schemas, optionally without recording a validation run."""

    state = project.load_state()
    raw_media_paths = sorted((project.root / "raw" / "media").glob("*"))
    vision_output_paths = sorted((project.root / "raw" / "vision-outputs").glob("*.json"))
    collection_batch_paths = sorted(
        (project.root / "raw" / "account-collections").glob("*/*/provider-batch.json")
    )
    input_hashes = sorted(
        {
            *(receipt.raw_hash for receipt in state.imports),
            *(path.stem for path in raw_media_paths if path.is_file()),
            *(path.stem for path in vision_output_paths),
            *(path.parent.name for path in collection_batch_paths),
        }
    )
    manifest = (
        project.begin_run("validate", input_hashes=input_hashes)
        if persist
        else RunManifest(
            run_id=stable_id("run_", "read-only-validation", *input_hashes),
            command="validate",
            started_at=datetime.now(UTC),
            input_hashes=input_hashes,
        )
    )
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
    for path in [*model_output_paths, *vision_output_paths, *raw_media_paths]:
        if not path.is_file():
            continue
        if sha256_file(path) != path.stem:
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, str(path), "integrity"),
                    run_id=manifest.run_id,
                    severity="error",
                    code="raw_integrity",
                    entity="raw_inputs",
                    message=f"Raw content-addressed input hash mismatch: {project.relative(path)}",
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

    media_analysis_paths = sorted(
        (project.root / "analyses" / "media").glob("*/*/media-analysis.json")
    )
    for path in media_analysis_paths:
        for message in _validate_media_analysis(path, project):
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, project.relative(path), message),
                    run_id=manifest.run_id,
                    severity="error",
                    code="media_artifact_invalid",
                    entity="media_analyses",
                    message=message,
                )
            )
    for message in _validate_media_features(project):
        issues.append(
            DataQualityIssue(
                issue_id=stable_id("dqi_", manifest.run_id, "media_features", message),
                run_id=manifest.run_id,
                severity="error",
                code="media_artifact_invalid",
                entity="media_features",
                message=message,
            )
        )

    media_enrichment_paths = sorted(
        (project.root / "analyses" / "accounts").glob("*/media-enrichments/*/enrichment.json")
    )
    for path in media_enrichment_paths:
        try:
            enrichment = AccountMediaEnrichment.model_validate(read_json(path))
            if enrichment.enrichment_id != path.parent.name:
                raise ValueError("media enrichment path does not match enrichment_id")
            if enrichment.account_id != path.parents[2].name:
                raise ValueError("media enrichment path does not match account_id")
            source_batch = project.root / enrichment.source_batch_path
            if (
                not source_batch.is_file()
                or sha256_file(source_batch) != enrichment.source_batch_hash
            ):
                raise ValueError("media enrichment source batch hash mismatch")
            warning_path = path.parent / "warnings.json"
            if not warning_path.is_file() or read_json(warning_path) != enrichment.warnings:
                raise ValueError("media enrichment warning artifact mismatch")
            for video in enrichment.videos:
                if video.media_analysis_path is not None:
                    media_path = project.root / video.media_analysis_path
                    if not media_path.is_file():
                        raise ValueError(f"media analysis is missing for video: {video.video_id}")
                if video.text_analysis_path is not None:
                    text_path = project.root / video.text_analysis_path
                    if not text_path.is_file():
                        raise ValueError(f"text analysis is missing for video: {video.video_id}")
            if (
                enrichment.distillation_path is not None
                and not (project.root / enrichment.distillation_path).is_file()
            ):
                raise ValueError("media enrichment distillation artifact is missing")
        except (OSError, ValueError, ValidationError) as exc:
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id(
                        "dqi_",
                        manifest.run_id,
                        project.relative(path),
                        str(exc),
                    ),
                    run_id=manifest.run_id,
                    severity="error",
                    code="media_enrichment_artifact_invalid",
                    entity="media_enrichments",
                    message=f"{project.relative(path)}: {exc}",
                )
            )

    phase4_paths: list[tuple[Path, type[Any]]] = [
        *[
            (path, CommentAnalysis)
            for path in sorted((project.root / "analyses" / "comments").glob("*/*/analysis.json"))
        ],
        *[
            (path, AccountDistillation)
            for path in sorted(
                (project.root / "reports" / "accounts").glob("*/*/distillation.json")
            )
        ],
        *[
            (path, BenchmarkComparison)
            for path in sorted((project.root / "reports" / "comparisons").glob("*/comparison.json"))
        ],
    ]
    for path, model_type in phase4_paths:
        for message in _validate_phase4_artifact(path, project, model_type):
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, project.relative(path), message),
                    run_id=manifest.run_id,
                    severity="error",
                    code="analysis_artifact_invalid",
                    entity="phase4_artifacts",
                    message=message,
                )
            )

    benchmark_profile_paths = sorted(
        (project.root / "analyses" / "accounts").glob("*/benchmark-profiles/*/profile.json")
    )
    for path in benchmark_profile_paths:
        for message in _validate_benchmark_profile(path, project):
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id(
                        "dqi_",
                        manifest.run_id,
                        project.relative(path),
                        message,
                    ),
                    run_id=manifest.run_id,
                    severity="error",
                    code="benchmark_profile_artifact_invalid",
                    entity="benchmark_profiles",
                    message=message,
                )
            )

    phase5_checks: list[tuple[Path, str]] = [
        *[
            (path, "score")
            for path in sorted((project.root / "reports" / "scoring").glob("*/*/score.json"))
        ],
        *[
            (path, "prediction")
            for path in sorted((project.root / "predictions").glob("*/prediction.json"))
        ],
        *[
            (path, "publication")
            for path in sorted((project.root / "publications").glob("*/publication.json"))
        ],
        *[
            (path, "retro")
            for path in sorted((project.root / "reports" / "retros").glob("*/*/retro.json"))
        ],
    ]
    phase5_validators = {
        "score": _validate_score,
        "prediction": _validate_prediction,
        "publication": _validate_publication,
        "retro": _validate_retro,
    }
    for path, kind in phase5_checks:
        for message in phase5_validators[kind](path, project):
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, project.relative(path), message),
                    run_id=manifest.run_id,
                    severity="error",
                    code="closed_loop_artifact_invalid",
                    entity="phase5_artifacts",
                    message=message,
                )
            )

    rule_paths = sorted((project.root / "knowledge-base" / "rules").glob("*/*.json"))
    rubric_paths = sorted((project.root / "knowledge-base" / "rubrics").glob("*/*.json"))
    knowledge_paths: list[tuple[Path, type[BaseModel]]] = [
        *((path, Rule) for path in rule_paths),
        *((path, Rubric) for path in rubric_paths),
    ]
    for path, knowledge_model_type in knowledge_paths:
        try:
            artifact = knowledge_model_type.model_validate(read_json(path))
            if isinstance(artifact, Rule) and (
                artifact.rule_id != path.parent.name or artifact.version != path.stem
            ):
                raise ValueError("Rule path does not match rule_id/version")
            if isinstance(artifact, Rubric) and artifact.rubric_id != path.stem:
                raise ValueError("Rubric path does not match rubric_id")
        except (OSError, ValueError, ValidationError) as exc:
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, project.relative(path), str(exc)),
                    run_id=manifest.run_id,
                    severity="error",
                    code="closed_loop_artifact_invalid",
                    entity="phase5_knowledge",
                    message=f"{project.relative(path)}: {exc}",
                )
            )

    phase7_paths: list[tuple[Path, type[BaseModel]]] = [
        *(
            (path, AuthorizedExportManifest)
            for path in sorted((project.root / "raw" / "authorized-manifests").glob("*.json"))
        ),
        *(
            (path, SyncReceipt)
            for path in sorted((project.root / "collaboration" / "syncs").glob("*/sync.json"))
        ),
        *(
            (path, BatchResult)
            for path in sorted(
                (project.root / "collaboration" / "batches").glob("*/batch-result.json")
            )
        ),
    ]
    snapshot_plan = project.root / "collaboration" / "schedules" / "snapshot-plan.json"
    if snapshot_plan.is_file():
        phase7_paths.append((snapshot_plan, SnapshotScheduleResult))
    team_config = project.root / "team.yaml"
    if team_config.is_file():
        try:
            TeamConfig.model_validate(yaml.safe_load(team_config.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, "team.yaml", str(exc)),
                    run_id=manifest.run_id,
                    severity="error",
                    code="collaboration_artifact_invalid",
                    entity="phase7_artifacts",
                    message=f"team.yaml: {exc}",
                )
            )
    for path, phase7_model_type in phase7_paths:
        try:
            phase7_artifact: BaseModel = phase7_model_type.model_validate(read_json(path))
            if (
                isinstance(phase7_artifact, SyncReceipt)
                and phase7_artifact.sync_id != path.parent.name
            ):
                raise ValueError("Sync receipt path does not match sync_id")
            if (
                isinstance(phase7_artifact, BatchResult)
                and phase7_artifact.batch_id != path.parent.name
            ):
                raise ValueError("Batch result path does not match batch_id")
        except (OSError, ValueError, ValidationError) as exc:
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, project.relative(path), str(exc)),
                    run_id=manifest.run_id,
                    severity="error",
                    code="collaboration_artifact_invalid",
                    entity="phase7_artifacts",
                    message=f"{project.relative(path)}: {exc}",
                )
            )
    raw_collaboration_paths = sorted((project.root / "raw" / "collaboration").glob("*/*.json"))
    for path in raw_collaboration_paths:
        try:
            if sha256_json(read_json(path)) != path.stem:
                raise ValueError("content hash does not match raw collaboration filename")
        except (OSError, ValueError) as exc:
            issues.append(
                DataQualityIssue(
                    issue_id=stable_id("dqi_", manifest.run_id, project.relative(path), str(exc)),
                    run_id=manifest.run_id,
                    severity="error",
                    code="raw_integrity",
                    entity="phase7_raw",
                    message=f"{project.relative(path)}: {exc}",
                )
            )

    openkb_errors, openkb_artifact_count = validate_openkb_artifacts(project)
    for message in openkb_errors:
        issues.append(
            DataQualityIssue(
                issue_id=stable_id("dqi_", manifest.run_id, "openkb", message),
                run_id=manifest.run_id,
                severity="error",
                code="knowledge_artifact_invalid",
                entity="openkb_knowledge",
                message=message,
            )
        )

    for path, message in validate_collection_batches(project, collection_batch_paths):
        issues.append(
            DataQualityIssue(
                issue_id=stable_id("dqi_", manifest.run_id, project.relative(path), message),
                run_id=manifest.run_id,
                severity="error",
                code="raw_integrity",
                entity="phase8_collection",
                message=f"{project.relative(path)}: {message}",
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
            "vision_outputs": len(vision_output_paths),
            "raw_media": len([path for path in raw_media_paths if path.is_file()]),
            "platforms": len(platforms),
            "video_analyses": len(analysis_paths),
            "phase6_artifacts": len(media_analysis_paths),
            "media_enrichments": len(media_enrichment_paths),
            "phase4_artifacts": len(phase4_paths),
            "benchmark_profiles": len(benchmark_profile_paths),
            "phase5_artifacts": len(phase5_checks),
            "rules": len(rule_paths),
            "rubrics": len(rubric_paths),
            "phase7_artifacts": len(phase7_paths) + int(team_config.is_file()),
            "phase7_raw": len(raw_collaboration_paths),
            "phase8_collections": len(collection_batch_paths),
            "openkb_artifacts": openkb_artifact_count,
            "errors": sum(issue.severity == "error" for issue in issues),
            "warnings": sum(issue.severity == "warning" for issue in issues) + len(warnings),
        },
        issues=issues,
        warnings=warnings,
    )
    if persist:
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
