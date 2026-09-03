"""Validation for the privacy-bounded local knowledge outbox."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from video_account_distiller.knowledge.models import KnowledgeExportIndex
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import read_json


def validate_knowledge_artifacts(project: ProjectLayout) -> tuple[list[str], int]:
    """Return local knowledge integrity errors and the inspected artifact count."""

    root = project.root / "knowledge-outbox" / "local"
    manifest_path = root / "manifest.json"
    account_root = (root / "accounts").resolve()
    allowed_source_roots = {"analyses", "knowledge-base", "reports"}
    errors: list[str] = []
    artifact_count = 0

    if not root.exists():
        return errors, artifact_count

    markdown_paths = sorted((root / "accounts").glob("*.md"))
    artifact_count += len(markdown_paths)
    if markdown_paths and not manifest_path.is_file():
        errors.append("knowledge-outbox/local: account documents exist without manifest.json")

    if manifest_path.is_file():
        artifact_count += 1
        try:
            export_index = KnowledgeExportIndex.model_validate(read_json(manifest_path))
            for document_key, document in export_index.documents.items():
                if document.document_key != document_key:
                    raise ValueError(f"manifest key mismatch: {document_key}")
                if document_key != f"account:{document.account_id}":
                    raise ValueError(f"invalid account document key: {document_key}")
                document_path = (project.root / document.document_path).resolve()
                if (
                    not document_path.is_relative_to(account_root)
                    or document_path.suffix.lower() != ".md"
                ):
                    raise ValueError(f"document escapes the local account outbox: {document_key}")
                if not document_path.is_file():
                    raise ValueError(f"document is missing: {document.document_path}")
                if len(document_path.read_bytes()) != document.byte_size:
                    raise ValueError(f"document byte size mismatch: {document.document_path}")
                if document.evidence_document_path is not None:
                    evidence_path = (project.root / document.evidence_document_path).resolve()
                    if (
                        not evidence_path.is_relative_to(account_root)
                        or evidence_path.suffix.lower() != ".md"
                    ):
                        raise ValueError(
                            f"evidence document escapes the local account outbox: {document_key}"
                        )
                    if not evidence_path.is_file():
                        raise ValueError(
                            f"evidence document is missing: {document.evidence_document_path}"
                        )
                    if len(evidence_path.read_bytes()) != document.evidence_byte_size:
                        raise ValueError(
                            "evidence document byte size mismatch: "
                            f"{document.evidence_document_path}"
                        )
                for source_path in document.source_paths:
                    normalized = source_path.replace("\\", "/").lstrip("/")
                    source_root = normalized.partition("/")[0]
                    if (
                        normalized != source_path
                        or ".." in Path(normalized).parts
                        or source_root not in allowed_source_roots
                    ):
                        raise ValueError(f"unsafe evidence backlink: {source_path}")
        except (OSError, ValueError, ValidationError) as exc:
            errors.append(f"{project.relative(manifest_path)}: {exc}")

    return errors, artifact_count
