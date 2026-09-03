from __future__ import annotations

from pathlib import Path
from typing import Any

import requests
from streamlit.testing.v1 import AppTest


class _FakeResponse:
    ok = True
    status_code = 200
    reason = "OK"

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


def _fake_request(
    _session: requests.Session,
    method: str,
    url: str,
    **_kwargs: Any,
) -> _FakeResponse:
    if url.endswith("/api/health"):
        return _FakeResponse(
            {
                "ok": True,
                "version": "test",
                "features": {"account_video_knowledge": "1"},
            }
        )
    if "/api/tasks" in url:
        return _FakeResponse({"tasks": []})
    if "/api/doctor/" in url:
        return _FakeResponse({"ok": True, "data": {"capabilities": {}}})
    if url.endswith("/reports/"):
        return _FakeResponse({"ok": True, "data": {"reports": []}})
    if url.endswith("/imports"):
        return _FakeResponse({"ok": True, "data": {"receipts": []}})
    if url.endswith("/settings/cloud-model"):
        return _FakeResponse(
            {
                "ok": True,
                "allow_cloud_model_upload": False,
                "api_key_configured": False,
            }
        )
    if method.upper() == "GET" and url.endswith("/status"):
        return _FakeResponse({"ok": False})
    return _FakeResponse({"ok": True})


def test_all_product_pages_render_without_streamlit_exceptions(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(requests.Session, "request", _fake_request)
    web_root = Path(__file__).resolve().parents[2] / "src" / "video_account_distiller" / "web"
    app = AppTest.from_file(str(web_root / "home.py"), default_timeout=30)

    app.run(timeout=30)
    assert not app.exception

    for page_path in (
        "pages/account_analysis.py",
        "pages/data_browser.py",
        "pages/import_data.py",
        "pages/quick_collect.py",
        "pages/reports.py",
        "pages/settings.py",
    ):
        app.switch_page(page_path).run(timeout=30)
        assert not app.exception, page_path
