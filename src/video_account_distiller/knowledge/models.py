"""Validated contracts for local curated-knowledge export."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrictKnowledgeModel(BaseModel):
    """Strict model for state written by video-account-distiller."""

    model_config = ConfigDict(extra="forbid")


class KnowledgeDocumentManifest(StrictKnowledgeModel):
    schema_version: str = "1.0.0"
    export_id: str
    document_key: str
    account_id: str
    payload_hash: str
    document_path: str
    evidence_document_path: str | None = None
    source_paths: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)
    byte_size: int = Field(ge=0)
    evidence_byte_size: int = Field(default=0, ge=0)
    generated_at: datetime


class KnowledgeExportIndex(StrictKnowledgeModel):
    schema_version: str = "1.0.0"
    documents: dict[str, KnowledgeDocumentManifest] = Field(default_factory=dict)
