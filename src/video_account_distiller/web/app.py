"""Distiller Web — 一体化 Web 应用.

uv run distiller-web
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import uvicorn


def _start_api(host: str, port: int) -> None:
    """在后台线程启动 FastAPI."""
    from video_account_distiller.api.app import create_app

    app = create_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    uvicorn.Server(config).run()


def main() -> None:
    api_host = os.environ.get("DISTILLER_API_HOST", "127.0.0.1")
    api_port = int(os.environ.get("DISTILLER_API_PORT", "8000"))
    web_port = int(os.environ.get("DISTILLER_WEB_PORT", "8501"))
    api_url = f"http://{api_host}:{api_port}"

    print(f"  API:  {api_url}")
    print(f"  Web:  http://localhost:{web_port}")
    print()

    # 后台启动 API
    t = threading.Thread(target=_start_api, args=(api_host, api_port), daemon=True)
    t.start()

    # 等待 API 就绪
    for _ in range(30):
        try:
            import urllib.request

            urllib.request.urlopen(f"{api_url}/api/health", timeout=1)
            print("  API 已就绪")
            break
        except Exception:
            time.sleep(0.5)

    # 启动 Streamlit (主脚本 = home.py, 子页面在 pages/)
    web_dir = Path(__file__).resolve().parent
    env = {**os.environ, "DISTILLER_API_URL": api_url}
    import subprocess

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
    )
