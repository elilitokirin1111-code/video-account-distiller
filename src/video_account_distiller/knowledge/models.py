"""Validated contracts for curated knowledge export and OpenKB responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictKnowledgeModel(BaseModel):
    """Strict model for state written by video-account-distiller."""

    model_config = ConfigDict(extra="forbid")


class OpenKBTarget(StrictKnowledgeModel):
    """Non-secret connection settings for one OpenKB knowledge base."""

    base_url: str
    kb: str = Field(min_length=1, max_length=128, pattern=r"^[\w-]+$")
    token_env: str = Field(
        default="DISTILLER_OPENKB_API_TOKEN",
        min_length=1,
        pattern=r"^[A-Z_][A-Z0-9_]*$",
    )
    timeout_seconds: int = Field(default=600, ge=1, le=1800)
    max_retries: int = Field(default=1, ge=0, le=3)


class KnowledgeDocumentManifest(StrictKnowledgeModel):
    schema_version: str = "1.0.0"
    export_id: str
    document_key: str
    account_id: str
    payload_hash: str
    document_path: str
    source_paths: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)
    byte_size: int = Field(ge=0)
    generated_at: datetime


class KnowledgeExportIndex(StrictKnowledgeModel):
    schema_version: str = "1.0.0"
    documents: dict[str, KnowledgeDocumentManifest] = Field(default_factory=dict)


class KnowledgeSyncRecord(StrictKnowledgeModel):
    schema_version: str = "1.0.0"
    document_key: str
    payload_hash: str
    remote_identifier: str
    kb: str
    base_url: str
    synced_at: datetime


class KnowledgeSyncIndex(StrictKnowledgeModel):
    schema_version: str = "1.0.0"
    documents: dict[str, KnowledgeSyncRecord] = Field(default_factory=dict)


class OpenKBResponseModel(BaseModel):
    """Tolerant validation boundary for the fast-moving external API."""

    model_config = ConfigDict(extra="allow")


class OpenKBInitResponse(OpenKBResponseModel):
    kb: str
    created: bool
    message: str | None = None


class OpenKBFileResult(OpenKBResponseModel):
    original_name: str
    saved_path: str | None = None
    status: str
    message: str | None = None


class OpenKBAddResponse(OpenKBResponseModel):
    kb: str
    files: list[OpenKBFileResult] = Field(default_factory=list)
    added_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)


class OpenKBRemoveResponse(OpenKBResponseModel):
    status: str
    name: str | None = None
    doc_name: str | None = None
    message: str | None = None


class OpenKBStatusResponse(OpenKBResponseModel):
    raw_count: int = Field(ge=0)
    total_indexed: int = Field(ge=0)
    directories: dict[str, Any] = Field(default_factory=dict)
    last_compile: str | None = None
    last_lint: str | None = None


class OpenKBQueryResponse(OpenKBResponseModel):
    answer: str
    saved_path: str | None = None
