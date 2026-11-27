from __future__ import annotations

from pathlib import Path

import video_account_distiller.web.web_state as web_state


def test_web_state_roundtrip_and_clear(tmp_path: Path) -> None:
    original = web_state._STATE_PATH
    web_state._STATE_PATH = tmp_path / "web-state.json"
    try:
        assert web_state.get_state("api_url", "fallback") == "fallback"

        web_state.set_state(
            api_url="http://127.0.0.1:9999",
            project_path="C:/projects/workspace",
            active_task_id="run_123",
        )
        assert web_state.get_state("api_url") == "http://127.0.0.1:9999"
        assert web_state.get_state("project_path") == "C:/projects/workspace"
        assert web_state.get_state("active_task_id") == "run_123"

        web_state.clear_state("active_task_id")
        assert web_state.get_state("active_task_id") is None
        # Unrelated keys survive the clear.
        assert web_state.get_state("api_url") == "http://127.0.0.1:9999"
    finally:
        web_state._STATE_PATH = original


def test_web_state_ignores_unknown_keys_and_corrupt_file(tmp_path: Path) -> None:
    original = web_state._STATE_PATH
    state_path = tmp_path / "web-state.json"
    web_state._STATE_PATH = state_path
    try:
        web_state.set_state(api_url="http://127.0.0.1:8000", secret_extra="nope")
        assert web_state.get_state("secret_extra") is None
        assert web_state.get_state("api_url") == "http://127.0.0.1:8000"

        state_path.write_text("{corrupt json", encoding="utf-8")
        assert web_state.get_state("api_url", "fallback") == "fallback"
    finally:
        web_state._STATE_PATH = original
