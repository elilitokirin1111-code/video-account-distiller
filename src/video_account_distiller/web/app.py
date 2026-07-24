"""Streamlit entry-point (``distiller-web`` script).

Run with::

    uv run distiller-web

The default Streamlit port is 8501 — open http://localhost:8501.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Launch the Streamlit web application."""
    web_dir = Path(__file__).resolve().parent
    home = web_dir / "pages" / "home.py"
    port = os.environ.get("DISTILLER_WEB_PORT", "8501")
    api_url = os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000")

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(home),
        "--server.port",
        str(port),
    ]
    env = {**os.environ, "DISTILLER_API_URL": api_url}
    subprocess.run(cmd, env=env, check=False)
