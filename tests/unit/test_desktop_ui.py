from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Api:
    running = False


class _Supervisor:
    api = _Api()

    def statuses(self, **_kwargs: Any) -> list[Any]:
        return []

    def start_ollama(self, **_kwargs: Any) -> bool:
        return False


class _Client:
    pass


class _Secrets:
    def get(self, _name: str) -> str | None:
        return None

    def set(self, _name: str, _secret: str) -> None:
        return None


def test_native_window_builds_secret_free_knowledge_workflow_payload(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from video_account_distiller.application import DesktopSettings, DesktopSettingsStore
    from video_account_distiller_desktop.window import DistillerMainWindow

    app = QApplication.instance() or QApplication([])
    window = DistillerMainWindow(
        supervisor=cast(Any, _Supervisor()),
        client=cast(Any, _Client()),
        settings_store=DesktopSettingsStore(tmp_path / "settings.json"),
        secret_store=cast(Any, _Secrets()),
        settings=DesktopSettings(),
    )
    window.account_url.setText("https://www.douyin.com/user/demo")

    payload = window._workflow_payload()

    assert window.stack.count() == 6
    assert payload["distillation_mode"] == "knowledge"
    assert payload["distill_video_knowledge"] is True
    assert payload["cloud_credential_provider"] == "bailian"
    assert "cloud_api_key" not in payload
    assert "weknora" not in payload
    window.task_timer.stop()
    window.close()
    app.processEvents()
