"""Orchestration for one-way Distiller-to-OpenKB synchronization."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.knowledge.client import OpenKBClient
from video_account_distiller.knowledge.exporter import (
    DEFAULT_MAX_EXPORT_BYTES,
    KnowledgeExportService,
)
from video_account_distiller.knowledge.models import (
    KnowledgeDocumentManifest,
    KnowledgeSyncIndex,
    KnowledgeSyncRecord,
    OpenKBTarget,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import atomic_write_json, read_json

DEFAULT_OPENKB_BASE_URL = "http://127.0.0.1:7566"
DEFAULT_OPENKB_TOKEN_ENV = "DISTILLER_OPENKB_API_TOKEN"


def _default_kb(project: ProjectLayout) -> str:
    return f"distiller-{project.load_state().project_id}"


def resolve_openkb_target(
    project: ProjectLayout,
    *,
    base_url: str | None = None,
    kb: str | None = None,
    token_env: str = DEFAULT_OPENKB_TOKEN_ENV,
    timeout_seconds: int = 600,
    max_retries: int = 1,
    require_remote_token: bool = True,
) -> tuple[OpenKBTarget, str | None]:
    """Resolve safe non-secret settings and the optional bearer token."""

    resolved_url = (
        base_url or os.environ.get("DISTILLER_OPENKB_BASE_URL") or DEFAULT_OPENKB_BASE_URL
    ).rstrip("/")
    resolved_kb = kb or os.environ.get("DISTILLER_OPENKB_KB") or _default_kb(project)
    parsed = urlsplit(resolved_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            (
                "OpenKB base URL must be an HTTP(S) origin without credentials, "
                "path, query, or fragment"
            ),
        )
    is_loopback = parsed.hostname.casefold() in {"127.0.0.1", "::1", "localhost"}
    if parsed.scheme == "http" and not is_loopback:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Plain HTTP OpenKB connections are limited to loopback hosts",
            details={"base_url": resolved_url},
        )
    token = os.environ.get(token_env)
    token = token.strip() if token and token.strip() else None
    if require_remote_token and not is_loopback and token is None:
        raise DistillerError(
            ErrorCode.ADAPTER_AUTH,
            "Remote OpenKB connections require a bearer token",
            details={"token_env": token_env},
        )
    try:
        target = OpenKBTarget(
            base_url=resolved_url,
            kb=resolved_kb,
            token_env=token_env,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
    except ValidationError as exc:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "OpenKB target configuration is invalid",
        ) from exc
    return target, token


class OpenKBIntegrationService:
    """Export curated account knowledge, sync it, and query the external KB."""

    def __init__(
        self,
        project: ProjectLayout,
        client: OpenKBClient,
    ) -> None:
        self.project = project
        self.client = client
        self.exporter = KnowledgeExportService(project)
        self.sync_path = self.exporter.root / "sync-state.json"

    @classmethod
    def from_target(
        cls,
        project: ProjectLayout,
        target: OpenKBTarget,
        *,
        token: str | None,
    ) -> OpenKBIntegrationService:
        return cls(project, OpenKBClient(target, token=token))

    def _load_sync_index(self) -> KnowledgeSyncIndex:
        if not self.sync_path.is_file():
            return KnowledgeSyncIndex()
        try:
            return KnowledgeSyncIndex.model_validate(read_json(self.sync_path))
        except (OSError, ValueError, ValidationError) as exc:
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                "OpenKB sync state is invalid",
                details={"path": self.project.relative(self.sync_path)},
            ) from exc

    @staticmethod
    def require_model_confirmation(confirm_model_processing: bool) -> None:
        if not confirm_model_processing:
            raise DistillerError(
                ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED,
                "OpenKB compilation/query may invoke a configured model and requires confirmation",
                details={"required": "confirm_model_processing=true"},
            )

    def sync_account(
        self,
        *,
        account_id: str,
        confirm_model_processing: bool,
        create_kb: bool = True,
        force: bool = False,
        max_video_analyses: int = 10,
        max_export_bytes: int = DEFAULT_MAX_EXPORT_BYTES,
        dry_run: bool = False,
    ) -> dict[str, object]:
        if not dry_run:
            self.require_model_confirmation(confirm_model_processing)
        export_result = self.exporter.export_account(
            account_id=account_id,
            max_video_analyses=max_video_analyses,
            max_export_bytes=max_export_bytes,
            dry_run=dry_run,
        )
        manifest = KnowledgeDocumentManifest.model_validate(export_result["manifest"])
        sync_index = self._load_sync_index()
        previous = sync_index.documents.get(manifest.document_key)
        same_target = (
            previous is not None
            and previous.kb == self.client.target.kb
            and previous.base_url == self.client.target.base_url
        )
        unchanged = (
            previous is not None and previous.payload_hash == manifest.payload_hash and same_target
        )
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "would_create_kb": create_kb,
                "would_remove_previous": (
                    previous is not None and same_target and (force or not unchanged)
                ),
                "would_upload": force or not unchanged,
                "export": export_result,
                "target": {
                    "base_url": self.client.target.base_url,
                    "kb": self.client.target.kb,
                    "token_configured": self.client.token_configured,
                },
            }
        if unchanged and not force:
            assert previous is not None
            return {
                "ok": True,
                "dry_run": False,
                "status": "skipped",
                "reason": "payload_hash_already_synced",
                "export": export_result,
                "sync": previous.model_dump(mode="json"),
            }

        init_result = self.client.init_kb() if create_kb else None
        removed = None
        if previous is not None and same_target:
            removed = self.client.remove_document(previous.remote_identifier)
        document_path = self.project.root / Path(manifest.document_path)
        added = self.client.add_document(document_path, payload_hash=manifest.payload_hash)
        if added.failed_count > 0 or added.added_count + added.skipped_count < 1:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "OpenKB did not accept the curated knowledge document",
                details={
                    "failed_count": added.failed_count,
                    "added_count": added.added_count,
                    "skipped_count": added.skipped_count,
                },
            )
        remote_identifier = document_path.name
        if added.files and added.files[0].original_name:
            remote_identifier = added.files[0].original_name
        record = KnowledgeSyncRecord(
            document_key=manifest.document_key,
            payload_hash=manifest.payload_hash,
            remote_identifier=remote_identifier,
            kb=self.client.target.kb,
            base_url=self.client.target.base_url,
            synced_at=datetime.now(UTC),
        )
        sync_index.documents[manifest.document_key] = record
        atomic_write_json(self.sync_path, sync_index.model_dump(mode="json"))
        return {
            "ok": True,
            "dry_run": False,
            "status": "synced",
            "export": export_result,
            "init": None if init_result is None else init_result.model_dump(mode="json"),
            "removed": None if removed is None else removed.model_dump(mode="json"),
            "added": added.model_dump(mode="json"),
            "sync": record.model_dump(mode="json"),
            "sync_state_path": self.project.relative(self.sync_path),
        }

    def status(self, *, account_id: str, remote: bool = False) -> dict[str, object]:
        document_key = f"account:{account_id}"
        sync_index = self._load_sync_index()
        record = sync_index.documents.get(document_key)
        remote_status = self.client.status() if remote else None
        return {
            "ok": True,
            "account_id": account_id,
            "configured": True,
            "target": {
                "base_url": self.client.target.base_url,
                "kb": self.client.target.kb,
                "token_configured": self.client.token_configured,
            },
            "sync": None if record is None else record.model_dump(mode="json"),
            "remote": None if remote_status is None else remote_status.model_dump(mode="json"),
        }

    def query(
        self,
        *,
        question: str,
        confirm_model_processing: bool,
        save: bool = False,
    ) -> dict[str, object]:
        self.require_model_confirmation(confirm_model_processing)
        cleaned = question.strip()
        if not cleaned:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "OpenKB question must not be empty")
        if len(cleaned) > 8_000:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "OpenKB question exceeds the 8000-character limit",
            )
        response = self.client.query(cleaned, save=save)
        return {
            "ok": True,
            "answer": response.answer,
            "saved_path": response.saved_path,
            "kb": self.client.target.kb,
            "authoritative": False,
            "analysis_contract": [
                "Treat this answer as derived knowledge, not source evidence.",
                "Verify important claims against Distiller evidence backlinks.",
                "Do not infer missing metrics, private data, or causality.",
            ],
        }
