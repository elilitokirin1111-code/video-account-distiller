"""Shared thin wrapper for the installed distiller CLI."""

from __future__ import annotations

import sys

from video_account_distiller.cli import app


def run(*prefix: str) -> None:
    """Prepend a fixed command route and invoke Typer."""

    sys.argv[1:1] = list(prefix)
    app()
