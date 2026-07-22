"""Data-quality report contracts and renderers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from video_account_distiller.models import SCHEMA_VERSION, DataQualityIssue
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION
    run_id: str
    entity: str
    input_hashes: list[str]
    stats: dict[str, int]
    issues: list[DataQualityIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        """Count error-severity issues."""

        return sum(issue.severity == "error" for issue in self.issues)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the report for machine output."""

        return self.model_dump(mode="json")

    def as_markdown(self) -> str:
        """Render a concise auditable quality report."""

        lines = [
            "# Data quality report",
            "",
            f"- Schema version: `{self.schema_version}`",
            f"- Run ID: `{self.run_id}`",
            f"- Entity: `{self.entity}`",
            f"- Input hashes: {', '.join(f'`{value}`' for value in self.input_hashes) or 'none'}",
            f"- Errors: {self.error_count}",
            "",
            "## Counts",
            "",
        ]
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.stats.items()))
        lines.extend(["", "## Issues", ""])
        if not self.issues:
            lines.append("No data-quality issues detected.")
        else:
            for issue in self.issues:
                location = f" row {issue.row_number}" if issue.row_number is not None else ""
                lines.append(
                    f"- **{issue.severity.upper()} {issue.code}**{location}: {issue.message}"
                )
        if self.warnings:
            lines.extend(["", "## Warnings", ""])
            lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines) + "\n"


def write_quality_report(report: QualityReport, directory: Path) -> tuple[Path, Path]:
    """Write matching JSON and Markdown quality reports."""

    json_path = directory / "quality-report.json"
    markdown_path = directory / "quality-report.md"
    atomic_write_json(json_path, report.as_dict())
    atomic_write_text(markdown_path, report.as_markdown())
    return json_path, markdown_path
