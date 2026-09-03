from __future__ import annotations

import json
import re
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
    assert result.stdout.strip() == "1.1.1"


def test_package_and_skill_release_versions_are_aligned() -> None:
    repository = Path(__file__).resolve().parents[2]
    project = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == PACKAGE_VERSION
    assert SKILL_VERSION == PACKAGE_VERSION


def test_stable_tag_workflow_fails_closed_before_publishing_complete_assets() -> None:
    repository = Path(__file__).resolve().parents[2]
    workflow = (repository / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "--require-public-beta-freeze" in workflow
    assert "--public-beta-evidence" in workflow
    assert "VideoAccountDistiller-Setup-" in workflow
    assert "-win64.exe" in workflow
    assert re.search(r"gh release create[\s\S]*?--draft(?:\s|$)", workflow)
    assert "gh release edit" in workflow
    assert "--draft=false" in workflow


def test_windows_installer_keeps_stable_identity_for_in_place_upgrades() -> None:
    repository = Path(__file__).resolve().parents[2]
    installer = (repository / "packaging/windows/VideoAccountDistiller.iss").read_text(
        encoding="utf-8"
    )

    assert "AppId={{8EECC661-966C-4CA4-86CC-8EC1E6C4982B}" in installer
    assert "UsePreviousAppDir=yes" in installer
    assert "OutputBaseFilename=VideoAccountDistiller-Setup-{#MyAppVersion}-win64" in installer
    assert "CloseApplications=yes" in installer


def test_doctor_emits_machine_readable_read_only_report(project: ProjectLayout) -> None:
    before = project.load_state()
    result = runner.invoke(app, ["doctor", "--project", str(project.root), "--json"])
    after = project.load_state()

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["package_version"] == "1.1.1"
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
