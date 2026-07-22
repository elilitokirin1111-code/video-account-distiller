"""Versioned Prompt loading and strict rendering."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from video_account_distiller.errors import DistillerError, ErrorCode

FACT_PROMPT_VERSION = "video-fact-extraction-v1"
SEMANTIC_PROMPT_VERSION = "video-semantic-labeling-v1"


def _source_prompt_path(filename: str) -> Path:
    repository_root = Path(__file__).resolve().parents[3]
    return repository_root / "skills" / "video-account-distiller" / "assets" / "prompts" / filename


def load_prompt(filename: str) -> str:
    """Load one prompt from the repository or installed wheel resources."""

    source_path = _source_prompt_path(filename)
    if source_path.is_file():
        return source_path.read_text(encoding="utf-8")
    installed = resources.files("video_account_distiller").joinpath("features", "prompts", filename)
    try:
        return installed.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DistillerError(
            ErrorCode.INTERNAL,
            f"Bundled prompt not found: {filename}",
        ) from exc


def render_prompt(filename: str, **context: Any) -> str:
    """Render one strict prompt using stable JSON for structured values."""

    serialized = {
        key: (
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)
            if not isinstance(value, str)
            else value
        )
        for key, value in context.items()
    }
    environment = Environment(undefined=StrictUndefined, autoescape=False)
    return environment.from_string(load_prompt(filename)).render(**serialized)
