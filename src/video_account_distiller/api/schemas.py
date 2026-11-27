"""Request and response Pydantic schemas for the REST API.

These are *API-layer* schemas that sit between the HTTP boundary and the
core domain models.  They are intentionally shallow — the heavy validation
lives in the existing ``video_account_distiller.models`` layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, model_validator

from video_account_distiller.collection import CollectionProfile
from video_account_distiller.insights import GptAnalysisRequest
from video_account_distiller.models import (
    CollectionProviderKind,
    CollectionSort,
    Platform,
)

CloudCredentialProvider = Literal["openai", "bailian", "deepseek"]

_CLOUD_PROVIDER_DEFAULT_BASE_URLS: dict[CloudCredentialProvider, str] = {
    "openai": "https://api.openai.com/v1",
    "bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com",
}


def cloud_endpoint_provider(base_url: str | None) -> CloudCredentialProvider | None:
    """Identify the credential owner for a known first-party cloud endpoint.

    Unknown OpenAI-compatible hosts intentionally return ``None`` so private
    gateways remain usable when the caller explicitly selects a credential
    slot.  Known vendor domains are matched by hostname (rather than a URL
    substring) so look-alike hosts cannot influence credential selection.
    """

    value = (base_url or "").strip()
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if hostname == "api.openai.com" or hostname.endswith(".openai.com"):
        return "openai"
    if hostname == "api.deepseek.com" or hostname.endswith(".deepseek.com"):
        return "deepseek"
    if hostname.endswith(".maas.aliyuncs.com") or (
        hostname.endswith(".aliyuncs.com") and hostname.startswith("dashscope")
    ):
        return "bailian"
    return None


def _model_provider_hint(model: str | None) -> CloudCredentialProvider | None:
    value = str(model or "").strip().casefold()
    if value.startswith("gpt-"):
        return "openai"
    if value.startswith("qwen"):
        return "bailian"
    if value.startswith("deepseek-"):
        return "deepseek"
    return None


def cloud_provider_default_base_url(provider: CloudCredentialProvider) -> str:
    """Return a first-party default that is safe for the selected key slot."""

    return _CLOUD_PROVIDER_DEFAULT_BASE_URLS[provider]


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


class CloudCredentialUpdate(BaseModel):
    api_key: SecretStr = Field(min_length=8, max_length=8_192)


class TaskRetryRequest(BaseModel):
    """Optional field overrides applied when retrying a failed workflow task.

    Only allowlisted workflow inputs may be overridden (model/provider/endpoint
    choices and scope), so a user can resume from the last safe checkpoint with
    a different cloud model instead of restarting the whole run.
    """

    overrides: dict[str, Any] | None = Field(default=None)


class TaskStatus(BaseModel):
    task_id: str
    status: Literal["pending", "running", "cancelling", "completed", "failed", "cancelled"]
    progress: float = 0.0
    task_type: str = "task"
    resource_class: str = "default"
    durable: bool = False
    queue_position: int | None = None
    result: Any | None = None
    error: ApiError | None = None


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class ProjectInitRequest(BaseModel):
    path: str = Field(..., description="Absolute path to the project directory")
    name: str | None = Field(None, description="Display name for the project")
    config_template: str | None = Field(
        None,
        description=(
            "Optional distiller.yaml path whose settings (models, media, "
            "analysis) are inherited by the new project."
        ),
    )


class ProjectInitResponse(BaseModel):
    project: str
    already_initialized: bool


class CloudModelSettingsUpdate(BaseModel):
    allow_cloud_model_upload: bool


class CloudPresetUpdate(BaseModel):
    """Cloud endpoint defaults plus an optional keyring credential update.

    Endpoint and model names are stored in ``distiller.yaml``. The API key is
    moved to the current user's operating-system keyring and never serialized
    into project configuration.
    """

    cloud_base_url: str | None = Field(default=None, max_length=2048)
    cloud_api_key: SecretStr | None = Field(default=None, max_length=2048)
    cloud_text_model: str | None = Field(default=None, max_length=128)
    cloud_vision_model: str | None = Field(default=None, max_length=128)


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
    distillation_mode: Literal["creative_learning", "knowledge"] = "creative_learning"
    model_output: str | None = Field(None, description="Path to pre-generated model output")
    max_attempts: int | None = Field(None, ge=1, le=5)
    strict_model: bool = False
    deep: bool = Field(
        False,
        description="Also run single-video deep distillation (topic/expression/craft/copy).",
    )
    deep_provider: str | None = Field(
        None, description="Deep distillation model provider: ollama, llamacpp, or cloud."
    )
    deep_model: str | None = Field(None, max_length=128)
    deep_base_url: str | None = Field(None, max_length=2048)
    deep_output: str | None = Field(None, description="Offline deep-distillation JSON path.")
    strict_deep: bool = False


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
    comment_video_limit: int | None = Field(default=None, ge=1, le=20_000)
    max_provider_calls: int | None = Field(default=None, ge=1, le=50_000)
    confirm_provider_cost: bool = False


class VideoUrlCollectParams(BaseModel):
    """Single-video collection: one public Douyin video URL."""

    url: str = Field(..., min_length=1, max_length=2048)
    provider: CollectionProviderKind = CollectionProviderKind.TIKHUB
    comments_per_video: int = Field(default=0, ge=0, le=200)
    confirm_provider_cost: bool = False


class AccountDistillWorkflowParams(CollectionAnalyzeParams):
    """Inputs for the self-service collect-to-knowledge workflow."""

    provider: CollectionProviderKind = CollectionProviderKind.MEDIACRAWLER
    distillation_mode: Literal["creative_learning", "knowledge"] = "creative_learning"
    media_limit: int | None = Field(default=None, ge=0, le=20_000)
    text_provider: Literal["llamacpp", "cloud"] | None = None
    whisper_backend: Literal["auto", "faster-whisper", "openai-whisper"] = "auto"
    whisper_model: str = Field(default="base", min_length=1, max_length=64)
    whisper_command: str | None = Field(default=None, max_length=2048)
    whisper_batch_size: int = Field(default=8, ge=1, le=32)
    vision_provider: Literal["ollama", "llamacpp", "cloud"] | None = "llamacpp"
    vision_model: str = Field(default="qwen3-vl-8b", min_length=1, max_length=128)
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", max_length=2048)
    cloud_base_url: str | None = Field(default=None, max_length=2048)
    cloud_text_base_url: str | None = Field(default=None, max_length=2048)
    cloud_credential_provider: CloudCredentialProvider | None = None
    cloud_api_key: SecretStr | None = Field(default=None, max_length=2048)
    cloud_text_model: str | None = Field(default=None, max_length=128)
    cloud_vision_model: str | None = Field(default=None, max_length=128)
    vision_batch_size: int = Field(default=4, ge=1, le=8)
    vision_timeout_seconds: int = Field(default=180, ge=1, le=1800)
    strict_media_enrichment: bool = False
    strict_vision: bool = False
    analysis_focus: Literal["general", "hospitality"] = "general"
    distill_video_knowledge: bool = False
    video_knowledge_provider: Literal["ollama", "llamacpp", "cloud", "none"] | None = None
    video_knowledge_model: str | None = Field(default=None, max_length=128)
    strict_video_knowledge: bool = False
    knowledge_analysis: GptAnalysisRequest | None = None
    export_knowledge: bool = True

    @model_validator(mode="before")
    @classmethod
    def mask_legacy_cloud_api_key_input(cls, value: Any) -> Any:
        """Wrap a legacy request-body key before any model-level error is built.

        Pydantic includes the complete model input for errors raised by an
        ``after`` validator. Mutating its transient input mapping here ensures
        that direct ``ValidationError.errors()`` calls and FastAPI's 422 body
        see a masked ``SecretStr`` rather than the credential's plaintext.
        """

        if isinstance(value, dict) and isinstance(value.get("cloud_api_key"), str):
            value["cloud_api_key"] = SecretStr(value["cloud_api_key"])
        return value

    @model_validator(mode="after")
    def validate_cloud_credential_routing(self) -> AccountDistillWorkflowParams:
        """Keep the one workflow credential within one provider trust boundary."""

        endpoint_routes = {
            "视频服务地址": cloud_endpoint_provider(self.cloud_base_url),
            "文本/蒸馏服务地址": cloud_endpoint_provider(self.cloud_text_base_url),
        }
        endpoint_providers = {provider for provider in endpoint_routes.values() if provider}
        if len(endpoint_providers) > 1:
            raise ValueError(
                "视频服务地址与文本/蒸馏服务地址属于不同服务商；当前工作流只允许使用一份"
                "云端凭据，已拒绝请求以避免 API Key 被发送到错误域名。请把两个地址设为同一"
                "服务商，或拆分为两次任务。"
            )
        if self.cloud_credential_provider is not None:
            mismatched_routes = [
                label
                for label, provider in endpoint_routes.items()
                if provider is not None and provider != self.cloud_credential_provider
            ]
            if mismatched_routes:
                raise ValueError(
                    f"所选云端凭据服务商 {self.cloud_credential_provider!r} 与"
                    f"{'、'.join(mismatched_routes)}的域名不一致；已拒绝发送 API Key。"
                )

        if self.knowledge_analysis is not None:
            analysis_endpoint_provider = cloud_endpoint_provider(
                self.cloud_text_base_url or self.cloud_base_url
            )
            if (
                analysis_endpoint_provider is not None
                and analysis_endpoint_provider != self.knowledge_analysis.provider.value
            ):
                raise ValueError(
                    "账号深度分析服务商与文本/蒸馏地址的域名不一致；已拒绝发送该服务商的"
                    " API Key。当前工作流的云端分析端点必须属于同一服务商。"
                )

        model_hints = _active_cloud_model_provider_hints(self)
        if (
            self.cloud_credential_provider is None
            and not endpoint_providers
            and len(model_hints) > 1
        ):
            raise ValueError(
                "云端视觉与文本模型指向不同服务商，但未指定服务商或服务地址；请明确选择"
                "云端凭据服务商和对应地址。"
            )

        models = [self.cloud_text_model, self.video_knowledge_model]
        if not any(str(model or "").casefold().startswith("deepseek-v4-") for model in models):
            return self
        text_base_url = (self.cloud_text_base_url or self.cloud_base_url or "").strip()
        if resolve_account_distill_cloud_credential_provider(self) != "bailian":
            return self
        parsed = urlparse(text_base_url)
        hostname = (parsed.hostname or "").casefold()
        valid_workspace = (
            parsed.scheme == "https"
            and hostname.endswith(".maas.aliyuncs.com")
            and parsed.path.rstrip("/").endswith("/compatible-mode/v1")
        )
        if not valid_workspace:
            raise ValueError(
                "百炼 DeepSeek V4 需要工作空间专属 MaaS 地址（https://{WorkspaceId}."
                "<region>.maas.aliyuncs.com/compatible-mode/v1）；通用 DashScope 地址只保留给"
                " Qwen 视频解析。请在“文本/蒸馏服务地址”中填写工作空间地址，或将蒸馏模型改为"
                " qwen3.7-plus。"
            )
        return self


def _active_cloud_model_provider_hints(
    body: AccountDistillWorkflowParams,
) -> set[CloudCredentialProvider]:
    models: list[str | None] = []
    if body.vision_provider == "cloud":
        models.append(body.cloud_vision_model or body.vision_model)
    if body.text_provider == "cloud":
        models.append(body.cloud_text_model)
    if body.video_knowledge_provider == "cloud":
        models.append(body.video_knowledge_model or body.cloud_text_model)
    return {provider for model in models if (provider := _model_provider_hint(model))}


def resolve_account_distill_cloud_credential_provider(
    body: AccountDistillWorkflowParams,
) -> CloudCredentialProvider:
    """Resolve the keyring slot after the schema has validated endpoint ownership."""

    if body.cloud_credential_provider is not None:
        return body.cloud_credential_provider
    endpoint_providers = {
        provider
        for base_url in (body.cloud_base_url, body.cloud_text_base_url)
        if (provider := cloud_endpoint_provider(base_url)) is not None
    }
    if endpoint_providers:
        # The model validator rejects mixed known providers before callers use
        # this resolver, but sorting keeps this helper deterministic in all
        # direct-call contexts.
        return sorted(endpoint_providers)[0]
    model_hints = _active_cloud_model_provider_hints(body)
    if len(model_hints) == 1:
        return next(iter(model_hints))
    if body.knowledge_analysis is not None:
        return body.knowledge_analysis.provider.value
    return "openai"


def materialize_account_distill_cloud_routing(
    body: AccountDistillWorkflowParams,
    *,
    fallback_base_url: str | None = None,
) -> AccountDistillWorkflowParams:
    """Freeze the effective cloud routes before a credential is resolved.

    Project presets and provider-specific defaults otherwise remain implicit
    until deep inside the workflow. Materializing them at the API/task boundary
    lets the same schema ownership checks run before any keyring value is read.
    """

    shared_cloud_requested = (
        body.text_provider == "cloud"
        or body.vision_provider == "cloud"
        or body.video_knowledge_provider == "cloud"
    )
    if not shared_cloud_requested:
        return body

    payload = body.model_dump(mode="python")
    configured_base_url = body.cloud_base_url or fallback_base_url
    if configured_base_url is not None:
        payload["cloud_base_url"] = configured_base_url
        provisional = AccountDistillWorkflowParams.model_validate(payload)
    else:
        provisional = body
    provider = resolve_account_distill_cloud_credential_provider(provisional)
    effective_base_url = configured_base_url or cloud_provider_default_base_url(provider)
    text_cloud_requested = body.text_provider == "cloud" or body.video_knowledge_provider == "cloud"
    payload.update(
        {
            "cloud_base_url": effective_base_url,
            "cloud_text_base_url": (
                body.cloud_text_base_url or effective_base_url
                if text_cloud_requested
                else body.cloud_text_base_url
            ),
            "cloud_credential_provider": provider,
        }
    )
    return AccountDistillWorkflowParams.model_validate(payload)


class AccountMediaReparseParams(BaseModel):
    """Selectively retry retained videos without repeating account collection."""

    mode: Literal["failed_or_degraded", "selected", "all"] = "failed_or_degraded"
    video_ids: list[str] = Field(default_factory=list, max_length=20_000)
    limit: int = Field(default=50, ge=1, le=20_000)
    refresh_media: bool = True
    whisper_backend: Literal["auto", "faster-whisper", "openai-whisper"] = "auto"
    whisper_model: str = Field(default="small", min_length=1, max_length=64)
    whisper_command: str | None = Field(default=None, max_length=2048)
    whisper_batch_size: int = Field(default=8, ge=1, le=32)
    vision_provider: Literal["ollama", "llamacpp"] | None = "llamacpp"
    vision_model: str = Field(default="qwen3-vl-8b", min_length=1, max_length=128)
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", max_length=2048)
    vision_batch_size: int = Field(default=4, ge=1, le=8)
    vision_timeout_seconds: int = Field(default=180, ge=1, le=1800)
    strict_media_enrichment: bool = False
    strict_vision: bool = False


# ---------------------------------------------------------------------------
# Local curated knowledge
# ---------------------------------------------------------------------------


class KnowledgeExportParams(BaseModel):
    max_video_analyses: int = Field(default=100, ge=1, le=1_000)
    max_export_bytes: int = Field(default=1_000_000, ge=10_000, le=5_000_000)


class AccountVideoKnowledgeParams(BaseModel):
    """Batch knowledge-first extraction options for every eligible account video."""

    limit: int | None = Field(default=None, ge=1, le=20_000)
    provider: Literal["ollama", "llamacpp", "cloud", "none"] | None = None
    model: str | None = Field(default=None, max_length=128)
    base_url: str | None = Field(default=None, max_length=2048)
    max_attempts: int | None = Field(default=None, ge=1, le=5)
    strict_model: bool = False


class ObsidianSyncParams(KnowledgeExportParams):
    vault_path: str | None = Field(default=None, max_length=4096)


class WeKnoraConnectionParams(BaseModel):
    base_url: str = Field(default="http://127.0.0.1:8080", max_length=2048)
    api_key: str = Field(min_length=1, max_length=2048)


class WeKnoraSyncParams(KnowledgeExportParams):
    base_url: str = Field(default="http://127.0.0.1:8080", max_length=2048)
    api_key: str = Field(min_length=1, max_length=2048)
    kb_id: str = Field(min_length=1, max_length=128)
    distillation_mode: Literal["creative_learning", "knowledge"] = "creative_learning"
