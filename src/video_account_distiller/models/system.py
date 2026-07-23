"""Runtime diagnostics contracts used for production installation checks."""

from __future__ import annotations

from pydantic import Field

from video_account_distiller.models.core import StrictModel


class RuntimeDependency(StrictModel):
    name: str = Field(min_length=1)
    version: str | None = None


class RuntimeExecutable(StrictModel):
    name: str = Field(min_length=1)
    available: bool
    path: str | None = None


class ProjectDiagnostic(StrictModel):
    root: str
    exists: bool
    initialized: bool
    readable: bool
    writable: bool
    validation_ok: bool | None = None
    validation_errors: int | None = Field(default=None, ge=0)
    validation_warnings: int | None = Field(default=None, ge=0)


class CapabilityDiagnostic(StrictModel):
    core: bool
    local_media: bool
    mediacrawler_douyin: bool
    tikhub_douyin: bool
    feishu_bitable: bool
    google_sheets: bool


class DoctorReport(StrictModel):
    ok: bool
    package_version: str
    python_version: str
    python_supported: bool
    operating_system: str
    executable: str
    dependencies: list[RuntimeDependency]
    executables: list[RuntimeExecutable]
    capabilities: CapabilityDiagnostic
    project: ProjectDiagnostic | None = None
