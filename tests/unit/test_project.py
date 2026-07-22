from __future__ import annotations

from pathlib import Path

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.storage.project import ProjectLayout


def test_project_init_is_idempotent_and_does_not_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "research"
    layout, existing = ProjectLayout.initialize(root, project_name="first")
    assert existing is False
    layout.config_path.write_text("project:\n  name: custom\n", encoding="utf-8")
    _, existing = ProjectLayout.initialize(root, project_name="second")
    assert existing is True
    assert "custom" in layout.config_path.read_text(encoding="utf-8")
    assert (root / "raw" / "imports").is_dir()
    assert (root / "normalized").is_dir()


def test_open_uninitialized_project_fails_stably(tmp_path: Path) -> None:
    with pytest.raises(DistillerError) as captured:
        ProjectLayout.open(tmp_path / "missing")
    assert captured.value.code == ErrorCode.PROJECT_NOT_INITIALIZED
