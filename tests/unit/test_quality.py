from __future__ import annotations

from video_account_distiller.models import DataQualityIssue
from video_account_distiller.quality import QualityReport


def test_quality_report_renders_machine_and_markdown() -> None:
    issue = DataQualityIssue(
        issue_id="dqi_test",
        run_id="run_test",
        severity="error",
        code="schema_invalid",
        entity="metrics",
        message="negative views",
        row_number=2,
    )
    report = QualityReport(
        run_id="run_test",
        entity="metrics",
        input_hashes=["a" * 64],
        stats={"accepted_rows": 0},
        issues=[issue],
        warnings=["Dry run: no project files or state were changed."],
    )
    assert report.error_count == 1
    machine = report.as_dict()
    assert machine["schema_version"] == "0.1.0"
    assert machine["issues"][0]["severity"] == "error"
    assert machine["issues"][0]["code"] == "schema_invalid"
    assert machine["issues"][0]["message"] == "negative views"
    markdown = report.as_markdown()
    assert "# 数据质量报告" in markdown
    assert "错误 · 数据结构校验失败" in markdown
    assert "代码 `schema_invalid`" in markdown
    assert "统计项（内部字段" not in markdown
    assert "本次为预检" in markdown
    assert "negative views" not in markdown
    assert "ERROR" not in markdown
    assert "run_test" in markdown
