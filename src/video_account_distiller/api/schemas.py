"""Request and response Pydantic schemas for the REST API.

These are *API-layer* schemas that sit between the HTTP boundary and the
core domain models.  They are intentionally shallow — the heavy validation
lives in the existing ``video_account_distiller.models`` layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from video_account_distiller.collection import CollectionProfile
from video_account_distiller.models import (
    CollectionProviderKind,
    CollectionSort,
    Platform,
)

# ---------------------------------------------------------------------------
# Generic envelopes
# ---------------------------------------------------------------------------


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ApiResponse(BaseModel):
    ok: bool
    data: Any | None = None
    error: ApiError | None = None


class TaskStatus(BaseModel):
    task_id: str
    status: str  # pending | running | completed | failed
    progress: float = 0.0
    result: Any | None = None
    error: ApiError | None = None


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class ProjectInitRequest(BaseModel):
    path: str = Field(..., description="Absolute path to the project directory")
    name: str | None = Field(None, description="Display name for the project")


class ProjectInitResponse(BaseModel):
    project: str
    already_initialized: bool


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class ImportParams(BaseModel):
    platform: Platform
    mapping_path: str | None = Field(None, description="Optional field-mapping YAML path")


class TranscriptImportParams(BaseModel):
    video_id: str
    language: str | None = None
    source_name: str = "user_subtitle"


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


class VideoAnalysisParams(BaseModel):
    model_output: str | None = Field(None, description="Path to pre-generated model output")
    max_attempts: int | None = Field(None, ge=1, le=5)
    strict_model: bool = False


class CommentAnalysisParams(BaseModel):
    model_output: str | None = Field(None)
    max_attempts: int | None = Field(None, ge=1, le=5)
    strict_model: bool = False


class MediaAnalysisParams(BaseModel):
    file: str | None = Field(None, description="Path to local media file")
    vision_output: str | None = Field(None)
    strict_media: bool = False
    strict_vision: bool = False
    scene_threshold: float | None = Field(None, gt=0, lt=1)
    max_keyframes: int | None = Field(None, ge=1, le=100)


# ---------------------------------------------------------------------------
# Sampling & Reporting
# ---------------------------------------------------------------------------


class SampleParams(BaseModel):
    size: int | None = Field(None, ge=1, le=500)


class ReportParams(BaseModel):
    sample_size: int | None = Field(None, ge=1, le=500)


# ---------------------------------------------------------------------------
# Distillation
# ---------------------------------------------------------------------------


class CompareParams(BaseModel):
    target_account_id: str
    benchmark_account_ids: list[str] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Closed-loop
# ---------------------------------------------------------------------------


class ScoreParams(BaseModel):
    script: str = Field(..., description="Path to script file")
    title: str | None = None
    topic: str | None = None
    target_pillar: str | None = None
    target_metric: str = "performance_score"
    planned_publish_hour: int | None = Field(None, ge=0, le=23)


class PredictParams(BaseModel):
    script: str = Field(..., description="Path to script file")
    title: str | None = None
    topic: str | None = None
    target_pillar: str | None = None
    target_metric: str = "performance_score"
    target_age_hours: int | None = Field(None, ge=1)
    planned_publish_hour: int | None = Field(None, ge=0, le=23)


class PublishParams(BaseModel):
    prediction_id: str
    video_id: str
    published_at: datetime | None = None
    url: str | None = None
    notes: str | None = None


class RetroParams(BaseModel):
    snapshot: str = "t3d"
    target_age_hours: int | None = Field(None, ge=1)


# ---------------------------------------------------------------------------
# Collection (Phase 8)
# ---------------------------------------------------------------------------


class CollectionAnalyzeParams(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    profile: CollectionProfile = CollectionProfile.STANDARD
    count: int | None = Field(default=None, ge=1, le=20_000)
    all_videos: bool = False
    sort: CollectionSort = CollectionSort.LATEST
    provider: CollectionProviderKind = CollectionProviderKind.TIKHUB
    comments_per_video: int | None = Field(default=None, ge=0, le=20)
    comment_video_limit: int = Field(default=3, ge=1, le=10)
    max_provider_calls: int | None = Field(default=None, ge=1, le=50_000)
    confirm_provider_cost: bool = False


# ---------------------------------------------------------------------------
# Curated knowledge / OpenKB
# ---------------------------------------------------------------------------


class KnowledgeExportParams(BaseModel):
    max_video_analyses: int = Field(default=10, ge=1, le=25)
    max_export_bytes: int = Field(default=1_000_000, ge=10_000, le=5_000_000)


class OpenKBSyncParams(KnowledgeExportParams):
    confirm_model_processing: bool = False
    create_kb: bool = True
    force: bool = False


class OpenKBQueryParams(BaseModel):
    question: str = Field(min_length=1, max_length=8_000)
    confirm_model_processing: bool = False
    save: bool = False
