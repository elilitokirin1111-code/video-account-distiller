"""Shared output and error boundaries for modular Typer command groups."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any, TypeVar

import typer

from video_account_distiller.errors import DistillerError, ErrorCode

T = TypeVar("T")


def emit(payload: Any, *, json_output: bool, human: str | None = None) -> None:
    """Emit exactly one machine object or a readable human summary."""

    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=True, default=str))
    else:
        typer.echo(human or json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def execute(operation: Callable[[], T], *, json_output: bool) -> T:
    """Run one CLI operation behind the stable Distiller error contract."""

    try:
        return operation()
    except DistillerError as exc:
        if json_output:
            typer.echo(json.dumps(exc.as_dict(), ensure_ascii=True), file=sys.stdout)
        else:
            typer.echo(f"{exc.code.value}: {exc.message}", err=True)
        raise typer.Exit(exc.exit_code) from exc
    except Exception as exc:
        wrapped = DistillerError(
            ErrorCode.INTERNAL,
            "Unexpected internal error",
            details={"type": type(exc).__name__, "reason": str(exc)},
        )
        if json_output:
            typer.echo(json.dumps(wrapped.as_dict(), ensure_ascii=True), file=sys.stdout)
        else:
            typer.echo(f"{wrapped.code.value}: {wrapped.message}: {exc}", err=True)
        raise typer.Exit(wrapped.exit_code) from exc
