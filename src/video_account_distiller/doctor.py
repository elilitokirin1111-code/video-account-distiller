"""Read-only production installation diagnostics."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from video_account_distiller.models.system import (
    CapabilityDiagnostic,
    DoctorReport,
    ProjectDiagnostic,
    RuntimeDependency,
    RuntimeExecutable,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.validation import validate_project
from video_account_distiller.version import PACKAGE_VERSION

REQUIRED_DEPENDENCIES = (
    "duckdb",
    "jinja2",
    "pyarrow",
    "pydantic",
    "pyyaml",
    "typer",
)


def _dependency(name: str) -> RuntimeDependency:
    try:
        installed_version = version(name)
    except PackageNotFoundError:
        installed_version = None
    return RuntimeDependency(name=name, version=installed_version)


def _executable(name: str) -> RuntimeExecutable:
    path = shutil.which(name)
    return RuntimeExecutable(name=name, available=path is not None, path=path)


def _project_diagnostic(path: Path) -> ProjectDiagnostic:
    root = path.expanduser().resolve()
    exists = root.is_dir()
    initialized = (root / ".distiller-state.json").is_file() and (root / "distiller.yaml").is_file()
    readable = exists and os.access(root, os.R_OK)
    writable = exists and os.access(root, os.W_OK)
    if not initialized:
        return ProjectDiagnostic(
            root=str(root),
            exists=exists,
            initialized=False,
            readable=readable,
            writable=writable,
        )
    report = validate_project(ProjectLayout.open(root), persist=False)
    return ProjectDiagnostic(
        root=str(root),
        exists=True,
        initialized=True,
        readable=readable,
        writable=writable,
        validation_ok=report.error_count == 0,
        validation_errors=report.error_count,
        validation_warnings=len(report.warnings),
    )


def doctor_report(project: Path | None = None) -> DoctorReport:
    """Inspect a local installation without changing project or credential state."""

    dependencies = [_dependency(name) for name in REQUIRED_DEPENDENCIES]
    executables = [_executable("ffmpeg"), _executable("ffprobe")]
    executable_state = {item.name: item.available for item in executables}
    python_supported = sys.version_info >= (3, 11)
    core_ready = python_supported and all(item.version is not None for item in dependencies)
    project_state = _project_diagnostic(project) if project is not None else None
    project_ready = project_state is None or (
        project_state.initialized
        and project_state.readable
        and project_state.writable
        and project_state.validation_ok is True
    )
    return DoctorReport(
        ok=core_ready and project_ready,
        package_version=PACKAGE_VERSION,
        python_version=platform.python_version(),
        python_supported=python_supported,
        operating_system=platform.platform(),
        executable=sys.executable,
        dependencies=dependencies,
        executables=executables,
        capabilities=CapabilityDiagnostic(
            core=core_ready,
            local_media=executable_state["ffmpeg"] and executable_state["ffprobe"],
            feishu_bitable=bool(os.environ.get("FEISHU_BITABLE_TOKEN")),
            google_sheets=bool(os.environ.get("GOOGLE_SHEETS_TOKEN")),
        ),
        project=project_state,
    )
