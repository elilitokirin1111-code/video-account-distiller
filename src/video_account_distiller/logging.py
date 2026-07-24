"""Structured logging for the distiller toolchain.

Replaces ad-hoc ``typer.echo`` / ``print`` calls with a single logging
facility that writes JSON lines to stderr by default.  CLI output (stdout)
remains reserved for the stable JSON envelope and is never mixed with logs.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

# Framework-level logger.  Callers should use ``logger = logging.getLogger(__name__)``
# to participate in the same hierarchy.
LOGGER_NAME = "video_account_distiller"


def _default_formatter(record: logging.LogRecord) -> str:
    """Render one log record as a single compact JSON line."""
    payload: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "msg": record.getMessage(),
    }
    if record.exc_info and record.exc_info[1]:
        payload["exc"] = str(record.exc_info[1])
    extras = getattr(record, "structured", None)
    if isinstance(extras, dict):
        payload.update(extras)
    return json.dumps(payload, ensure_ascii=False, default=str)


class _StructuredHandler(logging.Handler):
    """Handler that writes JSON lines to stderr."""

    def __init__(self, stream: Any = None) -> None:
        super().__init__()
        self._stream = stream or sys.stderr

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = _default_formatter(record) + "\n"
            self._stream.write(line)
            self._stream.flush()
        except Exception:
            self.handleError(record)


def configure_logging(
    level: int | str | None = None,
    *,
    quiet: bool = False,
) -> None:
    """Configure the root video-account-distiller logger.

    By default logs at INFO level.  Pass *level* (an int or "DEBUG"/"WARNING"/…)
    to override.  Pass *quiet* to suppress logs entirely (level=CRITICAL+1).

    The JSON-line handler writes to stderr so it never pollutes the JSON CLI
    envelope on stdout.  This function is idempotent — repeated calls update
    the level on the existing logger.
    """
    resolved: int
    if quiet:
        resolved = logging.CRITICAL + 1
    elif level is not None:
        resolved = logging.getLevelNamesMapping().get(str(level).upper(), logging.INFO)
    else:
        env_level: str = os.environ.get("LOG_LEVEL", "INFO").upper()
        resolved = logging.getLevelNamesMapping().get(env_level, logging.INFO)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(resolved)

    # Only attach our handler once.
    if not any(isinstance(h, _StructuredHandler) for h in logger.handlers):
        handler = _StructuredHandler()
        handler.setLevel(resolved)
        logger.addHandler(handler)

    # Keep the root logger quiet so third-party libraries do not leak.
    logging.getLogger().handlers.clear()
    logging.getLogger().setLevel(logging.WARNING)
