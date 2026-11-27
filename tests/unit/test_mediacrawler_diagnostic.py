from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_account_distiller.collection.mediacrawler import (
    MEDIACRAWLER_PINNED_COMMIT,
    mediacrawler_diagnostic,
)


def _runtime(root: Path) -> Path:
    home = root / "MediaCrawler"
    (home / "media_platform" / "douyin").mkdir(parents=True)
    (home / "cache").mkdir(parents=True)
    (home / "pyproject.toml").write_text(
        '[project]\nname = "mediacrawler"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    (home / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (home / "LICENSE").write_text("test fixture\n", encoding="utf-8")
    (home / "cache" / "__init__.py").write_text("# fixture\n", encoding="utf-8")
    (home / "cache" / "cache_factory.py").write_text("# fixture\n", encoding="utf-8")
    (home / "media_platform" / "douyin" / "client.py").write_text(
        "# fixture\n",
        encoding="utf-8",
    )
    return home


def test_mediacrawler_diagnostic_reports_pinned_ready_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _runtime(tmp_path)
    profile = tmp_path / "profile"
    profile.mkdir()
    bridge = tmp_path / "bridge.py"
    bridge.write_text("# fixture\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: f"/tools/{name}")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"{MEDIACRAWLER_PINNED_COMMIT}\n",
        ),
    )

    report = mediacrawler_diagnostic(
        home=home,
        browser_profile=profile,
        browser_channel="chrome",
        bridge_script=bridge,
    )

    assert report.runtime_ready is True
    assert report.ready is True
    assert report.commit_matches is True
    assert report.project_requires_python == ">=3.11"
    assert report.login_status == "profile_present_unverified"
    assert report.warnings == ["browser_profile_present_login_unverified"]


def test_mediacrawler_diagnostic_exposes_mismatch_and_missing_login(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _runtime(tmp_path)
    bridge = tmp_path / "bridge.py"
    bridge.write_text("# fixture\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: f"/tools/{name}")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="unexpected\n"),
    )

    report = mediacrawler_diagnostic(
        home=home,
        browser_profile=tmp_path / "missing-profile",
        browser_channel="msedge",
        bridge_script=bridge,
    )

    assert report.runtime_ready is False
    assert report.ready is False
    assert report.actual_commit == "unexpected"
    assert report.login_status == "profile_missing"
    assert "pinned_commit_mismatch" in report.warnings
    assert "browser_profile_missing" in report.warnings
