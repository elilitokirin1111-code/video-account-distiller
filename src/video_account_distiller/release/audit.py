"""Deterministic source and artifact checks for a release candidate."""

from __future__ import annotations

import ast
import re
import tarfile
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import ReleaseAuditIssue, ReleaseAuditReport
from video_account_distiller.release.public_beta import verify_public_beta_evidence
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.io import atomic_write_text

REQUIRED_RELEASE_FILES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "pyproject.toml",
    "docs/privacy-and-compliance.md",
    "docs/production-release.md",
    "docs/public-beta-release.md",
    "docs/release-notes.md",
    "release-evidence/README.md",
    ".github/workflows/release.yml",
    "packaging/windows/VideoAccountDistiller.iss",
    "scripts/build_windows_desktop.ps1",
    "tools/release_acceptance.py",
    "src/video_account_distiller/version.py",
    "skills/video-account-distiller/SKILL.md",
)
FORBIDDEN_ARTIFACT_PARTS = {"third_party", ".env", ".git"}
VERSION_PATTERN = re.compile(r"Package `(?P<version>[0-9]+\.[0-9]+\.[0-9]+)`")


def _release_artifacts(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and (
            path.name.endswith(".whl")
            or path.name.endswith(".tar.gz")
            or path.name.endswith(".zip")
            or path.name.endswith(".exe")
        )
    )


def _source_version(path: Path, variable: str) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == variable
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def _unsafe_artifact_member(name: str) -> bool:
    parts = {part.casefold() for part in PurePosixPath(name).parts}
    return bool(parts & FORBIDDEN_ARTIFACT_PARTS)


def _audit_wheel(
    wheel: Path,
    issues: list[ReleaseAuditIssue],
) -> None:
    try:
        with zipfile.ZipFile(wheel, mode="r") as archive:
            forbidden = [name for name in archive.namelist() if _unsafe_artifact_member(name)]
            if forbidden:
                issues.append(
                    ReleaseAuditIssue(
                        severity="error",
                        code="forbidden_wheel_content",
                        message="Wheel contains forbidden source or credential paths",
                        path=forbidden[0],
                    )
                )
    except zipfile.BadZipFile as exc:
        issues.append(
            ReleaseAuditIssue(
                severity="error",
                code="invalid_wheel",
                message=f"Wheel is not a valid ZIP archive: {exc}",
                path=str(wheel),
            )
        )


def _audit_skill_archive(
    skill_archive: Path,
    issues: list[ReleaseAuditIssue],
) -> None:
    try:
        with zipfile.ZipFile(skill_archive, mode="r") as archive:
            names = archive.namelist()
            if "video-account-distiller/SKILL.md" not in {
                name.replace("\\", "/") for name in names
            }:
                issues.append(
                    ReleaseAuditIssue(
                        severity="error",
                        code="skill_entrypoint_missing",
                        message="Skill archive is missing video-account-distiller/SKILL.md",
                        path=str(skill_archive),
                    )
                )
            if any(_unsafe_artifact_member(name) for name in names):
                issues.append(
                    ReleaseAuditIssue(
                        severity="error",
                        code="forbidden_skill_content",
                        message="Skill archive contains forbidden credential or Git paths",
                        path=str(skill_archive),
                    )
                )
    except zipfile.BadZipFile as exc:
        issues.append(
            ReleaseAuditIssue(
                severity="error",
                code="invalid_skill_archive",
                message=f"Skill archive is not a valid ZIP: {exc}",
                path=str(skill_archive),
            )
        )


def _audit_sdist(
    sdist: Path,
    issues: list[ReleaseAuditIssue],
) -> None:
    try:
        with tarfile.open(sdist, mode="r:gz") as archive:
            names = archive.getnames()
            if any(_unsafe_artifact_member(name) for name in names):
                issues.append(
                    ReleaseAuditIssue(
                        severity="error",
                        code="forbidden_sdist_content",
                        message="Source distribution contains forbidden credential or Git paths",
                        path=str(sdist),
                    )
                )
            for required in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                if not any(name.endswith(f"/{required}") for name in names):
                    issues.append(
                        ReleaseAuditIssue(
                            severity="error",
                            code="sdist_notice_missing",
                            message=f"Source distribution is missing {required}",
                            path=str(sdist),
                        )
                    )
    except (tarfile.TarError, OSError) as exc:
        issues.append(
            ReleaseAuditIssue(
                severity="error",
                code="invalid_sdist",
                message=f"Source distribution is invalid: {exc}",
                path=str(sdist),
            )
        )


def _audit_windows_installer(
    installer: Path,
    issues: list[ReleaseAuditIssue],
) -> None:
    try:
        with installer.open("rb") as stream:
            executable_magic = stream.read(2)
        if executable_magic != b"MZ":
            issues.append(
                ReleaseAuditIssue(
                    severity="error",
                    code="invalid_windows_installer",
                    message="Windows installer does not have a Windows executable header",
                    path=str(installer),
                )
            )
    except OSError as exc:
        issues.append(
            ReleaseAuditIssue(
                severity="error",
                code="invalid_windows_installer",
                message=f"Windows installer could not be read: {exc}",
                path=str(installer),
            )
        )


def _checksum_entries(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pieces = stripped.split(maxsplit=1)
        if len(pieces) != 2:
            raise ValueError(f"invalid checksum line: {line}")
        entries[pieces[1].lstrip("*")] = pieces[0].casefold()
    return entries


def audit_release_candidate(
    repository: Path,
    *,
    artifact_dir: Path | None = None,
    public_beta_evidence: Path | None = None,
    require_public_beta_freeze: bool = False,
) -> ReleaseAuditReport:
    """Audit source, artifacts, checksums, and optional public-beta freeze evidence."""

    repository = repository.expanduser().resolve()
    issues: list[ReleaseAuditIssue] = []
    required_files = {
        relative: (repository / relative).is_file() for relative in REQUIRED_RELEASE_FILES
    }
    for relative, present in required_files.items():
        if not present:
            issues.append(
                ReleaseAuditIssue(
                    severity="error",
                    code="required_release_file_missing",
                    message="Required release file is missing",
                    path=relative,
                )
            )

    package_version: str | None = None
    skill_version: str | None = None
    pyproject_path = repository / "pyproject.toml"
    version_path = repository / "src/video_account_distiller/version.py"
    skill_path = repository / "skills/video-account-distiller/SKILL.md"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        package_version = str(pyproject["project"]["version"])
        source_package_version = _source_version(version_path, "PACKAGE_VERSION")
        source_skill_version = _source_version(version_path, "SKILL_VERSION")
        skill_match = VERSION_PATTERN.search(skill_path.read_text(encoding="utf-8"))
        skill_version = skill_match.group("version") if skill_match else None
        versions = {
            "pyproject": package_version,
            "PACKAGE_VERSION": source_package_version,
            "SKILL_VERSION": source_skill_version,
            "SKILL.md": skill_version,
        }
        if None in versions.values() or len(set(versions.values())) != 1:
            issues.append(
                ReleaseAuditIssue(
                    severity="error",
                    code="release_version_mismatch",
                    message=f"Release versions are not aligned: {versions}",
                )
            )
    except (KeyError, OSError, SyntaxError, tomllib.TOMLDecodeError) as exc:
        issues.append(
            ReleaseAuditIssue(
                severity="error",
                code="release_version_unreadable",
                message=f"Could not read release versions: {exc}",
            )
        )

    artifact_checksums: dict[str, str] = {}
    resolved_artifact_dir: Path | None = None
    if artifact_dir is not None:
        resolved_artifact_dir = artifact_dir.expanduser().resolve()
        if not resolved_artifact_dir.is_dir():
            issues.append(
                ReleaseAuditIssue(
                    severity="error",
                    code="artifact_directory_missing",
                    message="Release artifact directory does not exist",
                    path=str(resolved_artifact_dir),
                )
            )
        else:
            artifacts = _release_artifacts(resolved_artifact_dir)
            artifact_checksums = {path.name: sha256_file(path) for path in artifacts}
            wheel_matches = [
                path
                for path in artifacts
                if package_version
                and path.match(f"video_account_distiller-{package_version}-*.whl")
            ]
            sdist_matches = [
                path
                for path in artifacts
                if package_version
                and path.name == f"video_account_distiller-{package_version}.tar.gz"
            ]
            skill_matches = [
                path
                for path in artifacts
                if package_version
                and path.name == f"video-account-distiller-skill-{package_version}.zip"
            ]
            windows_installer_matches = [
                path
                for path in artifacts
                if package_version
                and path.name == f"VideoAccountDistiller-Setup-{package_version}-win64.exe"
            ]
            if len(wheel_matches) != 1:
                issues.append(
                    ReleaseAuditIssue(
                        severity="error",
                        code="release_wheel_missing",
                        message="Exactly one version-matched wheel is required",
                        path=str(resolved_artifact_dir),
                    )
                )
            else:
                _audit_wheel(wheel_matches[0], issues)
            if len(sdist_matches) != 1:
                issues.append(
                    ReleaseAuditIssue(
                        severity="error",
                        code="release_sdist_missing",
                        message="Exactly one version-matched source distribution is required",
                        path=str(resolved_artifact_dir),
                    )
                )
            else:
                _audit_sdist(sdist_matches[0], issues)
            if len(skill_matches) != 1:
                issues.append(
                    ReleaseAuditIssue(
                        severity="error",
                        code="release_skill_archive_missing",
                        message="Exactly one version-matched Skill archive is required",
                        path=str(resolved_artifact_dir),
                    )
                )
            else:
                _audit_skill_archive(skill_matches[0], issues)
            if len(windows_installer_matches) != 1:
                issues.append(
                    ReleaseAuditIssue(
                        severity="error",
                        code="release_windows_installer_missing",
                        message=("Exactly one version-matched Windows win64 installer is required"),
                        path=str(resolved_artifact_dir),
                    )
                )
            else:
                _audit_windows_installer(windows_installer_matches[0], issues)

            checksum_path = resolved_artifact_dir / "SHA256SUMS.txt"
            if checksum_path.is_file():
                try:
                    declared = _checksum_entries(checksum_path)
                    if declared != artifact_checksums:
                        issues.append(
                            ReleaseAuditIssue(
                                severity="error",
                                code="checksum_manifest_mismatch",
                                message="SHA256SUMS.txt does not match the release artifacts",
                                path=str(checksum_path),
                            )
                        )
                except (OSError, ValueError) as exc:
                    issues.append(
                        ReleaseAuditIssue(
                            severity="error",
                            code="checksum_manifest_invalid",
                            message=str(exc),
                            path=str(checksum_path),
                        )
                    )
            else:
                issues.append(
                    ReleaseAuditIssue(
                        severity="warning",
                        code="checksum_manifest_missing",
                        message="Generate SHA256SUMS.txt before freezing the release candidate",
                        path=str(checksum_path),
                    )
                )

    public_beta_verified: bool | None = None
    public_beta_evidence_path: str | None = None
    public_beta_evidence_sha256: str | None = None
    if public_beta_evidence is None:
        if require_public_beta_freeze:
            issues.append(
                ReleaseAuditIssue(
                    severity="error",
                    code="public_beta_evidence_required",
                    message="A verified public-beta evidence bundle is required",
                )
            )
    else:
        resolved_public_beta = public_beta_evidence.expanduser().resolve()
        public_beta_evidence_path = str(resolved_public_beta)
        verification = verify_public_beta_evidence(
            resolved_public_beta,
            expected_version=package_version,
        )
        public_beta_verified = verification.ok
        public_beta_evidence_sha256 = verification.source_sha256
        issues.extend(verification.issues)
        if resolved_artifact_dir is not None and resolved_artifact_dir.is_dir():
            if (
                resolved_public_beta.parent != resolved_artifact_dir
                or resolved_public_beta.name not in artifact_checksums
            ):
                issues.append(
                    ReleaseAuditIssue(
                        severity="error",
                        code="public_beta_evidence_not_in_artifacts",
                        message=(
                            "Public-beta evidence must be a checksummed file in the release "
                            "artifact directory"
                        ),
                        path=str(resolved_public_beta),
                    )
                )

    return ReleaseAuditReport(
        ok=not any(issue.severity == "error" for issue in issues),
        checked_at=datetime.now(UTC),
        repository=str(repository),
        package_version=package_version,
        skill_version=skill_version,
        required_files=required_files,
        artifact_checksums=artifact_checksums,
        public_beta_required=require_public_beta_freeze,
        public_beta_verified=public_beta_verified,
        public_beta_evidence_path=public_beta_evidence_path,
        public_beta_evidence_sha256=public_beta_evidence_sha256,
        issues=issues,
    )


def write_checksum_manifest(artifact_dir: Path) -> Path:
    """Write a stable checksum manifest without overwriting an existing one."""

    artifact_dir = artifact_dir.expanduser().resolve()
    if not artifact_dir.is_dir():
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            "Release artifact directory does not exist",
            details={"path": str(artifact_dir)},
        )
    checksum_path = artifact_dir / "SHA256SUMS.txt"
    if checksum_path.exists():
        raise DistillerError(
            ErrorCode.PROJECT_EXISTS,
            "Checksum manifest already exists",
            details={"path": str(checksum_path)},
        )
    artifacts = _release_artifacts(artifact_dir)
    if not artifacts:
        raise DistillerError(ErrorCode.INPUT_MISSING, "No release artifacts found")
    content = "".join(f"{sha256_file(path)}  {path.name}\n" for path in artifacts)
    atomic_write_text(checksum_path, content)
    return checksum_path
