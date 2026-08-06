"""Persistent UI state for the Streamlit dashboard.

Streamlit's ``st.session_state`` lives in memory and is lost on page reload,
theme toggle, or WebSocket reconnects (common behind proxies). This module
mirrors a small set of UI-critical values to a JSON file in the user home
directory so the dashboard can restore them on the next run.

Values are written atomically (tmp file + rename) and reads never raise, so
the dashboard works even if the file is missing or corrupted.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_STATE_PATH = Path.home() / ".distiller-web-state.json"

_KNOWN_KEYS = {
    "api_url",
    "project_path",
    "active_task_id",
    "active_task_kind",
    "active_task_dry_run",
    "last_account_id",
    "last_account_project",
    "theme",
}


def _load() -> dict[str, Any]:
    try:
        payload = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return {key: value for key, value in payload.items() if key in _KNOWN_KEYS}
    except (OSError, ValueError):
        pass
    return {}


def get_state(key: str, default: Any = None) -> Any:
    """Read one persisted value without raising."""
    return _load().get(key, default)


def set_state(**values: Any) -> None:
    """Merge values into the persisted state file atomically."""
    payload = _load()
    payload.update(values)
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=".distiller-web-state-", suffix=".json",
            dir=str(_STATE_PATH.parent),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        os.replace(temp_name, _STATE_PATH)
    except OSError:
        pass


def clear_state(*keys: str) -> None:
    """Remove keys from the persisted state file."""
    payload = _load()
    for key in keys:
        payload.pop(key, None)
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=".distiller-web-state-", suffix=".json",
            dir=str(_STATE_PATH.parent),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        os.replace(temp_name, _STATE_PATH)
    except OSError:
        pass

def _reset() -> None:
    try:
        _STATE_PATH.unlink(missing_ok=True)
    except OSError:
        pass
