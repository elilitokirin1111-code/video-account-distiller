"""Audited, privacy-gated account analysis through selectable cloud providers."""

# ruff: noqa: E501
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from video_account_distiller.adapters.collaboration import HttpExecutor, UrllibHttpExecutor
from video_account_distiller.common.http_utils import read_env_credential, request_json
from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights.context import AnalysisContextService
from video_account_distiller.models.collaboration import RetryPolicy
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import (
    atomic_write_json,
    atomic_write_text,
    read_json,
)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
BAILIAN_API_KEY_ENV = "DASHSCOPE_API_KEY"
BAILIAN_BASE_URL_ENV = "DASHSCOPE_BASE_URL"
BAILIAN_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"
DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
GPT_ANALYSIS_VERSION = "1.4.0"
GPT_PROMPT_VERSION = "account-learning-playbook-v5"
GPT_EVALUATION_VERSION = "account-analysis-eval-v2"
GPT_PRICING_SNAPSHOT = "openai-api-pricing-2026-07-28"
BAILIAN_PRICING_SNAPSHOT = "aliyun-model-studio-pricing-2026-08-04"
DEEPSEEK_PRICING_SNAPSHOT = "deepseek-api-pricing-2026-08-05"
MAX_CLOUD_CONTEXT_BYTES = 1_500_000
MAX_OUTPUT_TOKENS = 5_000
MODEL_MAX_INPUT_TOKENS = 922_000
LONG_CONTEXT_THRESHOLD_TOKENS = 272_000
_EVALUATION_RUN_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")

# Model Studio MaaS caps qwen-max/qwen-plus/qwen-turbo input at 30,720 tokens;
# ~3.3 UTF-8 bytes per token for Chinese gives roughly 100 KB. Use a conservative
# byte budget so the analysis context is trimmed before the provider rejects it.
# qwen3.7-plus carries a 1M-token context window (max output 65,536), matching
# qwen3.8-max, so it gets the same generous input budget.
_MODEL_INPUT_BUDGET_BYTES: dict[str, int] = {
    "qwen3.8-max": 1_000_000,
    "qwen3.7-plus": 1_000_000,
    "qwen-max": 80_000,
    "qwen-plus": 80_000,
    "qwen-turbo": 80_000,
    "qwen3.7-max": 400_000,
    "qwen3.6-max": 400_000,
    "qwen-long": 1_400_000,
}

# Model Studio reasoning models (qwen3.8-max and friends) consume a large share
# of the completion budget on thinking tokens before emitting the JSON payload.
# A hard cap of 8,000 tokens truncated the full account analysis mid-object
# (finish_reason=length) and surfaced as E_MODEL_SCHEMA_INVALID. Keep the
# output budget per model well above the observed ~16K-token complete output.
#
# DeepSeek thinking mode counts reasoning tokens against max_tokens: a 220KB
# account context already consumed ~13.5K completion tokens, so 16K left no
# headroom and high-effort runs occasionally truncated. The API accepts up to
# 65536, so reasoning models get a generous budget that covers thinking plus
# the full JSON payload. qwen3.7-plus advertises a 65,536 max output, so it
# gets the same ceiling as DeepSeek reasoning models.
_MODEL_OUTPUT_BUDGET_TOKENS: dict[str, int] = {
    "qwen3.8-max": 32_768,
    "qwen3.7-max": 32_768,
    "qwen3.7-plus": 65_536,
    "qwen3.6-max": 32_768,
    "qwen-long": 32_768,
    "qwen-max": 8_192,
    "qwen-plus": 8_192,
    "qwen-turbo": 8_192,
    "qwen-plus-latest": 8_192,
    "deepseek-v4-flash": 65_536,
    "deepseek-v4-pro": 65_536,
    "deepseek-chat": 65_536,
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenAIModel(StrEnum):
    SOL = "gpt-5.6-sol"
    TERRA = "gpt-5.6-terra"
    LUNA = "gpt-5.6-luna"


class BailianModel(StrEnum):
    QWEN_3_8_MAX = "qwen3.8-max"
    QWEN_3_7_PLUS = "qwen3.7-plus"
    QWEN_3_7_MAX = "qwen3.7-max"
    QWEN_MAX = "qwen-max"
    QWEN_PLUS = "qwen-plus"
    QWEN_TURBO = "qwen-turbo"
    QWEN_LONG = "qwen-long"
    QWEN_PLUS_LATEST = "qwen-plus-latest"


class DeepSeekModel(StrEnum):
    V4_FLASH = "deepseek-v4-flash"
    V4_PRO = "deepseek-v4-pro"
    CHAT = "deepseek-chat"


class AnalysisProviderKind(StrEnum):
    OPENAI = "openai"
    BAILIAN = "bailian"
    DEEPSEEK = "deepseek"


AnalysisModel = OpenAIModel | BailianModel | DeepSeekModel


class AnalysisTemplate(StrEnum):
    ACCOUNT_HEALTH = "account_health"
    CONTENT_STRATEGY = "content_strategy"
    GROWTH_PLAN = "growth_plan"


class ReasoningEffort(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class GptAnalysisOptions(StrictModel):
    """Secret-free options that may safely enter task memory and audit metadata."""

    provider: AnalysisProviderKind = AnalysisProviderKind.DEEPSEEK
    model: AnalysisModel = DeepSeekModel.V4_FLASH
    template: AnalysisTemplate = AnalysisTemplate.CONTENT_STRATEGY
    reasoning_effort: ReasoningEffort = ReasoningEffort.HIGH
    max_video_analyses: int = Field(default=100, ge=1, le=1_000)
    confirm_cloud_upload: bool = False
    confirm_cost: bool = False

    @model_validator(mode="before")
    @classmethod
    def infer_provider_from_explicit_model(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "provider" in value or "model" not in value:
            return value
        model = value.get("model")
        model_value = model.value if isinstance(model, StrEnum) else str(model)
        inferred = (
            AnalysisProviderKind.OPENAI
            if model_value.startswith("gpt-")
            else AnalysisProviderKind.DEEPSEEK
            if model_value.startswith("deepseek-")
            else AnalysisProviderKind.BAILIAN
        )
        return {**value, "provider": inferred}

    @model_validator(mode="after")
    def validate_provider_model(self) -> Self:
        expected_by_provider = {
            AnalysisProviderKind.OPENAI: OpenAIModel,
            AnalysisProviderKind.BAILIAN: BailianModel,
            AnalysisProviderKind.DEEPSEEK: DeepSeekModel,
        }
        expected = expected_by_provider.get(self.provider, BailianModel)
        if not isinstance(self.model, expected):
            raise ValueError(
                f"model {self.model.value!r} is not available for provider {self.provider.value!r}"
            )
        return self


class GptAnalysisRequest(GptAnalysisOptions):
    """Secret-free analysis request; credentials are resolved by the API service."""

    def options(self) -> GptAnalysisOptions:
        return GptAnalysisOptions.model_validate(self.model_dump(mode="python"))


class GptFinding(StrictModel):
    classification: Literal[
        "observed_fact",
        "statistical_association",
        "hypothesis",
        "recommendation",
    ]
    title: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)
    confidence: Literal["low", "medium", "high"]


class GptPriorityAction(StrictModel):
    priority: int = Field(ge=1, le=5)
    action: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=1_500)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class GptExperiment(StrictModel):
    hypothesis: str = Field(min_length=1, max_length=1_000)
    action: str = Field(min_length=1, max_length=1_000)
    primary_metric: str = Field(min_length=1, max_length=160)
    observation_window: str = Field(min_length=1, max_length=160)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class GptKnowledgeCard(StrictModel):
    """One reusable, falsifiable operating proposition derived from evidence."""

    title: str = Field(min_length=1, max_length=160)
    claim: str = Field(min_length=1, max_length=2_000)
    knowledge_type: Literal["observation", "hypothesis", "experimental_rule"]
    mechanism: str = Field(min_length=1, max_length=2_000)
    competing_explanations: list[str] = Field(min_length=1, max_length=5)
    falsifier: str = Field(min_length=1, max_length=1_500)
    decision: str = Field(min_length=1, max_length=1_500)
    scope: list[str] = Field(min_length=1, max_length=8)
    boundary_conditions: list[str] = Field(min_length=1, max_length=8)
    tradeoff: str = Field(min_length=1, max_length=1_000)
    success_condition: str = Field(min_length=1, max_length=1_000)
    stop_condition: str = Field(min_length=1, max_length=1_000)
    target_metric: str = Field(min_length=1, max_length=160)
    maturity_level: int = Field(ge=0, le=3)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)
    confidence: Literal["low", "medium", "high"]


class GptImitationPlaybook(StrictModel):
    """A transferable way to reproduce the mechanism without copying the surface."""

    title: str = Field(min_length=1, max_length=160)
    learned_insight: str = Field(min_length=1, max_length=1_500)
    why_it_works: str = Field(min_length=1, max_length=1_500)
    copy_this: list[str] = Field(min_length=1, max_length=6)
    do_not_copy: list[str] = Field(min_length=1, max_length=5)
    adaptation_steps: list[str] = Field(min_length=2, max_length=7)
    suitable_for: list[str] = Field(min_length=1, max_length=6)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)
    confidence: Literal["low", "medium", "high"]


class GptCreativeExtension(StrictModel):
    """One executable creative direction derived from an observed mechanism."""

    title: str = Field(min_length=1, max_length=160)
    derived_from: str = Field(min_length=1, max_length=1_000)
    concept: str = Field(min_length=1, max_length=1_500)
    execution: list[str] = Field(min_length=2, max_length=7)
    trend_relevance: Literal[
        "evidence_backed_recent",
        "evergreen_extension",
        "needs_current_trend_check",
    ]
    trend_basis: str | None = Field(default=None, max_length=1_000)
    risk_or_boundary: str = Field(min_length=1, max_length=1_000)
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class GptAccountAnalysis(StrictModel):
    executive_summary: str = Field(min_length=1, max_length=3_000)
    findings: list[GptFinding] = Field(min_length=1, max_length=12)
    imitation_playbooks: list[GptImitationPlaybook] = Field(default_factory=list, max_length=6)
    creative_extensions: list[GptCreativeExtension] = Field(default_factory=list, max_length=8)
    priority_actions: list[GptPriorityAction] = Field(min_length=1, max_length=8)
    experiments: list[GptExperiment] = Field(max_length=6)
    knowledge_cards: list[GptKnowledgeCard] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(min_length=1, max_length=12)


@dataclass(frozen=True)
class ProviderAnalysis:
    response_id: str
    model: str
    status: str
    analysis: GptAccountAnalysis
    usage: dict[str, Any]


class AccountAnalysisProvider(Protocol):
    provider_name: str
    model_name: str
    credential_env: str
    credential_source: str

    def analyze(self, *, instructions: str, context_json: str) -> ProviderAnalysis: ...


@dataclass(frozen=True)
class ModelPricing:
    currency: Literal["USD", "CNY"]
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float
    source_url: str
    snapshot: str
    authoritative_source: str
    max_input_tokens: int = MODEL_MAX_INPUT_TOKENS
    long_context_threshold_tokens: int = LONG_CONTEXT_THRESHOLD_TOKENS
    long_context_input_multiplier: float = 2.0
    long_context_output_multiplier: float = 1.5
    cache_write_multiplier: float = 1.25

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "unit": "per_1m_tokens",
            "input": self.input_per_million,
            "cached_input": self.cached_input_per_million,
            "output": self.output_per_million,
            "cache_write_multiplier": self.cache_write_multiplier,
            "long_context_threshold_tokens": self.long_context_threshold_tokens,
            "long_context_input_multiplier": self.long_context_input_multiplier,
            "long_context_output_multiplier": self.long_context_output_multiplier,
            "snapshot": self.snapshot,
            "source_url": self.source_url,
        }


MODEL_PRICING: dict[AnalysisModel, ModelPricing] = {
    OpenAIModel.SOL: ModelPricing(
        currency="USD",
        input_per_million=5.0,
        cached_input_per_million=0.5,
        output_per_million=30.0,
        source_url="https://developers.openai.com/api/docs/models/gpt-5.6-sol",
        snapshot=GPT_PRICING_SNAPSHOT,
        authoritative_source="OpenAI billing dashboard/invoice",
    ),
    OpenAIModel.TERRA: ModelPricing(
        currency="USD",
        input_per_million=2.5,
        cached_input_per_million=0.25,
        output_per_million=15.0,
        source_url="https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        snapshot=GPT_PRICING_SNAPSHOT,
        authoritative_source="OpenAI billing dashboard/invoice",
    ),
    OpenAIModel.LUNA: ModelPricing(
        currency="USD",
        input_per_million=1.0,
        cached_input_per_million=0.1,
        output_per_million=6.0,
        source_url="https://developers.openai.com/api/docs/models/gpt-5.6-luna",
        snapshot=GPT_PRICING_SNAPSHOT,
        authoritative_source="OpenAI billing dashboard/invoice",
    ),
    BailianModel.QWEN_3_7_PLUS: ModelPricing(
        currency="CNY",
        input_per_million=2.0,
        cached_input_per_million=2.0,
        output_per_million=8.0,
        source_url="https://help.aliyun.com/zh/model-studio/model-pricing",
        snapshot=BAILIAN_PRICING_SNAPSHOT,
        authoritative_source="Alibaba Cloud Model Studio console/invoice",
        max_input_tokens=983_000,
        long_context_threshold_tokens=256_000,
        long_context_input_multiplier=3.0,
        long_context_output_multiplier=3.0,
        cache_write_multiplier=1.0,
    ),
    DeepSeekModel.V4_FLASH: ModelPricing(
        currency="USD",
        input_per_million=0.14,
        cached_input_per_million=0.0028,
        output_per_million=0.28,
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
        snapshot=DEEPSEEK_PRICING_SNAPSHOT,
        authoritative_source="DeepSeek platform pricing",
        max_input_tokens=1_000_000,
        long_context_threshold_tokens=1_000_000,
        long_context_input_multiplier=1.0,
        long_context_output_multiplier=1.0,
        cache_write_multiplier=1.0,
    ),
    DeepSeekModel.V4_PRO: ModelPricing(
        currency="USD",
        input_per_million=0.435,
        cached_input_per_million=0.003625,
        output_per_million=0.87,
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
        snapshot=DEEPSEEK_PRICING_SNAPSHOT,
        authoritative_source="DeepSeek platform pricing",
        max_input_tokens=1_000_000,
        long_context_threshold_tokens=1_000_000,
        long_context_input_multiplier=1.0,
        long_context_output_multiplier=1.0,
        cache_write_multiplier=1.0,
    ),
}


@dataclass(frozen=True)
class PreparedAnalysisContext:
    context: dict[str, Any]
    cloud_context: dict[str, Any]
    evidence_catalog: list[dict[str, str]]
    allowed_refs: list[str]
    context_json: str
    context_bytes: int
    context_hash: str
    instructions: str
    prompt_hash: str
    schema_hash: str
    effective_max_video_analyses: int


def _usage_int(usage: dict[str, Any], key: str) -> int | None:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _usage_cost(model: AnalysisModel, usage: dict[str, Any]) -> dict[str, Any]:
    pricing = MODEL_PRICING[model]
    input_tokens = _usage_int(usage, "input_tokens")
    output_tokens = _usage_int(usage, "output_tokens")
    input_details = usage.get("input_tokens_details")
    details = input_details if isinstance(input_details, dict) else {}
    cached_tokens = _usage_int(details, "cached_tokens")
    cache_write_tokens = _usage_int(details, "cache_write_tokens")
    estimated_total: float | None = None
    billed_breakdown: dict[str, int | None] = {
        "uncached_input_tokens": None,
        "cached_input_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "output_tokens": output_tokens,
    }
    long_context = input_tokens is not None and input_tokens > pricing.long_context_threshold_tokens
    input_multiplier = pricing.long_context_input_multiplier if long_context else 1.0
    output_multiplier = pricing.long_context_output_multiplier if long_context else 1.0
    if input_tokens is not None and output_tokens is not None:
        cached = min(cached_tokens or 0, input_tokens)
        cache_write = min(cache_write_tokens or 0, input_tokens - cached)
        uncached = max(input_tokens - cached - cache_write, 0)
        billed_breakdown["uncached_input_tokens"] = uncached
        input_cost = (
            uncached * pricing.input_per_million
            + cached * pricing.cached_input_per_million
            + cache_write * pricing.input_per_million * pricing.cache_write_multiplier
        )
        output_cost = output_tokens * pricing.output_per_million
        estimated_total = round(
            (input_cost * input_multiplier + output_cost * output_multiplier) / 1_000_000,
            8,
        )
    currency_key = f"estimated_total_{pricing.currency.lower()}"
    return {
        "currency": pricing.currency,
        "estimated_total": estimated_total,
        currency_key: estimated_total,
        "pricing": pricing.as_dict(),
        "usage_basis": billed_breakdown,
        "long_context_pricing_applied": long_context,
        "input_price_multiplier": input_multiplier,
        "output_price_multiplier": output_multiplier,
        "authoritative_source": pricing.authoritative_source,
    }


def _cost_ceiling(model: AnalysisModel, input_token_upper_bound: int) -> dict[str, Any]:
    pricing = MODEL_PRICING[model]
    billable_input_upper_bound = min(input_token_upper_bound, pricing.max_input_tokens)
    long_context = billable_input_upper_bound > pricing.long_context_threshold_tokens
    input_multiplier = pricing.long_context_input_multiplier if long_context else 1.0
    output_multiplier = pricing.long_context_output_multiplier if long_context else 1.0
    maximum = round(
        (
            billable_input_upper_bound * pricing.input_per_million * input_multiplier
            + MAX_OUTPUT_TOKENS * pricing.output_per_million * output_multiplier
        )
        / 1_000_000,
        6,
    )
    currency_key = f"conservative_maximum_{pricing.currency.lower()}"
    return {
        "currency": pricing.currency,
        "conservative_maximum": maximum,
        currency_key: maximum,
        "input_token_upper_bound": billable_input_upper_bound,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "assumption": (
            "UTF-8 request bytes are treated as a conservative token upper bound; "
            "all input is priced as uncached."
        ),
        "pricing": pricing.as_dict(),
        "long_context_pricing_assumed": long_context,
    }


def _safe_usage(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = payload.get(key)
        if isinstance(value, int):
            safe[key] = value
    input_details = payload.get("input_tokens_details")
    if isinstance(input_details, dict):
        safe["input_tokens_details"] = {
            key: value
            for key in ("cached_tokens", "cache_write_tokens")
            if isinstance((value := input_details.get(key)), int)
        }
    output_details = payload.get("output_tokens_details")
    if isinstance(output_details, dict):
        safe["output_tokens_details"] = (
            {"reasoning_tokens": output_details["reasoning_tokens"]}
            if isinstance(output_details.get("reasoning_tokens"), int)
            else {}
        )
    return safe


def _response_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    refusal: str | None = None
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
                    refusal = part["refusal"]
    if refusal is not None:
        raise DistillerError(
            ErrorCode.MODEL_UNAVAILABLE,
            "OpenAI declined to produce this account analysis",
            details={"response_id": payload.get("id"), "refusal": refusal[:240]},
        )
    text = "".join(texts).strip()
    if not text:
        raise DistillerError(
            ErrorCode.MODEL_SCHEMA_INVALID,
            "OpenAI response did not contain structured output text",
            details={"response_id": payload.get("id")},
        )
    return text


class OpenAIResponsesProvider:
    """Minimal SDK-free Responses API client with strict local validation."""

    provider_name = "openai_responses"
    credential_env = OPENAI_API_KEY_ENV

    def __init__(
        self,
        *,
        model: OpenAIModel,
        reasoning_effort: ReasoningEffort,
        executor: HttpExecutor | None = None,
        retry_policy: RetryPolicy | None = None,
        credential_loader: Callable[[], str] | None = None,
        credential_source: str = OPENAI_API_KEY_ENV,
    ) -> None:
        self.model_name = model.value
        self.reasoning_effort = reasoning_effort
        self.credential_source = credential_source
        self.executor = executor or UrllibHttpExecutor()
        self.retry_policy = retry_policy or RetryPolicy(
            max_retries=2,
            base_seconds=1.0,
            timeout_seconds=180,
        )
        self._credential_loader = credential_loader or (
            lambda: read_env_credential(OPENAI_API_KEY_ENV, "OpenAI API")
        )

    @classmethod
    def from_environment(
        cls,
        *,
        model: OpenAIModel,
        reasoning_effort: ReasoningEffort,
        executor: HttpExecutor | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> OpenAIResponsesProvider:
        """Build the production provider from the environment-only credential."""

        read_env_credential(OPENAI_API_KEY_ENV, "OpenAI API")
        return cls(
            model=model,
            reasoning_effort=reasoning_effort,
            executor=executor,
            retry_policy=retry_policy,
        )

    def analyze(self, *, instructions: str, context_json: str) -> ProviderAnalysis:
        schema = GptAccountAnalysis.model_json_schema()
        payload: dict[str, Any] = {
            "model": self.model_name,
            "instructions": instructions,
            "input": context_json,
            "reasoning": {"effort": self.reasoning_effort.value},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "account_analysis",
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "store": False,
        }
        response = request_json(
            self.executor,
            method="POST",
            url=OPENAI_RESPONSES_URL,
            token=self._credential_loader(),
            policy=self.retry_policy,
            payload=payload,
        )
        status = str(response.get("status") or "")
        if status != "completed":
            raise DistillerError(
                ErrorCode.MODEL_UNAVAILABLE,
                "OpenAI response did not complete",
                details={
                    "response_id": response.get("id"),
                    "status": status or "unknown",
                },
            )
        try:
            decoded = json.loads(_response_text(response))
            analysis = GptAccountAnalysis.model_validate(decoded)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise DistillerError(
                ErrorCode.MODEL_SCHEMA_INVALID,
                "OpenAI structured account analysis failed local schema validation",
                details={"response_id": response.get("id")},
            ) from exc
        return ProviderAnalysis(
            response_id=str(response.get("id") or ""),
            model=str(response.get("model") or self.model_name),
            status=status,
            analysis=analysis,
            usage=_safe_usage(response.get("usage")),
        )


def _bailian_chat_completions_url(base_url: str | None = None) -> str:
    configured = (base_url or os.environ.get(BAILIAN_BASE_URL_ENV) or "").strip()
    value = configured or BAILIAN_DEFAULT_BASE_URL
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    allowed_host = hostname in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    } or hostname.endswith(".maas.aliyuncs.com")
    if parsed.scheme != "https" or not allowed_host or parsed.query or parsed.fragment:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Bailian base URL must be an approved Alibaba Cloud HTTPS compatible-mode endpoint",
            details={"environment": BAILIAN_BASE_URL_ENV},
        )
    normalized_path = parsed.path.rstrip("/")
    if not normalized_path.endswith("/compatible-mode/v1"):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Bailian base URL must end with /compatible-mode/v1",
            details={"environment": BAILIAN_BASE_URL_ENV},
        )
    return value.rstrip("/") + "/chat/completions"


def _chat_completion_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise DistillerError(
            ErrorCode.MODEL_SCHEMA_INVALID,
            "Bailian response did not contain a completion choice",
            details={"response_id": payload.get("id")},
        )
    first_choice = choices[0]
    message = first_choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        # Qwen reasoning models (qwen3.7-plus and friends) occasionally place
        # the complete JSON answer in reasoning_content with an empty content,
        # mirroring DeepSeek's thinking mode behaviour.
        content = message.get("reasoning_content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise DistillerError(
            ErrorCode.MODEL_SCHEMA_INVALID,
            "Bailian response did not contain JSON output text",
            details={"response_id": payload.get("id")},
        )
    if first_choice.get("finish_reason") == "length":
        raise DistillerError(
            ErrorCode.MODEL_SCHEMA_INVALID,
            "Bailian response was truncated before the JSON object completed",
            details={
                "response_id": payload.get("id"),
                "finish_reason": "length",
                "hint": (
                    "输出被模型输出上限截断：请降低推理强度，或改用输出上限更大的模型"
                    "（如 qwen3.8-max / qwen-long）。"
                ),
            },
        )
    return content.strip()


def _deepseek_chat_completion_text(payload: dict[str, Any]) -> str:
    """Extract the final JSON text from a DeepSeek chat-completion response.

    DeepSeek's thinking mode (``thinking.type=disabled`` is the only reliable
    non-thinking path) may place the *entire* final answer in
    ``message.reasoning_content`` while leaving ``message.content`` empty,
    especially when ``response_format=json_object`` is combined with
    ``thinking.type=enabled``. Prefer ``content`` and fall back to
    ``reasoning_content`` so the analysis is not rejected as "missing text".
    """
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise DistillerError(
            ErrorCode.MODEL_SCHEMA_INVALID,
            "DeepSeek response did not contain a completion choice",
            details={"response_id": payload.get("id")},
        )
    first_choice = choices[0]
    message = first_choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        content = message.get("reasoning_content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise DistillerError(
            ErrorCode.MODEL_SCHEMA_INVALID,
            "DeepSeek response did not contain JSON output text",
            details={"response_id": payload.get("id")},
        )
    if first_choice.get("finish_reason") == "length":
        raise DistillerError(
            ErrorCode.MODEL_SCHEMA_INVALID,
            "DeepSeek response was truncated before the JSON object completed",
            details={
                "response_id": payload.get("id"),
                "finish_reason": "length",
                "hint": (
                    "输出被模型输出上限截断：请降低推理强度，或改用输出上限更大的模型"
                    "（如 deepseek-v4-flash / qwen3.8-max）。"
                ),
            },
        )
    return content.strip()


def _chat_usage(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    normalized = {
        "input_tokens": payload.get("prompt_tokens"),
        "output_tokens": payload.get("completion_tokens"),
        "total_tokens": payload.get("total_tokens"),
    }
    prompt_details = payload.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        normalized["input_tokens_details"] = {"cached_tokens": prompt_details.get("cached_tokens")}
    completion_details = payload.get("completion_tokens_details")
    if isinstance(completion_details, dict):
        normalized["output_tokens_details"] = {
            "reasoning_tokens": completion_details.get("reasoning_tokens")
        }
    return _safe_usage(normalized)


class BailianChatCompletionsProvider:
    """Alibaba Cloud Model Studio client using its OpenAI-compatible JSON mode."""

    provider_name = "aliyun_bailian_chat_completions"
    credential_env = BAILIAN_API_KEY_ENV

    def __init__(
        self,
        *,
        model: BailianModel,
        reasoning_effort: ReasoningEffort,
        executor: HttpExecutor | None = None,
        retry_policy: RetryPolicy | None = None,
        credential_loader: Callable[[], str] | None = None,
        credential_source: str = BAILIAN_API_KEY_ENV,
        base_url: str | None = None,
    ) -> None:
        self.model_name = model.value
        self.reasoning_effort = reasoning_effort
        self.credential_source = credential_source
        self.executor = executor or UrllibHttpExecutor()
        self.retry_policy = retry_policy or RetryPolicy(
            max_retries=1,
            base_seconds=1.0,
            timeout_seconds=600,
        )
        self.url = _bailian_chat_completions_url(base_url)
        self._credential_loader = credential_loader or (
            lambda: read_env_credential(BAILIAN_API_KEY_ENV, "Alibaba Cloud Model Studio API")
        )

    @classmethod
    def from_environment(
        cls,
        *,
        model: BailianModel,
        reasoning_effort: ReasoningEffort,
        executor: HttpExecutor | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> BailianChatCompletionsProvider:
        read_env_credential(BAILIAN_API_KEY_ENV, "Alibaba Cloud Model Studio API")
        return cls(
            model=model,
            reasoning_effort=reasoning_effort,
            executor=executor,
            retry_policy=retry_policy,
        )

    def analyze(self, *, instructions: str, context_json: str) -> ProviderAnalysis:
        schema_json = json.dumps(
            GptAccountAnalysis.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        output_budget = _MODEL_OUTPUT_BUDGET_TOKENS.get(self.model_name, 16_384)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{instructions}\nReturn only a valid JSON object matching this "
                        "JSON Schema. "
                        f"Do not add Markdown fences.\nJSON Schema:\n{schema_json}"
                    ),
                },
                {"role": "user", "content": context_json},
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": self.reasoning_effort is not ReasoningEffort.NONE,
            "max_tokens": output_budget,
        }
        response = request_json(
            self.executor,
            method="POST",
            url=self.url,
            token=self._credential_loader(),
            policy=self.retry_policy,
            payload=payload,
        )
        analysis, used_response = self._analyze_single(response)
        if analysis is None:
            # Qwen reasoning models occasionally return a syntactically valid
            # but schema-incomplete JSON object with finish_reason=stop (not a
            # length truncation). Retry once with the identical payload; the
            # follow-up completion is typically complete and valid.
            retry_response = request_json(
                self.executor,
                method="POST",
                url=self.url,
                token=self._credential_loader(),
                policy=self.retry_policy,
                payload=payload,
            )
            analysis, used_response = self._analyze_single(retry_response)
            response = retry_response
        else:
            response = used_response
        if analysis is None:
            raise DistillerError(
                ErrorCode.MODEL_SCHEMA_INVALID,
                "Bailian account analysis failed local schema validation",
                details={
                    "response_id": response.get("id"),
                    "retried": True,
                    "hint": (
                        "模型返回的 JSON 缺少必填字段。已自动重试一次仍未通过；"
                        "可降低推理强度或改用其他模型后重试。"
                    ),
                },
            )
        choices = response.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        status = "completed" if isinstance(first_choice, dict) else "unknown"
        return ProviderAnalysis(
            response_id=str(response.get("id") or ""),
            model=str(response.get("model") or self.model_name),
            status=status,
            analysis=analysis,
            usage=_chat_usage(response.get("usage")),
        )

    def _analyze_single(self, response: dict[str, Any]) -> tuple[GptAccountAnalysis | None, dict[str, Any]]:
        """Parse and validate one Bailian completion, returning None on failure."""
        try:
            decoded = json.loads(_chat_completion_text(response))
            return GptAccountAnalysis.model_validate(decoded), response
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            return None, response


def _deepseek_chat_completions_url(base_url: str | None = None) -> str:
    configured = (base_url or os.environ.get(DEEPSEEK_BASE_URL_ENV) or "").strip()
    value = configured or DEEPSEEK_DEFAULT_BASE_URL
    return value.rstrip("/") + "/chat/completions"


class DeepSeekChatCompletionsProvider:
    """DeepSeek OpenAI-compatible chat client with structured JSON output."""

    provider_name = "deepseek_chat_completions"
    credential_env = DEEPSEEK_API_KEY_ENV

    def __init__(
        self,
        *,
        model: DeepSeekModel,
        reasoning_effort: ReasoningEffort,
        executor: HttpExecutor | None = None,
        retry_policy: RetryPolicy | None = None,
        credential_loader: Callable[[], str] | None = None,
        credential_source: str = DEEPSEEK_API_KEY_ENV,
        base_url: str | None = None,
    ) -> None:
        self.model_name = model.value
        self.reasoning_effort = reasoning_effort
        self.credential_source = credential_source
        self.executor = executor or UrllibHttpExecutor()
        self.retry_policy = retry_policy or RetryPolicy(
            max_retries=2,
            base_seconds=1.0,
            timeout_seconds=180,
        )
        self.url = _deepseek_chat_completions_url(base_url)
        self._credential_loader = credential_loader or (
            lambda: read_env_credential(DEEPSEEK_API_KEY_ENV, "DeepSeek API")
        )

    @classmethod
    def from_environment(
        cls,
        *,
        model: DeepSeekModel,
        reasoning_effort: ReasoningEffort,
        executor: HttpExecutor | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> DeepSeekChatCompletionsProvider:
        read_env_credential(DEEPSEEK_API_KEY_ENV, "DeepSeek API")
        return cls(
            model=model,
            reasoning_effort=reasoning_effort,
            executor=executor,
            retry_policy=retry_policy,
        )

    def analyze(self, *, instructions: str, context_json: str) -> ProviderAnalysis:
        schema_json = json.dumps(
            GptAccountAnalysis.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        output_budget = _MODEL_OUTPUT_BUDGET_TOKENS.get(self.model_name, 16_384)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{instructions}\nReturn only a valid JSON object matching this "
                        "JSON Schema. "
                        f"Do not add Markdown fences.\nJSON Schema:\n{schema_json}"
                    ),
                },
                {"role": "user", "content": context_json},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": output_budget,
        }
        if self.reasoning_effort is ReasoningEffort.NONE:
            payload["thinking"] = {"type": "disabled"}
        else:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = (
                "low"
                if self.reasoning_effort is ReasoningEffort.LOW
                else "max"
                if self.reasoning_effort is ReasoningEffort.MAX
                else "high"
            )
        response = request_json(
            self.executor,
            method="POST",
            url=self.url,
            token=self._credential_loader(),
            policy=self.retry_policy,
            payload=payload,
        )
        try:
            decoded = json.loads(_deepseek_chat_completion_text(response))
            analysis = GptAccountAnalysis.model_validate(decoded)
        except DistillerError:
            raise
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            details: dict[str, Any] = {"response_id": response.get("id")}
            if isinstance(exc, ValidationError):
                details["validation_errors"] = [
                    {
                        "loc": ".".join(str(part) for part in error["loc"]),
                        "message": error["msg"],
                    }
                    for error in exc.errors()
                ][:12]
            raise DistillerError(
                ErrorCode.MODEL_SCHEMA_INVALID,
                "DeepSeek account analysis failed local schema validation",
                details=details,
            ) from exc
        choices = response.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        status = "completed" if isinstance(first_choice, dict) else "unknown"
        return ProviderAnalysis(
            response_id=str(response.get("id") or ""),
            model=str(response.get("model") or self.model_name),
            status=status,
            analysis=analysis,
            usage=_chat_usage(response.get("usage")),
        )


def build_account_analysis_provider(
    options: GptAnalysisOptions,
    *,
    executor: HttpExecutor | None = None,
    credential: str | None = None,
    credential_source: str | None = None,
    base_url: str | None = None,
) -> AccountAnalysisProvider:
    """Construct the selected provider with a resolved persistent or environment credential."""

    if options.provider is AnalysisProviderKind.OPENAI:
        if not isinstance(options.model, OpenAIModel):
            raise AssertionError("validated OpenAI options must contain an OpenAI model")
        if credential is not None:
            return OpenAIResponsesProvider(
                model=options.model,
                reasoning_effort=options.reasoning_effort,
                executor=executor,
                credential_loader=lambda: credential,
                credential_source=credential_source or "operating_system_keyring",
            )
        return OpenAIResponsesProvider.from_environment(
            model=options.model,
            reasoning_effort=options.reasoning_effort,
            executor=executor,
        )
    if options.provider is AnalysisProviderKind.DEEPSEEK:
        if not isinstance(options.model, DeepSeekModel):
            raise AssertionError("validated DeepSeek options must contain a DeepSeek model")
        if credential is not None:
            return DeepSeekChatCompletionsProvider(
                model=options.model,
                reasoning_effort=options.reasoning_effort,
                executor=executor,
                credential_loader=lambda: credential,
                credential_source=credential_source or "operating_system_keyring",
                base_url=base_url,
            )
        return DeepSeekChatCompletionsProvider.from_environment(
            model=options.model,
            reasoning_effort=options.reasoning_effort,
            executor=executor,
        )
    if not isinstance(options.model, BailianModel):
        raise AssertionError("validated Bailian options must contain a Bailian model")
    if credential is not None:
        return BailianChatCompletionsProvider(
            model=options.model,
            reasoning_effort=options.reasoning_effort,
            executor=executor,
            credential_loader=lambda: credential,
            credential_source=credential_source or "operating_system_keyring",
            base_url=base_url,
        )
    return BailianChatCompletionsProvider.from_environment(
        model=options.model,
        reasoning_effort=options.reasoning_effort,
        executor=executor,
    )


def probe_account_analysis_provider(
    provider: AnalysisProviderKind,
    *,
    credential: str,
    executor: HttpExecutor | None = None,
) -> dict[str, Any]:
    """Authenticate against the provider and return supported models visible to the key."""

    client = executor or UrllibHttpExecutor()
    policy = RetryPolicy(max_retries=1, base_seconds=0.5, timeout_seconds=30)
    supported: list[str]
    if provider is AnalysisProviderKind.OPENAI:
        url = OPENAI_MODELS_URL
    elif provider is AnalysisProviderKind.DEEPSEEK:
        url = _deepseek_chat_completions_url().removesuffix("/chat/completions") + "/models"
    else:
        url = _bailian_chat_completions_url().removesuffix("/chat/completions") + "/models"
    response = request_json(
        client,
        method="GET",
        url=url,
        token=credential,
        policy=policy,
    )
    data = response.get("data")
    items = data if isinstance(data, list) else []
    visible = {
        str(item["id"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if provider is AnalysisProviderKind.OPENAI:
        supported = [model.value for model in OpenAIModel if model.value in visible]
    elif provider is AnalysisProviderKind.DEEPSEEK:
        supported = [model.value for model in DeepSeekModel if model.value in visible]
    else:
        supported = [model.value for model in BailianModel if model.value in visible]
    if not supported:
        raise DistillerError(
            ErrorCode.MODEL_UNAVAILABLE,
            "The credential is valid but none of the supported analysis models are available",
            details={"provider": provider.value, "visible_model_count": len(visible)},
        )
    return {
        "ok": True,
        "provider": provider.value,
        "authenticated": True,
        "models": supported,
        "credential_persisted": False,
    }


_TEMPLATE_INSTRUCTIONS: dict[AnalysisTemplate, str] = {
    AnalysisTemplate.ACCOUNT_HEALTH: (
        "Diagnose the account's current strengths, weaknesses, evidence gaps, and the most "
        "important next actions."
    ),
    AnalysisTemplate.CONTENT_STRATEGY: (
        "Identify repeatable content patterns, audience needs, positioning opportunities, and "
        "a focused experiment backlog."
    ),
    AnalysisTemplate.GROWTH_PLAN: (
        "Build a practical 30-day growth plan from observed evidence, with measurable tests and "
        "explicit uncertainty."
    ),
}

_CLOUD_REDACTED_KEYS = {
    "platform_account_id",
    "handle",
    "profile_url",
    "raw_hash",
    "source_file",
    "source_row",
}


def _cloud_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _cloud_safe(item)
            for key, item in value.items()
            if str(key) not in _CLOUD_REDACTED_KEYS
        }
    if isinstance(value, list):
        return [_cloud_safe(item) for item in value]
    return value


def _evidence_catalog(context: dict[str, Any]) -> list[dict[str, str]]:
    catalog = [
        {"ref": "context://account", "kind": "context_section", "path": "$.account"},
        {
            "ref": "context://data-availability",
            "kind": "context_section",
            "path": "$.data_availability",
        },
        {"ref": "context://growth", "kind": "context_section", "path": "$.growth"},
        {
            "ref": "context://limitations",
            "kind": "context_section",
            "path": "$.limitations",
        },
    ]
    artifacts = context.get("artifacts")
    if isinstance(artifacts, dict):
        for name, value in artifacts.items():
            if value not in (None, [], {}):
                catalog.append(
                    {
                        "ref": f"context://artifacts/{name}",
                        "kind": "context_section",
                        "path": f"$.artifacts.{name}",
                    }
                )
    source_paths = context.get("source_paths")
    if isinstance(source_paths, list):
        for path in source_paths:
            if isinstance(path, str) and path:
                catalog.append({"ref": path, "kind": "artifact_path", "path": path})
    return catalog


def _used_evidence_refs(analysis: GptAccountAnalysis) -> set[str]:
    refs = {ref for finding in analysis.findings for ref in finding.evidence_refs}
    refs.update(ref for action in analysis.priority_actions for ref in action.evidence_refs)
    refs.update(ref for experiment in analysis.experiments for ref in experiment.evidence_refs)
    refs.update(ref for card in analysis.knowledge_cards for ref in card.evidence_refs)
    refs.update(ref for playbook in analysis.imitation_playbooks for ref in playbook.evidence_refs)
    refs.update(ref for idea in analysis.creative_extensions for ref in idea.evidence_refs)
    return refs


def _prompt(options: GptAnalysisOptions, allowed_refs: list[str]) -> str:
    refs = "\n".join(f"- {ref}" for ref in allowed_refs)
    return (
        "You are an evidence-disciplined analyst for a video-account operations workspace.\n"
        f"Task: {_TEMPLATE_INSTRUCTIONS[options.template]}\n"
        "Write all narrative fields in concise Simplified Chinese.\n"
        "Separate observed facts, statistical associations, hypotheses, and recommendations.\n"
        "Do not produce an inventory of metrics. Synthesize the evidence into a small number "
        "of consequential business judgments. For every major judgment, explain: what changed, "
        "the most plausible mechanism, at least one competing explanation, what evidence could "
        "falsify it, and the decision that follows.\n"
        "Compare high- and low-performing samples where possible. Distinguish a topic effect from "
        "an exposure, hook, structure, duration, or measurement effect. If views, completion, or "
        "growth snapshots are missing, explain exactly which decision cannot yet be made.\n"
        "Recommendations must name a trade-off, a measurable success condition, and a stop or "
        "revision condition. Experiments must change one main variable and avoid vague advice.\n"
        "Produce 2 to 5 imitation_playbooks. Each playbook must extract the underlying mechanism "
        "instead of copying a title, person, hotel, wording, or visual surface. State what is safe "
        "to copy, what must not be copied, and concrete adaptation steps another account can use.\n"
        "Produce 2 to 6 creative_extensions derived from the evidence. Prefer executable content "
        "concepts over abstract brainstorming. Mark trend_relevance as evidence_backed_recent only "
        "when the supplied evidence itself proves recency and trend relevance; use evergreen_extension "
        "for durable ideas, otherwise needs_current_trend_check. Never invent a current hot topic.\n"
        "Create 2 to 6 knowledge_cards that are reusable operating propositions, not report "
        "summaries. Every card must contain a mechanism, competing explanations, falsifier, "
        "scope, boundary conditions, decision, trade-off, success condition, stop condition, "
        "and target metric. A single analysis may produce maturity levels 0 to 3 only; never "
        "claim a level-4 validated rule. Use level 3 only when the card defines a controlled "
        "experiment. Prefer no card over a generic or unfalsifiable card.\n"
        "Every priority action must carry a priority integer from 1 (most important) to 5 only; "
        "never emit 0 or any value above 5. Every confidence field must be exactly one of "
        "low, medium, high. Every maturity_level must be an integer from 0 to 3 only. "
        "Every list length and field length must stay inside the JSON Schema limits above; "
        "do not exceed maxLength or maxItems constraints.\n"
        "Never treat unknown, missing, or fallback semantic labels as a content strategy.\n"
        "Never infer missing values, audience demographics, or causal effects.\n"
        "Every finding, imitation playbook, creative extension, action, experiment, and knowledge "
        "card must cite evidence_refs exactly from the allowlist below. Do not invent paths or "
        "identifiers.\n"
        "Preserve the context limitations in the output and prefer testable next actions.\n"
        f"Evidence allowlist:\n{refs}\n"
        f"Prompt version: {GPT_PROMPT_VERSION}"
    )


def _render_markdown(
    payload: dict[str, Any],
    *,
    include_evidence_appendix: bool = True,
) -> str:
    confidence_zh = {
        "high": "高",
        "medium": "中",
        "low": "低",
    }
    trend_zh = {
        "evidence_backed_recent": "有近期证据支持",
        "evergreen_extension": "常青创意",
        "needs_current_trend_check": "执行前需核验当前热点",
    }

    def _evidence_label(ref: str) -> str:
        lowered = ref.casefold()
        if lowered.startswith("context://account"):
            return "账号快照"
        if lowered.startswith("context://data-availability"):
            return "数据可用性"
        if lowered.startswith("context://growth"):
            return "增长轨迹"
        if lowered.startswith("context://limitations"):
            return "数据局限"
        if lowered.startswith("context://analysis_contract"):
            return "分析规范"
        if lowered.startswith("context://artifacts/"):
            return f"分析产物（{ref.rsplit('/', 1)[-1]}）"
        if lowered.endswith("report.json"):
            return "账号体检报告"
        if lowered.endswith("distillation.json"):
            return "账号蒸馏"
        if lowered.endswith("enrichment.json"):
            return "媒体增强"
        if lowered.endswith("profile.json"):
            return "对标画像"
        if lowered.endswith("analysis.json"):
            return "视频分析"
        if lowered.endswith("sample-manifest.json"):
            return "抽样清单"
        return ref

    result = GptAccountAnalysis.model_validate(payload["result"])
    lines = [
        "# 账号运营学习报告",
        "",
        "> 先读方法和行动；统计明细、反证与证据路径集中放在文末附录。",
        "",
        "## 一页结论",
        "",
        result.executive_summary,
        "",
        "## 可模仿打法",
        "",
    ]
    if result.imitation_playbooks:
        for index, playbook in enumerate(result.imitation_playbooks, start=1):
            lines.extend(
                [
                    f"### {index}. {playbook.title}",
                    "",
                    f"**学到的东西：** {playbook.learned_insight}",
                    "",
                    f"**为什么可能有效：** {playbook.why_it_works}",
                    "",
                    "**可以模仿：** " + "；".join(playbook.copy_this),
                    "",
                    "**不要照搬：** " + "；".join(playbook.do_not_copy),
                    "",
                    "**落地步骤：**",
                    *[f"{step_no}. {step}" for step_no, step in enumerate(playbook.adaptation_steps, 1)],
                    "",
                    f"**适合：** {'；'.join(playbook.suitable_for)}",
                    f"**置信度：** {confidence_zh[str(playbook.confidence)]}",
                    "",
                ]
            )
    else:
        lines.extend(["- 当前证据尚不足以形成可迁移打法；建议先补齐视频语义后重新综合。", ""])

    lines.extend(["## 灵感与延伸创意", ""])
    if result.creative_extensions:
        for index, idea in enumerate(result.creative_extensions, start=1):
            lines.extend(
                [
                    f"### {index}. {idea.title}",
                    "",
                    f"- 来源：{idea.derived_from}",
                    f"- 创意：{idea.concept}",
                    f"- 热点属性：{trend_zh[str(idea.trend_relevance)]}",
                    *(
                        [f"- 热点依据：{idea.trend_basis}"]
                        if idea.trend_basis
                        else []
                    ),
                    "- 执行：",
                    *[f"  {step_no}. {step}" for step_no, step in enumerate(idea.execution, 1)],
                    f"- 风险/边界：{idea.risk_or_boundary}",
                    "",
                ]
            )
    else:
        lines.extend(["- 本次没有形成足够具体的延伸创意。", ""])

    lines.extend(["## 现在就做", ""])
    for action in sorted(result.priority_actions, key=lambda item: item.priority):
        lines.extend(
            [
                f"{action.priority}. {action.action}",
                f"   - 为什么：{action.rationale}",
            ]
        )
    lines.extend(["", "## 如何验证这些想法", ""])
    if result.experiments:
        for experiment in result.experiments:
            lines.extend(
                [
                    f"- 假设：{experiment.hypothesis}",
                    f"  - 动作：{experiment.action}",
                    f"  - 主指标：{experiment.primary_metric}",
                    f"  - 观察窗口：{experiment.observation_window}",
                ]
            )
    else:
        lines.append("- 本次未生成实验建议。")

    lines.extend(["", "## 阅读边界", ""])
    lines.extend(f"- {item}" for item in result.limitations)

    if include_evidence_appendix:
        lines.extend(["", "<details>", "<summary>证据与严谨分析附录</summary>", ""])
        lines.extend(["### 主要判断", ""])
        for finding in result.findings:
            lines.extend(
                [
                    f"- **{finding.title}**：{finding.statement}",
                    f"  - 类型：{finding.classification}；置信度：{confidence_zh[str(finding.confidence)]}",
                    f"  - 证据：{'、'.join(_evidence_label(ref) for ref in finding.evidence_refs)}",
                ]
            )
        lines.extend(["", "### 可复用经营知识卡", ""])
        for card in result.knowledge_cards:
            lines.extend(
                [
                    f"- **{card.title}**：{card.claim}",
                    f"  - 机制：{card.mechanism}",
                    f"  - 竞争解释：{'；'.join(card.competing_explanations)}",
                    f"  - 反证：{card.falsifier}",
                    f"  - 成功/停止：{card.success_condition} / {card.stop_condition}",
                    f"  - 证据：{'、'.join(_evidence_label(ref) for ref in card.evidence_refs)}",
                ]
            )
        lines.extend(["", "</details>"])
    return "\n".join(lines).rstrip() + "\n"


def render_account_learning_report(
    payload: dict[str, Any],
    *,
    include_evidence_appendix: bool = False,
) -> str:
    """Render the concise, human-first view of a persisted account synthesis."""

    return _render_markdown(payload, include_evidence_appendix=include_evidence_appendix)


def _prepare_analysis_context(
    project: ProjectLayout,
    *,
    account_id: str,
    options: GptAnalysisOptions,
) -> PreparedAnalysisContext:
    model_budget = _MODEL_INPUT_BUDGET_BYTES.get(
        options.model.value,
        MAX_CLOUD_CONTEXT_BYTES,
    )
    requested_video_analyses = options.max_video_analyses
    effective_video_analyses = requested_video_analyses
    context = AnalysisContextService(project).build(
        account_id=account_id,
        max_video_analyses=effective_video_analyses,
    )
    if context.get("account") is None:
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            f"No normalized account found for GPT analysis: {account_id}",
        )
    # Trim per-video evidence until the serialized context fits the selected
    # model's input budget. Small-context models (e.g. MaaS qwen-max at 30K
    # tokens) would otherwise be rejected with HTTP 400 "input length".
    while effective_video_analyses > 1:
        cloud_context = _cloud_safe(context)
        if not isinstance(cloud_context, dict):
            raise AssertionError("analysis context must remain an object")
        catalog = _evidence_catalog(cloud_context)
        cloud_context["evidence_catalog"] = catalog
        context_json = json.dumps(
            cloud_context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        context_bytes = len(context_json.encode("utf-8"))
        if context_bytes <= model_budget:
            break
        effective_video_analyses = max(1, effective_video_analyses // 2)
        context = AnalysisContextService(project).build(
            account_id=account_id,
            max_video_analyses=effective_video_analyses,
        )
    cloud_context = _cloud_safe(context)
    if not isinstance(cloud_context, dict):
        raise AssertionError("analysis context must remain an object")
    catalog = _evidence_catalog(cloud_context)
    allowed_refs = [item["ref"] for item in catalog]
    cloud_context["evidence_catalog"] = catalog
    context_json = json.dumps(
        cloud_context,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    context_bytes = len(context_json.encode("utf-8"))
    if context_bytes > MAX_CLOUD_CONTEXT_BYTES:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Bounded GPT analysis context exceeds the upload limit",
            details={
                "context_bytes": context_bytes,
                "max_context_bytes": MAX_CLOUD_CONTEXT_BYTES,
                "hint": "reduce max_video_analyses",
            },
        )
    if effective_video_analyses < requested_video_analyses:
        limitations = list(context.get("limitations") or [])
        limitations.append(
            f"模型输入上限限制：逐视频证据已从 {requested_video_analyses} 缩减到 "
            f"{effective_video_analyses} 条（上下文约 {context_bytes // 1024} KB）。"
        )
        context["limitations"] = limitations
        cloud_context["limitations"] = limitations
    if context_bytes > model_budget:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "账号分析上下文超出所选模型的输入上限",
            details={
                "model": options.model.value,
                "context_bytes": context_bytes,
                "model_input_budget_bytes": model_budget,
                "next": (
                    "请选择上下文更大的模型，例如百炼 qwen3.8-max / qwen-long，"
                    "或在知识分析页减少“纳入逐视频详细证据数”。"
                ),
            },
        )

    stable_context = dict(cloud_context)
    stable_context.pop("generated_at", None)
    context_hash = sha256_json(stable_context)
    instructions = _prompt(options, allowed_refs)
    prompt_hash = sha256_json({"instructions": instructions})
    schema_hash = sha256_json(GptAccountAnalysis.model_json_schema())
    return PreparedAnalysisContext(
        context=context,
        cloud_context=cloud_context,
        evidence_catalog=catalog,
        allowed_refs=allowed_refs,
        context_json=context_json,
        context_bytes=context_bytes,
        context_hash=context_hash,
        instructions=instructions,
        prompt_hash=prompt_hash,
        schema_hash=schema_hash,
        effective_max_video_analyses=effective_video_analyses,
    )


def _numeric_tokens(value: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?%?", value))


def _finding_fingerprints(analysis: GptAccountAnalysis) -> set[str]:
    return {
        sha256_json(
            {
                "classification": finding.classification,
                "title": " ".join(finding.title.casefold().split()),
                "statement": " ".join(finding.statement.casefold().split()),
            }
        )
        for finding in analysis.findings
    }


def _load_stability_comparisons(
    account_root: Path,
    *,
    comparison_key: str,
    current_analysis: GptAccountAnalysis,
) -> list[dict[str, Any]]:
    current = _finding_fingerprints(current_analysis)
    comparisons: list[dict[str, Any]] = []
    if not account_root.is_dir():
        return comparisons
    for audit_path in sorted(account_root.glob("*/audit.json")):
        analysis_path = audit_path.with_name("analysis.json")
        try:
            audit = read_json(audit_path)
            payload = read_json(analysis_path)
            if audit.get("comparison_key") != comparison_key or not isinstance(
                payload.get("result"), dict
            ):
                continue
            previous = GptAccountAnalysis.model_validate(payload["result"])
        except (OSError, ValueError, ValidationError):
            continue
        prior = _finding_fingerprints(previous)
        union = current | prior
        similarity = len(current & prior) / len(union) if union else 1.0
        comparisons.append(
            {
                "analysis_id": payload.get("analysis_id"),
                "finding_jaccard_similarity": round(similarity, 6),
            }
        )
    return comparisons


def _evaluate_analysis(
    *,
    prepared: PreparedAnalysisContext,
    analysis: GptAccountAnalysis,
    account_root: Path,
    comparison_key: str,
) -> dict[str, Any]:
    citation_groups = [
        *(item.evidence_refs for item in analysis.findings),
        *(item.evidence_refs for item in analysis.priority_actions),
        *(item.evidence_refs for item in analysis.experiments),
        *(item.evidence_refs for item in analysis.knowledge_cards),
    ]
    cited_items = sum(bool(refs) for refs in citation_groups)
    completeness = cited_items / len(citation_groups) if citation_groups else None
    used_refs = _used_evidence_refs(analysis)
    invalid_refs = sorted(used_refs.difference(prepared.allowed_refs))

    context_numbers = _numeric_tokens(prepared.context_json)
    unsupported_numeric_claims: list[dict[str, Any]] = []
    for index, finding in enumerate(analysis.findings):
        if finding.classification not in {"observed_fact", "statistical_association"}:
            continue
        claim_numbers = _numeric_tokens(f"{finding.title} {finding.statement}")
        unsupported = sorted(claim_numbers.difference(context_numbers))
        if unsupported:
            unsupported_numeric_claims.append(
                {
                    "finding_index": index,
                    "title": finding.title,
                    "tokens": unsupported,
                }
            )

    comparisons = _load_stability_comparisons(
        account_root,
        comparison_key=comparison_key,
        current_analysis=analysis,
    )
    if comparisons:
        minimum_similarity = min(item["finding_jaccard_similarity"] for item in comparisons)
        stability_status = "pass" if minimum_similarity >= 0.6 else "review_required"
    else:
        minimum_similarity = None
        stability_status = "insufficient_runs"

    knowledge_cards_present = bool(analysis.knowledge_cards)
    knowledge_cards_are_safe = all(card.maturity_level <= 3 for card in analysis.knowledge_cards)
    knowledge_card_titles = {
        " ".join(card.title.casefold().split()) for card in analysis.knowledge_cards
    }
    knowledge_cards_are_distinct = len(knowledge_card_titles) == len(analysis.knowledge_cards)

    checks: list[dict[str, Any]] = [
        {
            "id": "citation_completeness",
            "question": "Does every finding, action, experiment, and knowledge card include evidence?",
            "status": "pass" if completeness == 1.0 else "fail",
            "value": completeness,
            "unknown": completeness is None,
        },
        {
            "id": "evidence_allowlist_integrity",
            "question": "Do all citations resolve to the submitted evidence allowlist?",
            "status": "pass" if not invalid_refs else "fail",
            "invalid_refs": invalid_refs,
        },
        {
            "id": "hallucination_numeric_claim_review",
            "question": (
                "Do observed/statistical conclusions avoid numeric claims absent from context?"
            ),
            "status": "pass" if not unsupported_numeric_claims else "review_required",
            "unsupported_numeric_claims": unsupported_numeric_claims,
            "scope_note": "Semantic hallucination still requires human or benchmark review.",
        },
        {
            "id": "conclusion_stability",
            "question": "Are finding conclusions stable across comparable independent runs?",
            "status": stability_status,
            "comparable_runs": comparisons,
            "minimum_finding_jaccard_similarity": minimum_similarity,
            "required_runs": 2,
        },
        {
            "id": "knowledge_asset_completeness",
            "question": "Did the synthesis create distinct, falsifiable operating knowledge cards?",
            "status": (
                "pass"
                if knowledge_cards_present and knowledge_cards_are_distinct
                else "review_required"
            ),
            "knowledge_card_count": len(analysis.knowledge_cards),
            "distinct_titles": knowledge_cards_are_distinct,
            "required_fields_enforced_by_schema": [
                "mechanism",
                "competing_explanations",
                "falsifier",
                "decision",
                "scope",
                "boundary_conditions",
                "tradeoff",
                "success_condition",
                "stop_condition",
                "target_metric",
            ],
        },
        {
            "id": "knowledge_promotion_safety",
            "question": "Does one model run avoid promoting a claim to a validated rule?",
            "status": "pass" if knowledge_cards_are_safe else "fail",
            "maximum_allowed_maturity": 3,
        },
        {
            "id": "derived_analysis_boundary",
            "question": "Are model-derived cards isolated from validated Rule and Rubric records?",
            "status": "pass",
            "write_scope": "analyses/gpt + knowledge-base/claims (candidate only)",
        },
    ]
    return {
        "evaluation_version": GPT_EVALUATION_VERSION,
        "comparison_key": comparison_key,
        "checks": checks,
        "finding_fingerprints": sorted(_finding_fingerprints(analysis)),
        "manual_review_required": any(
            item["status"] in {"review_required", "insufficient_runs"} for item in checks
        ),
    }


def _persist_candidate_knowledge_cards(
    project: ProjectLayout,
    *,
    account_id: str,
    analysis_id: str,
    generated_at: str,
    analysis: GptAccountAnalysis,
) -> list[str]:
    """Persist model-derived propositions without promoting them to validated rules."""

    claim_dir = project.root / "knowledge-base" / "claims"
    relative_paths: list[str] = []
    claim_index: dict[str, str] = {}
    for card in analysis.knowledge_cards:
        card_payload = card.model_dump(mode="json")
        claim_id = stable_id("claim_", account_id, analysis_id, card_payload)
        claim_path = claim_dir / f"{claim_id}.json"
        payload = {
            "schema_version": "1.0.0",
            "claim_id": claim_id,
            "account_id": account_id,
            "source_analysis_id": analysis_id,
            "generated_at": generated_at,
            "status": "experimental" if card.maturity_level >= 3 else "candidate",
            "validated": False,
            "requires_human_review": True,
            "knowledge": card_payload,
        }
        atomic_write_json(claim_path, payload)
        relative = project.relative(claim_path)
        relative_paths.append(relative)
        claim_index[claim_id] = relative

    if claim_index:
        index_path = project.root / "knowledge-base" / "index.json"
        try:
            index = read_json(index_path) if index_path.is_file() else {}
        except (OSError, ValueError, TypeError):
            index = {}
        if not isinstance(index, dict):
            index = {}
        claims = index.setdefault("claims", {})
        if not isinstance(claims, dict):
            claims = {}
            index["claims"] = claims
        claims.update(claim_index)
        atomic_write_json(index_path, index)
    return relative_paths


class RemoteAccountAnalysisService:
    """Create one idempotent, schema-validated, evidence-linked analysis artifact."""

    def __init__(self, project: ProjectLayout, provider: AccountAnalysisProvider) -> None:
        self.project = project
        self.provider = provider

    @staticmethod
    def require_authorization(
        project: ProjectLayout,
        options: GptAnalysisOptions,
    ) -> None:
        config = load_config(project.config_path)
        if not config.privacy.allow_cloud_model_upload:
            raise DistillerError(
                ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED,
                "Cloud model upload is disabled for this project",
                details={
                    "required": "privacy.allow_cloud_model_upload=true",
                    "data_sent": "bounded redacted analysis context",
                },
            )
        missing = []
        if not options.confirm_cloud_upload:
            missing.append("confirm_cloud_upload=true")
        if not options.confirm_cost:
            missing.append("confirm_cost=true")
        if missing:
            raise DistillerError(
                ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED,
                "Cloud analysis requires explicit data-upload and cost confirmation",
                details={"required": missing},
            )

    @staticmethod
    def preview(
        project: ProjectLayout,
        *,
        account_id: str,
        options: GptAnalysisOptions,
    ) -> dict[str, Any]:
        """Describe the exact bounded request and conservative price before authorization."""

        prepared = _prepare_analysis_context(
            project,
            account_id=account_id,
            options=options,
        )
        request_bytes = len(f"{prepared.instructions}\n{prepared.context_json}".encode())
        artifacts = prepared.cloud_context.get("artifacts")
        included_artifacts = (
            sorted(str(name) for name, value in artifacts.items() if value not in (None, [], {}))
            if isinstance(artifacts, dict)
            else []
        )
        return {
            "ok": True,
            "remote_call_performed": False,
            "provider": options.provider.value,
            "model": options.model.value,
            "template": options.template.value,
            "reasoning_effort": options.reasoning_effort.value,
            "data_scope": {
                "context_bytes": prepared.context_bytes,
                "request_bytes": request_bytes,
                "max_video_analyses": options.max_video_analyses,
                "effective_max_video_analyses": prepared.effective_max_video_analyses,
                "included_artifacts": included_artifacts,
                "evidence_refs_available": len(prepared.allowed_refs),
                "redacted_keys": sorted(_CLOUD_REDACTED_KEYS),
                "raw_comments_included": False,
                "raw_provider_pages_included": False,
                "credentials_included": False,
            },
            "request_fingerprints": {
                "context_hash": prepared.context_hash,
                "prompt_hash": prepared.prompt_hash,
                "schema_hash": prepared.schema_hash,
            },
            "cost_preview": _cost_ceiling(options.model, request_bytes),
            "confirmations_required": [
                "confirm_cloud_upload=true",
                "confirm_cost=true",
            ],
        }

    def analyze(
        self,
        *,
        account_id: str,
        options: GptAnalysisOptions,
        evaluation_run_key: str | None = None,
    ) -> dict[str, Any]:
        self.require_authorization(self.project, options)
        if evaluation_run_key is not None and not _EVALUATION_RUN_KEY_PATTERN.fullmatch(
            evaluation_run_key
        ):
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "GPT evaluation run key must be 1-192 safe identifier characters",
                details={"field": "evaluation_run_key"},
            )
        prepared = _prepare_analysis_context(
            self.project,
            account_id=account_id,
            options=options,
        )
        comparison_key = sha256_json(
            {
                "context_hash": prepared.context_hash,
                "prompt_hash": prepared.prompt_hash,
                "provider": options.provider.value,
                "model": options.model.value,
                "template": options.template.value,
                "reasoning_effort": options.reasoning_effort.value,
            }
        )
        analysis_id_parts = [
            account_id,
            GPT_ANALYSIS_VERSION,
            options.provider.value,
            options.model.value,
            options.template.value,
            options.reasoning_effort.value,
            prepared.context_hash,
            prepared.prompt_hash,
        ]
        if evaluation_run_key is not None:
            analysis_id_parts.append(evaluation_run_key)
        analysis_id = stable_id("gpta_", *analysis_id_parts)
        output_dir = self.project.root / "analyses" / "gpt" / account_id / analysis_id
        analysis_path = output_dir / "analysis.json"
        audit_path = output_dir / "audit.json"
        evaluation_path = output_dir / "evaluation.json"
        report_path = output_dir / "report.md"
        paths = [analysis_path, audit_path, evaluation_path, report_path]
        relative_paths = [self.project.relative(path) for path in paths]
        if all(path.is_file() for path in paths):
            cached = read_json(analysis_path)
            cached_claim_paths = (
                cached.get("knowledge_claim_paths", []) if isinstance(cached, dict) else []
            )
            return {
                "ok": True,
                "already_generated": True,
                "analysis": cached,
                "audit": read_json(audit_path),
                "evaluation": read_json(evaluation_path),
                "outputs": [*relative_paths, *cached_claim_paths],
            }

        manifest = self.project.begin_run(
            "analyze account gpt",
            input_hashes=[prepared.context_hash, prepared.prompt_hash],
        )
        try:
            provider_result = self.provider.analyze(
                instructions=prepared.instructions,
                context_json=prepared.context_json,
            )
            used_refs = _used_evidence_refs(provider_result.analysis)
            invalid_refs = sorted(used_refs.difference(prepared.allowed_refs))
            if invalid_refs:
                raise DistillerError(
                    ErrorCode.MODEL_SCHEMA_INVALID,
                    "GPT analysis cited evidence outside the submitted allowlist",
                    details={"invalid_evidence_refs": invalid_refs[:20]},
                )
            generated_at = datetime.now(UTC).isoformat()
            output_hash = sha256_json(provider_result.analysis.model_dump(mode="json"))
            evaluation_payload = _evaluate_analysis(
                prepared=prepared,
                analysis=provider_result.analysis,
                account_root=output_dir.parent,
                comparison_key=comparison_key,
            )
            analysis_payload = {
                "analysis_id": analysis_id,
                "analysis_version": GPT_ANALYSIS_VERSION,
                "account_id": account_id,
                "generated_at": generated_at,
                "run_id": manifest.run_id,
                "provider": self.provider.provider_name,
                "requested_model": options.model.value,
                "returned_model": provider_result.model,
                "template": options.template.value,
                "reasoning_effort": options.reasoning_effort.value,
                "result": provider_result.analysis.model_dump(mode="json"),
                "output_hash": output_hash,
                "evidence_refs_used": sorted(used_refs),
                "source_paths": prepared.context.get("source_paths", []),
                "limitations": prepared.context.get("limitations", []),
                "derived_analysis_only": True,
                "evaluation_run_key": evaluation_run_key,
            }
            knowledge_claim_paths = _persist_candidate_knowledge_cards(
                self.project,
                account_id=account_id,
                analysis_id=analysis_id,
                generated_at=generated_at,
                analysis=provider_result.analysis,
            )
            analysis_payload["knowledge_claim_paths"] = knowledge_claim_paths
            relative_paths.extend(knowledge_claim_paths)
            audit_payload = {
                "analysis_id": analysis_id,
                "audit_version": GPT_ANALYSIS_VERSION,
                "generated_at": generated_at,
                "run_id": manifest.run_id,
                "comparison_key": comparison_key,
                "request": {
                    "provider": self.provider.provider_name,
                    "model": options.model.value,
                    "template": options.template.value,
                    "reasoning_effort": options.reasoning_effort.value,
                    "prompt_version": GPT_PROMPT_VERSION,
                    "prompt_hash": prepared.prompt_hash,
                    "context_hash": prepared.context_hash,
                    "schema_hash": prepared.schema_hash,
                    "context_bytes": prepared.context_bytes,
                    "max_video_analyses": options.max_video_analyses,
                    "store": False,
                    "cloud_upload_confirmed": True,
                    "cost_confirmed": True,
                    "evaluation_run_key": evaluation_run_key,
                },
                "response": {
                    "response_id": provider_result.response_id,
                    "model": provider_result.model,
                    "status": provider_result.status,
                    "usage": provider_result.usage,
                    "output_hash": output_hash,
                    "estimated_cost": _usage_cost(options.model, provider_result.usage),
                },
                "privacy": {
                    "redacted_keys": sorted(_CLOUD_REDACTED_KEYS),
                    "api_key_persisted": False,
                    "api_key_source": getattr(
                        self.provider,
                        "credential_source",
                        (
                            OPENAI_API_KEY_ENV
                            if options.provider is AnalysisProviderKind.OPENAI
                            else DEEPSEEK_API_KEY_ENV
                            if options.provider is AnalysisProviderKind.DEEPSEEK
                            else BAILIAN_API_KEY_ENV
                        ),
                    ),
                    "raw_response_persisted": False,
                },
                "write_boundary": "derived_analysis_and_candidate_claims_only",
                "evidence_catalog": prepared.evidence_catalog,
                "evidence_refs_used": sorted(used_refs),
                "evaluation": {
                    "version": GPT_EVALUATION_VERSION,
                    "path": self.project.relative(evaluation_path),
                },
            }
            output_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(analysis_path, analysis_payload)
            atomic_write_json(audit_path, audit_payload)
            atomic_write_json(evaluation_path, evaluation_payload)
            atomic_write_text(report_path, _render_markdown(analysis_payload))
        except Exception as exc:
            error = (
                f"{exc.code.value}: {exc.message}"
                if isinstance(exc, DistillerError)
                else f"{type(exc).__name__}: {exc}"
            )
            self.project.finish_run(
                manifest,
                success=False,
                errors=[error[:1_000]],
            )
            raise

        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={
                "findings": len(provider_result.analysis.findings),
                "actions": len(provider_result.analysis.priority_actions),
                "experiments": len(provider_result.analysis.experiments),
            },
            output_files=relative_paths,
        )
        return {
            "ok": True,
            "already_generated": False,
            "analysis": analysis_payload,
            "audit": audit_payload,
            "evaluation": evaluation_payload,
            "outputs": relative_paths,
        }
