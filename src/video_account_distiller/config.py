"""Project configuration contract and YAML loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from video_account_distiller.errors import DistillerError, ErrorCode

DEFAULT_WEIGHTS = {
    "views": 0.25,
    "like_rate": 0.15,
    "comment_rate": 0.15,
    "share_rate": 0.15,
    "save_rate": 0.10,
    "follow_conversion": 0.10,
    "watch_efficiency": 0.10,
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


class ReportsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    formats: list[str] = Field(default_factory=lambda: ["markdown", "json"])
    include_evidence_index: bool = True


class DistillerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: ProjectSection
    analysis: AnalysisSection = Field(default_factory=AnalysisSection)
    platforms: PlatformSection = Field(default_factory=PlatformSection)
    privacy: PrivacySection = Field(default_factory=PrivacySection)
    reports: ReportsSection = Field(default_factory=ReportsSection)

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
