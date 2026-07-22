"""Project-level integrity and schema validation."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ValidationError

from video_account_distiller.models import DataQualityIssue
from video_account_distiller.normalization.pipeline import MODEL_BY_ENTITY
from video_account_distiller.quality import QualityReport, write_quality_report
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.ids import stable_id


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


def validate_project(project: ProjectLayout) -> QualityReport:
    """Verify raw hashes, staging schemas, and cross-platform safety warnings."""

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
            "platforms": len(platforms),
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
