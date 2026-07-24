"""Distiller Web — 一体化 Web 应用启动器.

启动方式:

    uv run distiller-web

默认同时启动 FastAPI 后端 (端口 8000) 和 Streamlit 前端 (端口 8501)。
打开浏览器访问 http://localhost:8501 即可使用。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import uvicorn


def _start_api(host: str, port: int) -> None:
    """在后台线程中启动 FastAPI 服务."""
    from video_account_distiller.api.app import create_app

    app = create_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def main() -> None:
    """启动完整的 Distiller Web 平台."""
    api_host = os.environ.get("DISTILLER_API_HOST", "127.0.0.1")
    api_port = int(os.environ.get("DISTILLER_API_PORT", "8000"))
    web_port = int(os.environ.get("DISTILLER_WEB_PORT", "8501"))
    api_url = f"http://{api_host}:{api_port}"

    print(f"  API 服务 → {api_url}")
    print(f"  Web 前端 → http://localhost:{web_port}")
    print()

    # 后台启动 API
    api_thread = threading.Thread(target=_start_api, args=(api_host, api_port), daemon=True)
    api_thread.start()

    # 等待 API 就绪
    for _ in range(30):
        try:
            import urllib.request

            urllib.request.urlopen(f"{api_url}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    # 通过环境变量传递 API URL 给 Streamlit 页面
    env = os.environ.copy()
    env["DISTILLER_API_URL"] = api_url

    # 启动 Streamlit
    web_dir = Path(__file__).resolve().parent
    home = web_dir / "pages" / "home.py"
    import subprocess

    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(home),
            "--server.port",
            str(web_port),
            "--server.headless",
            "true",
            "--browser.serverAddress",
            "localhost",
        ],
        env=env,
    )
