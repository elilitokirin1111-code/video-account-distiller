from __future__ import annotations

import json
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.version import PACKAGE_VERSION, SKILL_VERSION

runner = CliRunner()


def test_root_version_is_available_after_install() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "1.0.0"


def test_package_and_skill_release_versions_are_aligned() -> None:
    repository = Path(__file__).resolve().parents[2]
    project = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == PACKAGE_VERSION
    assert SKILL_VERSION == PACKAGE_VERSION


def test_doctor_emits_machine_readable_read_only_report(project: ProjectLayout) -> None:
    before = project.load_state()
    result = runner.invoke(app, ["doctor", "--project", str(project.root), "--json"])
    after = project.load_state()

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["package_version"] == "1.0.0"
    assert payload["project"]["validation_ok"] is True
    assert before == after


def test_machine_json_is_ascii_safe_for_windows_pipes(tmp_path: Path) -> None:
    project_path = tmp_path / "酒店账号项目"
    initialized = runner.invoke(app, ["init", str(project_path), "--json"])
    diagnosed = runner.invoke(app, ["doctor", "--project", str(project_path), "--json"])

    assert initialized.exit_code == 0
    assert diagnosed.exit_code == 0
    assert initialized.stdout.isascii()
    assert diagnosed.stdout.isascii()
    assert json.loads(diagnosed.stdout)["project"]["root"].endswith("酒店账号项目")
