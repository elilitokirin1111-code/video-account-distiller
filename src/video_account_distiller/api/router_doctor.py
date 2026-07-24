"""System and project diagnostics endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from video_account_distiller.doctor import doctor_report

router = APIRouter()


@router.get("/doctor/")
async def system_doctor() -> dict[str, Any]:
    """Return a machine-readable diagnostic of the installed environment."""
    report = doctor_report()
    return {"ok": True, "data": report.model_dump(mode="json")}


@router.get("/doctor/{project_path:path}")
async def project_doctor(project_path: str) -> dict[str, Any]:
    """Return a diagnostic scoped to a specific distiller project."""
    root = Path(project_path).expanduser().resolve()
    report = doctor_report(root)
    return {"ok": True, "data": report.model_dump(mode="json")}
