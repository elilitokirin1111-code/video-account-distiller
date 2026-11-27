"""Discover and export account-level one-video-one-document knowledge packages."""

from __future__ import annotations

import os
import zipfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import AccountVideoKnowledgeManifest
from video_account_distiller.storage import ProjectLayout
from video_account_distiller.utils.io import read_json


class KnowledgeBundleSummary(BaseModel):
    manifest_id: str
    account_id: str
    generated_at: datetime
    status: str
    completed_count: int
    degraded_count: int
    skipped_count: int
    document_count: int
    missing_count: int
    manifest_path: str
    output_directory: str


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


class KnowledgePackageService:
    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def list_bundles(self, *, account_id: str | None = None) -> list[KnowledgeBundleSummary]:
        root = self.project.root / "knowledge" / "accounts"
        pattern = (
            f"{account_id}/video-knowledge/avk_*/manifest.json"
            if account_id
            else "*/video-knowledge/avk_*/manifest.json"
        )
        bundles: list[KnowledgeBundleSummary] = []
        for path in root.glob(pattern):
            try:
                manifest = AccountVideoKnowledgeManifest.model_validate(read_json(path))
            except (OSError, ValueError):
                continue
            missing_count = sum(
                not (self.project.root / item.document_path).is_file()
                for item in manifest.documents
            )
            bundles.append(
                KnowledgeBundleSummary(
                    manifest_id=manifest.manifest_id,
                    account_id=manifest.account_id,
                    generated_at=manifest.generated_at,
                    status=manifest.status,
                    completed_count=manifest.completed_count,
                    degraded_count=manifest.degraded_count,
                    skipped_count=manifest.skipped_count,
                    document_count=len(manifest.documents),
                    missing_count=missing_count,
                    manifest_path=str(path.resolve()),
                    output_directory=str(path.parent.resolve()),
                )
            )
        return sorted(
            bundles,
            key=lambda item: (item.generated_at, item.manifest_id),
            reverse=True,
        )

    def export_zip(
        self,
        manifest_path: Path | str,
        *,
        destination_dir: Path | str | None = None,
    ) -> Path:
        path = Path(manifest_path).expanduser().resolve()
        expected_root = self.project.root / "knowledge" / "accounts"
        if not path.is_file() or not _inside(path, expected_root):
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                "Knowledge manifest is missing or outside this project",
            )
        manifest = AccountVideoKnowledgeManifest.model_validate(read_json(path))
        files: list[tuple[Path, str]] = [(path, "manifest.json")]
        readme = path.parent / "README.md"
        if readme.is_file():
            files.append((readme, "README.md"))
        for document in manifest.documents:
            source = (self.project.root / document.document_path).resolve()
            if not source.is_file() or not _inside(source, path.parent):
                raise DistillerError(
                    ErrorCode.INPUT_MISSING,
                    f"Knowledge document is missing: {document.document_path}",
                )
            files.append((source, f"documents/{source.name}"))
        target_dir = (
            Path(destination_dir).expanduser().resolve()
            if destination_dir is not None
            else self.project.root / "exports"
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        output = target_dir / f"{manifest.account_id}-{manifest.manifest_id}-一视频一文档.zip"
        temporary = output.with_suffix(output.suffix + ".tmp")
        try:
            with zipfile.ZipFile(
                temporary,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                for source, archive_name in files:
                    archive.write(source, arcname=archive_name)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        return output
