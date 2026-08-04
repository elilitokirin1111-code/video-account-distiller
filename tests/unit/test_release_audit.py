from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from video_account_distiller.release import (
    audit_release_candidate,
    write_checksum_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _write_release_artifacts(directory: Path, *, forbidden_wheel_path: str | None = None) -> None:
    directory.mkdir()
    (directory / ".gitignore").write_text("*\n", encoding="utf-8")
    wheel = directory / "video_account_distiller-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as archive:
        archive.writestr(
            forbidden_wheel_path or "video_account_distiller/__init__.py",
            b"",
        )
    sdist = directory / "video_account_distiller-1.0.0.tar.gz"
    with tarfile.open(sdist, mode="w:gz") as archive:
        for name, content in (
            ("video_account_distiller-1.0.0/LICENSE", b"MIT"),
            ("video_account_distiller-1.0.0/THIRD_PARTY_NOTICES.md", b"notices"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    skill = directory / "video-account-distiller-skill-1.0.0.zip"
    with zipfile.ZipFile(skill, mode="w") as archive:
        archive.writestr("video-account-distiller/SKILL.md", b"---\nname: test\n---\n")


def test_source_and_version_release_audit_passes() -> None:
    report = audit_release_candidate(REPOSITORY_ROOT)

    assert report.ok is True
    assert report.package_version == "1.0.0"
    assert report.skill_version == "1.0.0"
    assert all(report.required_files.values())
    assert report.public_beta_required is False
    assert report.public_beta_verified is None
    assert report.issues == []


def test_release_audit_can_require_public_beta_freeze_evidence() -> None:
    report = audit_release_candidate(
        REPOSITORY_ROOT,
        require_public_beta_freeze=True,
    )

    assert report.ok is False
    assert report.public_beta_required is True
    assert report.public_beta_verified is None
    assert any(issue.code == "public_beta_evidence_required" for issue in report.issues)


def test_release_artifacts_and_checksum_manifest_are_verified(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "dist"
    _write_release_artifacts(artifacts)
    checksum_path = write_checksum_manifest(artifacts)

    report = audit_release_candidate(REPOSITORY_ROOT, artifact_dir=artifacts)

    assert checksum_path.is_file()
    assert report.ok is True
    assert set(report.artifact_checksums) == {
        "video-account-distiller-skill-1.0.0.zip",
        "video_account_distiller-1.0.0-py3-none-any.whl",
        "video_account_distiller-1.0.0.tar.gz",
    }
    assert report.issues == []


def test_release_audit_rejects_third_party_source_inside_wheel(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "dist"
    _write_release_artifacts(artifacts, forbidden_wheel_path="third_party/MediaCrawler/main.py")

    report = audit_release_candidate(REPOSITORY_ROOT, artifact_dir=artifacts)

    assert report.ok is False
    assert any(issue.code == "forbidden_wheel_content" for issue in report.issues)
    assert any(issue.code == "checksum_manifest_missing" for issue in report.issues)
