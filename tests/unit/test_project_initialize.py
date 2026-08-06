from __future__ import annotations

from pathlib import Path

from video_account_distiller.config import load_config
from video_account_distiller.storage.project import ProjectLayout


def test_initialize_inherits_template_config(tmp_path: Path) -> None:
    container, _ = ProjectLayout.initialize(
        tmp_path / "container", project_name="container"
    )
    # Configure the container for local models.
    config = load_config(container.config_path)
    config.models.text_provider = "ollama"
    config.models.vision_provider = "ollama"
    config.models.vision_model = "qwen3-vl:8b"
    container.config_path.write_text(config.as_yaml(), encoding="utf-8")

    child, already = ProjectLayout.initialize(
        tmp_path / "container" / "小许的酒店日记",
        project_name="小许的酒店日记",
        config_template=container.config_path,
    )
    assert already is False
    child_config = load_config(child.config_path)
    assert child_config.project.name == "小许的酒店日记"
    assert child_config.models.text_provider == "ollama"
    assert child_config.models.vision_provider == "ollama"
    assert child_config.models.vision_model == "qwen3-vl:8b"


def test_initialize_falls_back_to_defaults_when_template_missing(tmp_path: Path) -> None:
    layout, _ = ProjectLayout.initialize(
        tmp_path / "project",
        project_name="project",
        config_template=tmp_path / "does-not-exist" / "distiller.yaml",
    )
    config = load_config(layout.config_path)
    assert config.models.text_provider is None
