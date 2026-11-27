"""Data-quality report contracts and renderers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from video_account_distiller.models import SCHEMA_VERSION, DataQualityIssue
from video_account_distiller.report_presentation import (
    display_label,
    display_warning,
)
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

        entity_label = display_label(self.entity)
        if entity_label == self.entity:
            entity_label = f"数据对象（内部字段 `{self.entity}`）"
        lines = [
            "# 数据质量报告",
            "",
            f"- 数据结构版本：`{self.schema_version}`",
            f"- 运行标识：`{self.run_id}`",
            f"- 检查对象：{entity_label}",
            "- 输入哈希：" + ("、".join(f"`{value}`" for value in self.input_hashes) or "无"),
            f"- 错误数：{self.error_count}",
            "",
            "## 数量统计",
            "",
        ]
        for key, value in sorted(self.stats.items()):
            label = display_label(key)
            if label == key:
                label = f"统计项（内部字段 `{key}`）"
            lines.append(f"- {label}：{value}")
        lines.extend(["", "## 质量问题", ""])
        if not self.issues:
            lines.append("未发现数据质量问题。")
        else:
            for issue in self.issues:
                severity = display_label(issue.severity)
                issue_label = display_label(issue.code)
                if issue_label == issue.code:
                    issue_label = "数据质量异常"
                location = f"，第 {issue.row_number} 行" if issue.row_number is not None else ""
                lines.append(
                    f"- **{severity} · {issue_label}**（代码 `{issue.code}`{location}）："
                    f"{display_warning(issue.message)}"
                )
        if self.warnings:
            lines.extend(["", "## 注意事项", ""])
            lines.extend(f"- {display_warning(warning)}" for warning in self.warnings)
        return "\n".join(lines) + "\n"


def write_quality_report(report: QualityReport, directory: Path) -> tuple[Path, Path]:
    """Write matching JSON and Markdown quality reports."""

    json_path = directory / "quality-report.json"
    markdown_path = directory / "quality-report.md"
    atomic_write_json(json_path, report.as_dict())
    atomic_write_text(markdown_path, report.as_markdown())
    return json_path, markdown_path
