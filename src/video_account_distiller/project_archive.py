"""Safe, verifiable project backup and restore operations."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    BackupRecoveryDrillResult,
    BackupVerification,
    ProjectBackupFile,
    ProjectBackupManifest,
    ProjectRestoreResult,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json
from video_account_distiller.validation import validate_project
from video_account_distiller.version import PACKAGE_VERSION


def backup_manifest_path(archive_path: Path) -> Path:
    """Return the non-ambiguous sidecar path for one backup archive."""

    return archive_path.with_suffix(f"{archive_path.suffix}.manifest.json")


def _safe_relative(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if (
        "\\" in value
        or ":" in value
        or "\x00" in value
        or relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
    ):
        raise DistillerError(
            ErrorCode.RAW_INTEGRITY,
            "Backup contains an unsafe member path",
            details={"path": value},
        )
    return relative


def _temporary_path(*, prefix: str, suffix: str, directory: Path | None = None) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=prefix,
        suffix=suffix,
        dir=directory,
    )
    os.close(descriptor)
    return Path(name)


def _collect_project_entries(
    project: ProjectLayout,
) -> tuple[list[str], list[ProjectBackupFile]]:
    directories: list[str] = []
    files: list[ProjectBackupFile] = []
    project_root = project.root.resolve()
    for path in sorted(project.root.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(project_root):
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Project backups do not follow links outside the project",
                details={"path": project.relative(path)},
            )
        relative = path.relative_to(project.root).as_posix()
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            files.append(
                ProjectBackupFile(
                    path=relative,
                    sha256=sha256_file(path),
                    byte_size=path.stat().st_size,
                )
            )
    if not files:
        raise DistillerError(ErrorCode.INPUT_MISSING, "Project contains no files to back up")
    return directories, files


def create_project_backup(project: ProjectLayout, archive_path: Path) -> ProjectBackupManifest:
    """Create an immutable ZIP plus a hash ledger sidecar outside the project."""

    archive_path = archive_path.expanduser().resolve()
    if archive_path.suffix.casefold() != ".zip":
        raise DistillerError(ErrorCode.SCHEMA_INVALID, "Backup output must use a .zip suffix")
    if archive_path.is_relative_to(project.root):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Backup output must be outside the source project",
        )
    manifest_path = backup_manifest_path(archive_path)
    if archive_path.exists() or manifest_path.exists():
        raise DistillerError(
            ErrorCode.PROJECT_EXISTS,
            "Backup archive or manifest already exists",
            details={"archive": str(archive_path), "manifest": str(manifest_path)},
        )

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    directories, files = _collect_project_entries(project)
    temporary = _temporary_path(
        prefix=f".{archive_path.name}.",
        suffix=".tmp",
        directory=archive_path.parent,
    )
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for directory in directories:
                archive.writestr(f"{directory}/", b"")
            for record in files:
                source = project.root / Path(record.path)
                digest = hashlib.sha256()
                byte_size = 0
                with source.open("rb") as input_file, archive.open(record.path, mode="w") as output:
                    for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                        digest.update(chunk)
                        byte_size += len(chunk)
                        output.write(chunk)
                if byte_size != record.byte_size or digest.hexdigest() != record.sha256:
                    raise DistillerError(
                        ErrorCode.RAW_INTEGRITY,
                        "Project changed while the backup was being created",
                        details={"path": record.path},
                    )
        os.replace(temporary, archive_path)
        archive_sha256 = sha256_file(archive_path)
        state = project.load_state()
        manifest = ProjectBackupManifest(
            backup_id=stable_id("bkp_", state.project_id, archive_sha256),
            package_version=PACKAGE_VERSION,
            created_at=datetime.now(UTC),
            project_id=state.project_id,
            project_name=state.project_name,
            project_schema_version=state.schema_version,
            archive_name=archive_path.name,
            archive_sha256=archive_sha256,
            file_count=len(files),
            directory_count=len(directories),
            total_bytes=sum(item.byte_size for item in files),
            directories=directories,
            files=files,
        )
        atomic_write_json(manifest_path, manifest.model_dump(mode="json"))
        return manifest
    except Exception:
        temporary.unlink(missing_ok=True)
        if archive_path.exists() and not manifest_path.exists():
            archive_path.unlink()
        raise


def _load_manifest(archive_path: Path) -> tuple[Path, ProjectBackupManifest]:
    manifest_path = backup_manifest_path(archive_path)
    if not archive_path.is_file() or not manifest_path.is_file():
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            "Backup archive and manifest sidecar are both required",
            details={"archive": str(archive_path), "manifest": str(manifest_path)},
        )
    try:
        manifest = ProjectBackupManifest.model_validate(read_json(manifest_path))
    except (OSError, ValueError) as exc:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Backup manifest is invalid",
            details={"reason": str(exc)},
        ) from exc
    return manifest_path, manifest


def verify_project_backup(archive_path: Path) -> BackupVerification:
    """Verify archive hash, member allowlist, byte sizes, and every file digest."""

    archive_path = archive_path.expanduser().resolve()
    manifest_path, manifest = _load_manifest(archive_path)
    archive_hash = sha256_file(archive_path)
    if manifest.archive_name != archive_path.name or manifest.archive_sha256 != archive_hash:
        raise DistillerError(ErrorCode.RAW_INTEGRITY, "Backup archive hash or name mismatch")

    expected_files = {item.path: item for item in manifest.files}
    expected_directories = {f"{item}/" for item in manifest.directories}
    if (
        len(expected_files) != manifest.file_count
        or len(expected_directories) != manifest.directory_count
    ):
        raise DistillerError(ErrorCode.RAW_INTEGRITY, "Backup manifest contains duplicate paths")

    try:
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            members = archive.infolist()
            member_names = [item.filename for item in members]
            if len(member_names) != len(set(member_names)):
                raise DistillerError(ErrorCode.RAW_INTEGRITY, "Backup contains duplicate members")
            for name in member_names:
                _safe_relative(name.rstrip("/"))
            if set(member_names) != set(expected_files) | expected_directories:
                raise DistillerError(
                    ErrorCode.RAW_INTEGRITY,
                    "Backup member list does not match its manifest",
                )
            for name, record in expected_files.items():
                digest = hashlib.sha256()
                byte_size = 0
                with archive.open(name, mode="r") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                        byte_size += len(chunk)
                if byte_size != record.byte_size or digest.hexdigest() != record.sha256:
                    raise DistillerError(
                        ErrorCode.RAW_INTEGRITY,
                        "Backup file digest mismatch",
                        details={"path": name},
                    )
    except zipfile.BadZipFile as exc:
        raise DistillerError(ErrorCode.RAW_INTEGRITY, "Backup ZIP is invalid") from exc

    return BackupVerification(
        ok=True,
        backup_id=manifest.backup_id,
        archive_path=str(archive_path),
        manifest_path=str(manifest_path),
        archive_sha256=archive_hash,
        file_count=manifest.file_count,
        directory_count=manifest.directory_count,
        total_bytes=manifest.total_bytes,
    )


def restore_project_backup(archive_path: Path, destination: Path) -> ProjectRestoreResult:
    """Restore only into a new directory, then run a read-only project validation."""

    archive_path = archive_path.expanduser().resolve()
    destination = destination.expanduser().resolve()
    verification = verify_project_backup(archive_path)
    _, manifest = _load_manifest(archive_path)
    if destination.exists():
        raise DistillerError(
            ErrorCode.PROJECT_EXISTS,
            "Restore destination must not already exist",
            details={"destination": str(destination)},
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=destination.parent)
    )
    try:
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            for directory in manifest.directories:
                relative = _safe_relative(directory)
                (temporary.joinpath(*relative.parts)).mkdir(parents=True, exist_ok=True)
            for record in manifest.files:
                relative = _safe_relative(record.path)
                target = temporary.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(record.path, mode="r") as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        restored_project = ProjectLayout.open(temporary)
        validation = validate_project(restored_project, persist=False)
        os.replace(temporary, destination)
        return ProjectRestoreResult(
            ok=validation.error_count == 0,
            backup_id=verification.backup_id,
            destination=str(destination),
            file_count=verification.file_count,
            validation_errors=validation.error_count,
            validation_warnings=validation.stats.get("warnings", len(validation.warnings)),
        )
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def run_backup_recovery_drill(project: ProjectLayout) -> BackupRecoveryDrillResult:
    """Back up, verify, and restore into an isolated temporary workspace."""

    started_at = datetime.now(UTC)
    workspace = Path(tempfile.mkdtemp(prefix="distiller-backup-drill-"))
    steps: list[str] = []
    verification: BackupVerification | None = None
    restored: ProjectRestoreResult | None = None
    try:
        archive_path = workspace / "project.zip"
        create_project_backup(project, archive_path)
        steps.append("backup_created")
        verification = verify_project_backup(archive_path)
        steps.append("backup_verified")
        restored = restore_project_backup(archive_path, workspace / "restored-project")
        steps.append("restored_to_new_directory")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    workspace_removed = not workspace.exists()
    completed_at = datetime.now(UTC)
    return BackupRecoveryDrillResult(
        ok=bool(
            verification
            and restored
            and restored.ok
            and workspace_removed
            and restored.file_count == verification.file_count
        ),
        started_at=started_at,
        completed_at=completed_at,
        source_project=str(project.root),
        workspace_scope="temporary",
        workspace_removed=workspace_removed,
        backup_verified=verification is not None and verification.ok,
        restored_to_new_directory=restored is not None,
        restored_file_count=restored.file_count if restored is not None else 1,
        restored_validation_errors=restored.validation_errors if restored is not None else 1,
        restored_validation_warnings=restored.validation_warnings if restored is not None else 0,
        steps=steps or ["drill_failed_before_first_step"],
    )
