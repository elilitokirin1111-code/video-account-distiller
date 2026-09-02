from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_account_distiller.doctor import doctor_report
from video_account_distiller.storage.project import ProjectLayout


def test_doctor_reports_project_readiness_without_exposing_tokens(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEISHU_BITABLE_TOKEN", "secret-feishu-value")
    monkeypatch.setenv("GOOGLE_SHEETS_TOKEN", "secret-google-value")
    monkeypatch.setenv("TIKHUB_API_KEY", "secret-tikhub-value")

    report = doctor_report(project.root)
    serialized = json.dumps(report.model_dump(mode="json"))

    assert report.ok is True
    assert report.package_version == "1.1.0"
    assert report.capabilities.core is True
    assert isinstance(report.capabilities.local_vision, bool)
    assert isinstance(report.capabilities.mediacrawler_douyin, bool)
    assert any(item.name == "chrome" for item in report.executables)
    assert report.capabilities.tikhub_douyin is True
    assert report.capabilities.feishu_bitable is True
    assert report.capabilities.google_sheets is True
    assert report.project is not None
    assert report.project.validation_ok is True
    assert "secret-feishu-value" not in serialized
    assert "secret-google-value" not in serialized
    assert "secret-tikhub-value" not in serialized


def test_doctor_marks_uninitialized_project_not_ready(tmp_path: Path) -> None:
    report = doctor_report(tmp_path / "missing")

    assert report.ok is False
    assert report.project is not None
    assert report.project.exists is False
    assert report.project.initialized is False
