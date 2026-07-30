"""Audited, privacy-gated account analysis through the OpenAI Responses API."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
GPT_ANALYSIS_VERSION = "1.1.0"
GPT_PROMPT_VERSION = "account-gpt-analysis-v1"
GPT_EVALUATION_VERSION = "account-analysis-eval-v1"
GPT_PRICING_SNAPSHOT = "openai-api-pricing-2026-07-28"
MAX_CLOUD_CONTEXT_BYTES = 1_500_000
MAX_OUTPUT_TOKENS = 5_000
MODEL_MAX_INPUT_TOKENS = 922_000
LONG_CONTEXT_THRESHOLD_TOKENS = 272_000
_EVALUATION_RUN_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenAIModel(StrEnum):
    SOL = "gpt-5.6-sol"
    TERRA = "gpt-5.6-terra"
    LUNA = "gpt-5.6-luna"


class AnalysisTemplate(StrEnum):
    ACCOUNT_HEALTH = "account_health"
    CONTENT_STRATEGY = "content_strategy"
    GROWTH_PLAN = "growth_plan"


class ReasoningEffort(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GptAnalysisOptions(StrictModel):
    """Secret-free options that may safely enter task memory and audit metadata."""

    model: OpenAIModel = OpenAIModel.TERRA
    template: AnalysisTemplate = AnalysisTemplate.ACCOUNT_HEALTH
    reasoning_effort: ReasoningEffort = ReasoningEffort.LOW
    max_video_analyses: int = Field(default=10, ge=1, le=25)
    confirm_cloud_upload: bool = False
    confirm_cost: bool = False


class GptAnalysisRequest(GptAnalysisOptions):
    """Secret-free API request; credentials are read only from the server environment."""

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


class GptAccountAnalysis(StrictModel):
    executive_summary: str = Field(min_length=1, max_length=3_000)
    findings: list[GptFinding] = Field(min_length=1, max_length=12)
    priority_actions: list[GptPriorityAction] = Field(min_length=1, max_length=8)
    experiments: list[GptExperiment] = Field(max_length=6)
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

    def analyze(self, *, instructions: str, context_json: str) -> ProviderAnalysis: ...


@dataclass(frozen=True)
class ModelPricing:
    input_usd_per_million: float
    cached_input_usd_per_million: float
    output_usd_per_million: float
    source_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": "USD",
            "unit": "per_1m_tokens",
            "input": self.input_usd_per_million,
            "cached_input": self.cached_input_usd_per_million,
            "output": self.output_usd_per_million,
            "cache_write_multiplier": 1.25,
            "long_context_threshold_tokens": LONG_CONTEXT_THRESHOLD_TOKENS,
            "long_context_input_multiplier": 2.0,
            "long_context_output_multiplier": 1.5,
            "snapshot": GPT_PRICING_SNAPSHOT,
            "source_url": self.source_url,
        }


MODEL_PRICING: dict[OpenAIModel, ModelPricing] = {
    OpenAIModel.SOL: ModelPricing(
        input_usd_per_million=5.0,
        cached_input_usd_per_million=0.5,
        output_usd_per_million=30.0,
        source_url="https://developers.openai.com/api/docs/models/gpt-5.6-sol",
    ),
    OpenAIModel.TERRA: ModelPricing(
        input_usd_per_million=2.5,
        cached_input_usd_per_million=0.25,
        output_usd_per_million=15.0,
        source_url="https://developers.openai.com/api/docs/models/gpt-5.6-terra",
    ),
    OpenAIModel.LUNA: ModelPricing(
        input_usd_per_million=1.0,
        cached_input_usd_per_million=0.1,
        output_usd_per_million=6.0,
        source_url="https://developers.openai.com/api/docs/models/gpt-5.6-luna",
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


def _usage_int(usage: dict[str, Any], key: str) -> int | None:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _usage_cost(model: OpenAIModel, usage: dict[str, Any]) -> dict[str, Any]:
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
    long_context = input_tokens is not None and input_tokens > LONG_CONTEXT_THRESHOLD_TOKENS
    input_multiplier = 2.0 if long_context else 1.0
    output_multiplier = 1.5 if long_context else 1.0
    if input_tokens is not None and output_tokens is not None:
        cached = min(cached_tokens or 0, input_tokens)
        cache_write = min(cache_write_tokens or 0, input_tokens - cached)
        uncached = max(input_tokens - cached - cache_write, 0)
        billed_breakdown["uncached_input_tokens"] = uncached
        input_cost = (
            uncached * pricing.input_usd_per_million
            + cached * pricing.cached_input_usd_per_million
            + cache_write * pricing.input_usd_per_million * 1.25
        )
        output_cost = output_tokens * pricing.output_usd_per_million
        estimated_total = round(
            (input_cost * input_multiplier + output_cost * output_multiplier) / 1_000_000,
            8,
        )
    return {
        "estimated_total_usd": estimated_total,
        "pricing": pricing.as_dict(),
        "usage_basis": billed_breakdown,
        "long_context_pricing_applied": long_context,
        "input_price_multiplier": input_multiplier,
        "output_price_multiplier": output_multiplier,
        "authoritative_source": "OpenAI billing dashboard/invoice",
    }


def _cost_ceiling(model: OpenAIModel, input_token_upper_bound: int) -> dict[str, Any]:
    pricing = MODEL_PRICING[model]
    billable_input_upper_bound = min(input_token_upper_bound, MODEL_MAX_INPUT_TOKENS)
    long_context = billable_input_upper_bound > LONG_CONTEXT_THRESHOLD_TOKENS
    input_multiplier = 2.0 if long_context else 1.0
    output_multiplier = 1.5 if long_context else 1.0
    maximum_usd = round(
        (
            billable_input_upper_bound * pricing.input_usd_per_million * input_multiplier
            + MAX_OUTPUT_TOKENS * pricing.output_usd_per_million * output_multiplier
        )
        / 1_000_000,
        6,
    )
    return {
        "currency": "USD",
        "conservative_maximum_usd": maximum_usd,
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

    def __init__(
        self,
        *,
        model: OpenAIModel,
        reasoning_effort: ReasoningEffort,
        executor: HttpExecutor | None = None,
        retry_policy: RetryPolicy | None = None,
        credential_loader: Callable[[], str] | None = None,
    ) -> None:
        self.model_name = model.value
        self.reasoning_effort = reasoning_effort
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
    return refs


def _prompt(options: GptAnalysisOptions, allowed_refs: list[str]) -> str:
    refs = "\n".join(f"- {ref}" for ref in allowed_refs)
    return (
        "You are an evidence-disciplined analyst for a video-account operations workspace.\n"
        f"Task: {_TEMPLATE_INSTRUCTIONS[options.template]}\n"
        "Write all narrative fields in concise Simplified Chinese.\n"
        "Separate observed facts, statistical associations, hypotheses, and recommendations.\n"
        "Never infer missing values, audience demographics, or causal effects.\n"
        "Every finding, action, and experiment must cite one or more evidence_refs exactly from "
        "the allowlist below. Do not invent paths or identifiers.\n"
        "Preserve the context limitations in the output and prefer testable next actions.\n"
        f"Evidence allowlist:\n{refs}\n"
        f"Prompt version: {GPT_PROMPT_VERSION}"
    )


def _render_markdown(payload: dict[str, Any]) -> str:
    result = GptAccountAnalysis.model_validate(payload["result"])
    lines = [
        "# GPT 账号分析",
        "",
        result.executive_summary,
        "",
        "## 主要发现",
        "",
    ]
    for finding in result.findings:
        lines.extend(
            [
                f"### {finding.title}",
                "",
                finding.statement,
                "",
                f"- 类型：{finding.classification}",
                f"- 置信度：{finding.confidence}",
                f"- 证据：{', '.join(finding.evidence_refs)}",
                "",
            ]
        )
    lines.extend(["## 优先行动", ""])
    for action in sorted(result.priority_actions, key=lambda item: item.priority):
        lines.extend(
            [
                f"{action.priority}. {action.action}",
                f"   - 理由：{action.rationale}",
                f"   - 证据：{', '.join(action.evidence_refs)}",
            ]
        )
    lines.extend(["", "## 实验建议", ""])
    if result.experiments:
        for experiment in result.experiments:
            lines.extend(
                [
                    f"- 假设：{experiment.hypothesis}",
                    f"  - 动作：{experiment.action}",
                    f"  - 主指标：{experiment.primary_metric}",
                    f"  - 观察窗口：{experiment.observation_window}",
                    f"  - 证据：{', '.join(experiment.evidence_refs)}",
                ]
            )
    else:
        lines.append("- 本次未生成实验建议。")
    lines.extend(["", "## 局限", ""])
    lines.extend(f"- {item}" for item in result.limitations)
    return "\n".join(lines).rstrip() + "\n"


def _prepare_analysis_context(
    project: ProjectLayout,
    *,
    account_id: str,
    options: GptAnalysisOptions,
) -> PreparedAnalysisContext:
    context = AnalysisContextService(project).build(
        account_id=account_id,
        max_video_analyses=options.max_video_analyses,
    )
    if context.get("account") is None:
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            f"No normalized account found for GPT analysis: {account_id}",
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

    checks: list[dict[str, Any]] = [
        {
            "id": "citation_completeness",
            "question": "Does every finding, action, and experiment include evidence?",
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
            "id": "derived_analysis_boundary",
            "question": "Is the GPT output isolated from Rule and Rubric source records?",
            "status": "pass",
            "write_scope": "analyses/gpt only",
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
                "OpenAI analysis requires explicit data-upload and cost confirmation",
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
            "model": options.model.value,
            "template": options.template.value,
            "reasoning_effort": options.reasoning_effort.value,
            "data_scope": {
                "context_bytes": prepared.context_bytes,
                "request_bytes": request_bytes,
                "max_video_analyses": options.max_video_analyses,
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
                "model": options.model.value,
                "template": options.template.value,
                "reasoning_effort": options.reasoning_effort.value,
            }
        )
        analysis_id_parts = [
            account_id,
            GPT_ANALYSIS_VERSION,
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
            return {
                "ok": True,
                "already_generated": True,
                "analysis": cached,
                "audit": read_json(audit_path),
                "evaluation": read_json(evaluation_path),
                "outputs": relative_paths,
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
                    "api_key_source": OPENAI_API_KEY_ENV,
                    "raw_response_persisted": False,
                },
                "write_boundary": "derived_analysis_only",
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
