from __future__ import annotations

import pytest

from video_account_distiller.web import app


def test_find_available_port_skips_busy_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app, "_port_available", lambda host, port: port == 8503)

    assert app._find_available_port("127.0.0.1", 8501) == 8503


def test_find_available_port_fails_with_bounded_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "_port_available", lambda host, port: False)

    with pytest.raises(RuntimeError, match="8501-8502"):
        app._find_available_port("127.0.0.1", 8501, attempts=2)
