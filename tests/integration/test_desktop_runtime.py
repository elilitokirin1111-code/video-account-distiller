from __future__ import annotations

from pathlib import Path

import pytest

from video_account_distiller.application import DesktopApiClient, EmbeddedApiServer


@pytest.mark.enable_socket
def test_embedded_desktop_api_starts_without_browser_and_serves_tasks(tmp_path: Path) -> None:
    server = EmbeddedApiServer(task_db_path=tmp_path / "desktop-tasks.sqlite3")
    try:
        server.start()
        client = DesktopApiClient(server.base_url)

        health = client.health()
        tasks = client.list_tasks()

        assert health["status"] == "ok"
        assert health["features"]["account_video_knowledge"] == "1"
        assert tasks == []
        assert server.status().available is True
    finally:
        server.stop()
