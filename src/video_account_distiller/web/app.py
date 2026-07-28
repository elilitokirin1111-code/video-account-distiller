"""Distiller Web — 一体化 Web 应用.

uv run distiller-web
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


def _port_available(host: str, port: int) -> bool:
    """Return whether a local TCP port can be bound by this application."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        try:
            candidate.bind((host, port))
        except OSError:
            return False
    return True


def _find_available_port(host: str, preferred: int, *, attempts: int = 50) -> int:
    """Find a free local port without taking over an unrelated application."""

    for port in range(preferred, preferred + attempts):
        if _port_available(host, port):
            return port
    raise RuntimeError(
        f"No available local port found in range {preferred}-{preferred + attempts - 1}"
    )


def _start_api(host: str, port: int) -> None:
    """在后台线程启动 FastAPI."""
    from video_account_distiller.api.app import create_app

    app = create_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    uvicorn.Server(config).run()


def _open_browser_when_ready(url: str) -> None:
    """Open the local workspace after Streamlit starts accepting requests."""

    import urllib.request

    health_url = f"{url}/_stcore/health"
    for _ in range(60):
        try:
            urllib.request.urlopen(health_url, timeout=1)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.5)


def main() -> None:
    api_host = os.environ.get("DISTILLER_API_HOST", "127.0.0.1")
    port_probe_host = "127.0.0.1" if api_host in {"0.0.0.0", "::"} else api_host
    requested_api_port = int(os.environ.get("DISTILLER_API_PORT", "8000"))
    requested_web_port = int(os.environ.get("DISTILLER_WEB_PORT", "8501"))
    api_port = _find_available_port(port_probe_host, requested_api_port)
    web_port = _find_available_port("127.0.0.1", requested_web_port)
    api_browser_host = "127.0.0.1" if api_host in {"0.0.0.0", "::"} else api_host
    api_url = f"http://{api_browser_host}:{api_port}"

    if api_port != requested_api_port:
        print(f"  Port {requested_api_port} is busy; using API port {api_port}.")
    if web_port != requested_web_port:
        print(f"  Port {requested_web_port} is busy; using Web port {web_port}.")

    print(f"  API:  {api_url}")
    print(f"  Web:  http://localhost:{web_port}")
    print()

    # 后台启动 API
    t = threading.Thread(target=_start_api, args=(api_host, api_port), daemon=True)
    t.start()

    # 等待 API 就绪
    api_ready = False
    for _ in range(30):
        try:
            import urllib.request

            urllib.request.urlopen(f"{api_url}/api/health", timeout=1)
            print("  API 已就绪")
            api_ready = True
            break
        except Exception:
            time.sleep(0.5)
    if not api_ready:
        raise RuntimeError(f"Local API did not become ready: {api_url}")

    # 启动 Streamlit (主脚本 = home.py, 子页面在 pages/)
    web_dir = Path(__file__).resolve().parent
    env = {**os.environ, "DISTILLER_API_URL": api_url}
    web_url = f"http://localhost:{web_port}"
    if os.environ.get("DISTILLER_OPEN_BROWSER", "1") != "0":
        threading.Thread(
            target=_open_browser_when_ready,
            args=(web_url,),
            daemon=True,
        ).start()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(web_dir / "home.py"),
            "--server.port",
            str(web_port),
            "--server.headless",
            "true",
            "--browser.serverAddress",
            "localhost",
        ],
        env=env,
        check=True,
    )
