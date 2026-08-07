"""Project configuration contract and YAML loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from video_account_distiller.errors import DistillerError, ErrorCode

DEFAULT_WEIGHTS = {
    "views": 0.20,
    "like_rate": 0.10,
    "comment_rate": 0.10,
    "share_rate": 0.10,
    "save_rate": 0.06,
    "follow_conversion": 0.06,
    "watch_efficiency": 0.06,
    # Absolute interaction volumes proxy heat when views are unavailable;
    # they complement the rate terms when views are present.
    "likes_abs": 0.10,
    "comments_abs": 0.10,
    "shares_abs": 0.06,
    "saves_abs": 0.06,
}


class ProjectSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    language: str = "zh-CN"
    timezone: str = "Asia/Shanghai"


class AnalysisSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_sample_size: int = Field(default=40, ge=1, le=500)
    recent_sample_fraction: float = Field(default=0.20, gt=0, le=1)
    use_robust_zscore: bool = True
    log_transform_metrics: bool = True
    performance_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    min_pattern_support: int = Field(default=3, ge=2, le=100)
    min_validated_rule_support: int = Field(default=10, ge=3, le=1000)
    max_comments_per_analysis: int = Field(default=10000, ge=1, le=100000)


class PlatformSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: list[str] = Field(
        default_factory=lambda: [
            "douyin",
            "xiaohongshu",
            "wechat-channels",
            "bilibili",
            "tiktok",
            "youtube",
            "instagram",
        ]
    )
    cross_platform_raw_metric_comparison: bool = False


class PrivacySection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    redact_usernames_in_reports: bool = True
    hash_comment_author_ids: bool = True
    allow_cloud_model_upload: bool = False


class ModelsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text_provider: str | None = None
    vision_provider: str | None = None
    vision_model: str = "qwen3-vl-8b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    llamacpp_base_url: str = "http://127.0.0.1:8080"
    llamacpp_model: str | None = None
    llamacpp_api_key: str | None = None
    vision_batch_size: int = Field(default=4, ge=1, le=8)
    vision_timeout_seconds: int = Field(default=180, ge=1, le=1800)
    require_schema_validation: bool = True
    max_schema_attempts: int = Field(default=2, ge=1, le=5)
    allow_degraded_analysis: bool = True


class MediaSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
    scene_threshold: float = Field(default=0.30, gt=0, lt=1)
    max_shots: int = Field(default=500, ge=1, le=5000)
    max_keyframes: int = Field(default=12, ge=1, le=100)
    keyframe_width: int = Field(default=720, ge=160, le=3840)
    audio_sample_rate: int = Field(default=8000, ge=1000, le=48000)
    audio_window_ms: int = Field(default=100, ge=20, le=1000)
    silence_threshold_dbfs: float = Field(default=-40.0, ge=-100, le=0)
    max_audio_analysis_seconds: int = Field(default=600, ge=1, le=7200)
    command_timeout_seconds: int = Field(default=180, ge=1, le=3600)
    allow_degraded_without_ffmpeg: bool = True


class CollaborationSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=3, ge=0, le=8)
    retry_base_seconds: float = Field(default=0.5, ge=0, le=30)
    max_batch_rows: int = Field(default=500, ge=1, le=5000)


class ScoringSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_target_snapshot_age_hours: int = Field(default=72, ge=1, le=8760)
    snapshot_plan_hours: list[int] = Field(default_factory=lambda: [1, 24, 72, 168])
    prediction_metrics: list[str] = Field(
        default_factory=lambda: ["views", "engagement_rate_by_view"]
    )
    max_rule_score_adjustment: float = Field(default=5.0, ge=0, le=10)


class ReportsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    formats: list[str] = Field(default_factory=lambda: ["markdown", "json"])
    include_evidence_index: bool = True


class KnowledgeSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    obsidian_vault_path: str | None = Field(default=None, max_length=4096)


class DistillerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: ProjectSection
    analysis: AnalysisSection = Field(default_factory=AnalysisSection)
    platforms: PlatformSection = Field(default_factory=PlatformSection)
    privacy: PrivacySection = Field(default_factory=PrivacySection)
    models: ModelsSection = Field(default_factory=ModelsSection)
    media: MediaSection = Field(default_factory=MediaSection)
    collaboration: CollaborationSection = Field(default_factory=CollaborationSection)
    scoring: ScoringSection = Field(default_factory=ScoringSection)
    reports: ReportsSection = Field(default_factory=ReportsSection)
    knowledge: KnowledgeSection = Field(default_factory=KnowledgeSection)

    def as_yaml(self) -> str:
        """Serialize the validated configuration as stable YAML."""

        return yaml.safe_dump(self.model_dump(mode="json"), allow_unicode=True, sort_keys=False)


def default_config(project_name: str) -> DistillerConfig:
    """Build the default offline-safe project configuration."""

    return DistillerConfig(project=ProjectSection(name=project_name))


def load_config(path: Path) -> DistillerConfig:
    """Load and validate a project YAML configuration."""

    if not path.is_file():
        raise DistillerError(ErrorCode.PROJECT_NOT_INITIALIZED, f"Missing config: {path}")
    try:
        payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return DistillerConfig.model_validate(payload)
    except DistillerError:
        raise
    except Exception as exc:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            f"Invalid project config: {path}",
            details={"reason": str(exc)},
        ) from exc
