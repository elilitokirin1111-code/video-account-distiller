"""Controlled, budget-gated regression evaluation for remote GPT account analysis."""

from __future__ import annotations

from collections.abc import Callable
from itertools import combinations
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights.gpt_analysis import (
    GPT_PRICING_SNAPSHOT,
    AccountAnalysisProvider,
    AnalysisTemplate,
    GptAnalysisOptions,
    OpenAIModel,
    ReasoningEffort,
    RemoteAccountAnalysisService,
    StrictModel,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.io import (
    atomic_write_json,
    atomic_write_text,
    read_json,
)

GPT_EVALUATION_SUITE_VERSION: Literal["gpt-evaluation-suite-v1"] = "gpt-evaluation-suite-v1"
GPT_EVALUATION_RESULT_VERSION = "gpt-evaluation-result-v1"
_SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$"


class GptEvaluationCase(StrictModel):
    """One fixed account and model configuration in a regression suite."""

    case_id: str = Field(pattern=_SAFE_ID_PATTERN)
    account_id: str = Field(min_length=1, max_length=160)
    model: OpenAIModel = OpenAIModel.TERRA
    template: AnalysisTemplate = AnalysisTemplate.ACCOUNT_HEALTH
    reasoning_effort: ReasoningEffort = ReasoningEffort.LOW
    max_video_analyses: int = Field(default=100, ge=1, le=1_000)
    runs_per_case: int = Field(default=2, ge=2, le=5)

    def options(self, *, authorized: bool) -> GptAnalysisOptions:
        return GptAnalysisOptions(
            model=self.model,
            template=self.template,
            reasoning_effort=self.reasoning_effort,
            max_video_analyses=self.max_video_analyses,
            confirm_cloud_upload=authorized,
            confirm_cost=authorized,
        )


class GptEvaluationSuite(StrictModel):
    """Versioned fixed-account suite with an explicit maximum payable budget."""

    version: Literal["gpt-evaluation-suite-v1"] = GPT_EVALUATION_SUITE_VERSION
    suite_id: str = Field(pattern=_SAFE_ID_PATTERN)
    description: str = Field(default="", max_length=500)
    max_total_cost_usd: float = Field(gt=0, le=1_000)
    stability_threshold: float = Field(default=0.6, ge=0, le=1)
    cases: list[GptEvaluationCase] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_cases(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id values must be unique")
        identities = [
            (
                case.account_id,
                case.model,
                case.template,
                case.reasoning_effort,
                case.max_video_analyses,
            )
            for case in self.cases
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("equivalent account/model cases must not be duplicated")
        return self


class GptEvaluationPreviewRequest(StrictModel):
    """Secret-free request for a no-network evaluation preview."""

    suite: GptEvaluationSuite
    campaign_id: str = Field(pattern=_SAFE_ID_PATTERN)


class GptEvaluationRunRequest(GptEvaluationPreviewRequest):
    """Execution request bound to one reviewed preview and three confirmations."""

    confirmed_preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm_cloud_upload: bool = False
    confirm_cost: bool = False
    confirm_independent_paid_runs: bool = False


ProviderFactory = Callable[[GptEvaluationCase, int], AccountAnalysisProvider]


def _check(evaluation: dict[str, Any], check_id: str) -> dict[str, Any]:
    checks = evaluation.get("checks")
    if not isinstance(checks, list):
        return {}
    for item in checks:
        if isinstance(item, dict) and item.get("id") == check_id:
            return item
    return {}


def _estimated_cost(result: dict[str, Any]) -> float | None:
    audit = result.get("audit")
    if not isinstance(audit, dict):
        return None
    response = audit.get("response")
    if not isinstance(response, dict):
        return None
    estimate = response.get("estimated_cost")
    if not isinstance(estimate, dict):
        return None
    value = estimate.get("estimated_total_usd")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _finding_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_values = left.get("finding_fingerprints")
    right_values = right.get("finding_fingerprints")
    left_set = set(left_values) if isinstance(left_values, list) else set()
    right_set = set(right_values) if isinstance(right_values, list) else set()
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


def _case_summary(
    case: GptEvaluationCase,
    results: list[dict[str, Any]],
    *,
    stability_threshold: float,
) -> dict[str, Any]:
    run_summaries: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    for run_index, result in enumerate(results, start=1):
        evaluation = result.get("evaluation")
        evaluation_payload = evaluation if isinstance(evaluation, dict) else {}
        evaluations.append(evaluation_payload)
        citation = _check(evaluation_payload, "citation_completeness")
        integrity = _check(evaluation_payload, "evidence_allowlist_integrity")
        numeric = _check(evaluation_payload, "hallucination_numeric_claim_review")
        analysis = result.get("analysis")
        analysis_payload = analysis if isinstance(analysis, dict) else {}
        run_summaries.append(
            {
                "run_index": run_index,
                "analysis_id": analysis_payload.get("analysis_id"),
                "already_generated": bool(result.get("already_generated")),
                "output_hash": analysis_payload.get("output_hash"),
                "citation_completeness": citation.get("value"),
                "citation_status": citation.get("status", "missing"),
                "evidence_integrity_status": integrity.get("status", "missing"),
                "numeric_claim_status": numeric.get("status", "missing"),
                "estimated_cost_usd": _estimated_cost(result),
                "outputs": result.get("outputs", []),
            }
        )

    similarities = [
        round(_finding_similarity(evaluations[left - 1], evaluations[right - 1]), 6)
        for left, right in combinations(range(1, len(evaluations) + 1), 2)
    ]
    minimum_similarity = min(similarities) if similarities else None
    mean_similarity = round(sum(similarities) / len(similarities), 6) if similarities else None
    stability_passed = minimum_similarity is not None and minimum_similarity >= stability_threshold
    return {
        "case_id": case.case_id,
        "account_id": case.account_id,
        "configuration": {
            "model": case.model.value,
            "template": case.template.value,
            "reasoning_effort": case.reasoning_effort.value,
            "max_video_analyses": case.max_video_analyses,
        },
        "requested_runs": case.runs_per_case,
        "remote_calls_performed": sum(not item["already_generated"] for item in run_summaries),
        "cached_runs": sum(item["already_generated"] for item in run_summaries),
        "citation_complete_runs": sum(item["citation_status"] == "pass" for item in run_summaries),
        "evidence_integrity_passed_runs": sum(
            item["evidence_integrity_status"] == "pass" for item in run_summaries
        ),
        "numeric_claim_review_runs": sum(
            item["numeric_claim_status"] == "review_required" for item in run_summaries
        ),
        "stability": {
            "status": "pass" if stability_passed else "fail",
            "threshold": stability_threshold,
            "pair_count": len(similarities),
            "pairwise_finding_jaccard_similarity": similarities,
            "minimum_finding_jaccard_similarity": minimum_similarity,
            "mean_finding_jaccard_similarity": mean_similarity,
        },
        "runs": run_summaries,
    }


def _render_report(result: dict[str, Any]) -> str:
    quality = result["quality"]
    cost = result["cost"]
    lines = [
        f"# GPT evaluation: {result['suite_id']} / {result['campaign_id']}",
        "",
        f"- Acceptance status: `{result['acceptance_status']}`",
        f"- Planned independent runs: {result['counts']['planned_runs']}",
        f"- Remote calls performed: {result['counts']['remote_calls_performed']}",
        f"- Cached runs: {result['counts']['cached_runs']}",
        f"- Citation-complete runs: {quality['citation_complete_runs']}",
        f"- Evidence-integrity runs: {quality['evidence_integrity_passed_runs']}",
        f"- Stability-passing cases: {quality['stability_passed_cases']}",
        f"- Estimated total cost (USD): {cost['total_estimated_usd']}",
        f"- Approved budget (USD): {cost['approved_budget_usd']}",
        "",
        "## Cases",
        "",
    ]
    for case in result["cases"]:
        stability = case["stability"]
        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"- Account: `{case['account_id']}`",
                f"- Stability: `{stability['status']}` "
                f"(minimum Jaccard: {stability['minimum_finding_jaccard_similarity']})",
                f"- New/cached runs: {case['remote_calls_performed']}/{case['cached_runs']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            "This report estimates API cost from response usage. The provider invoice remains "
            "authoritative. Semantic correctness and business usefulness still require review.",
            "",
        ]
    )
    return "\n".join(lines)


class GptEvaluationService:
    """Preview and execute a fixed-account GPT regression campaign."""

    def __init__(
        self,
        project: ProjectLayout,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self.project = project
        self.provider_factory = provider_factory

    def preview(self, request: GptEvaluationPreviewRequest) -> dict[str, Any]:
        case_previews: list[dict[str, Any]] = []
        planned_runs = 0
        conservative_total = 0.0
        for case in request.suite.cases:
            preview = RemoteAccountAnalysisService.preview(
                self.project,
                account_id=case.account_id,
                options=case.options(authorized=False),
            )
            case_maximum = float(preview["cost_preview"]["conservative_maximum_usd"])
            planned_case_cost = round(case_maximum * case.runs_per_case, 6)
            planned_runs += case.runs_per_case
            conservative_total += planned_case_cost
            case_previews.append(
                {
                    "case_id": case.case_id,
                    "account_id": case.account_id,
                    "runs_per_case": case.runs_per_case,
                    "request": {
                        "model": preview["model"],
                        "template": preview["template"],
                        "reasoning_effort": preview["reasoning_effort"],
                        "data_scope": preview["data_scope"],
                        "request_fingerprints": preview["request_fingerprints"],
                    },
                    "cost": {
                        "per_run_conservative_maximum_usd": case_maximum,
                        "case_conservative_maximum_usd": planned_case_cost,
                    },
                }
            )
        conservative_total = round(conservative_total, 6)
        budget = request.suite.max_total_cost_usd
        payload: dict[str, Any] = {
            "ok": True,
            "remote_call_performed": False,
            "suite_version": request.suite.version,
            "suite_id": request.suite.suite_id,
            "campaign_id": request.campaign_id,
            "suite_fingerprint": sha256_json(request.suite.model_dump(mode="json")),
            "pricing_snapshot": GPT_PRICING_SNAPSHOT,
            "planned_independent_runs": planned_runs,
            "cases": case_previews,
            "budget": {
                "currency": "USD",
                "approved_maximum_usd": budget,
                "conservative_maximum_usd": conservative_total,
                "remaining_headroom_usd": round(budget - conservative_total, 6),
                "within_limit": conservative_total <= budget,
            },
            "confirmations_required": [
                "confirmed_preview_hash=<preview_hash>",
                "confirm_cloud_upload=true",
                "confirm_cost=true",
                "confirm_independent_paid_runs=true",
            ],
        }
        payload["preview_hash"] = sha256_json(payload)
        return payload

    def authorize(self, request: GptEvaluationRunRequest) -> dict[str, Any]:
        missing = []
        if not request.confirm_cloud_upload:
            missing.append("confirm_cloud_upload=true")
        if not request.confirm_cost:
            missing.append("confirm_cost=true")
        if not request.confirm_independent_paid_runs:
            missing.append("confirm_independent_paid_runs=true")
        if missing:
            raise DistillerError(
                ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED,
                "GPT evaluation requires explicit upload, cost, and independent-run confirmation",
                details={"required": missing},
            )
        preview = self.preview(
            GptEvaluationPreviewRequest(
                suite=request.suite,
                campaign_id=request.campaign_id,
            )
        )
        if request.confirmed_preview_hash != preview["preview_hash"]:
            raise DistillerError(
                ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED,
                "GPT evaluation preview changed or was not the confirmed preview",
                details={
                    "confirmed_preview_hash": request.confirmed_preview_hash,
                    "current_preview_hash": preview["preview_hash"],
                    "next": "review the current preview and confirm its hash",
                },
            )
        if not preview["budget"]["within_limit"]:
            raise DistillerError(
                ErrorCode.GPT_EVALUATION_BUDGET_EXCEEDED,
                "GPT evaluation conservative cost exceeds the suite budget",
                details={
                    "approved_maximum_usd": preview["budget"]["approved_maximum_usd"],
                    "conservative_maximum_usd": preview["budget"]["conservative_maximum_usd"],
                    "next": "reduce cases/runs or raise the suite budget after review",
                },
            )
        RemoteAccountAnalysisService.require_authorization(
            self.project,
            request.suite.cases[0].options(authorized=True),
        )
        return preview

    def run(self, request: GptEvaluationRunRequest) -> dict[str, Any]:
        preview = self.authorize(request)
        output_dir = (
            self.project.root / "evaluations" / "gpt" / request.suite.suite_id / request.campaign_id
        )
        suite_path = output_dir / "suite.json"
        preview_path = output_dir / "preview.json"
        result_path = output_dir / "result.json"
        report_path = output_dir / "report.md"
        paths: list[Path] = [suite_path, preview_path, result_path, report_path]
        existing_paths = [path for path in paths if path.is_file()]
        existing_preview_hash: Any = None
        cached: dict[str, Any] | None = None
        if result_path.is_file():
            cached = read_json(result_path)
            existing_preview_hash = cached.get("preview_hash")
        elif preview_path.is_file():
            existing_preview_hash = read_json(preview_path).get("preview_hash")
        if existing_paths and existing_preview_hash != preview["preview_hash"]:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "GPT evaluation campaign output already belongs to a different preview",
                details={
                    "suite_id": request.suite.suite_id,
                    "campaign_id": request.campaign_id,
                    "existing_preview_hash": existing_preview_hash,
                    "current_preview_hash": preview["preview_hash"],
                    "next": "use a new campaign_id; existing campaign evidence is immutable",
                },
            )
        if cached is not None and all(path.is_file() for path in paths):
            if (
                cached.get("preview_hash") == preview["preview_hash"]
                and cached.get("suite_fingerprint") == preview["suite_fingerprint"]
            ):
                return {**cached, "already_generated": True}
        if self.provider_factory is None:
            raise DistillerError(
                ErrorCode.INTERNAL,
                "GPT evaluation provider factory is not configured",
            )
        suite_run = self.project.begin_run(
            "evaluate gpt regression suite",
            input_hashes=[preview["preview_hash"], preview["suite_fingerprint"]],
        )
        case_summaries: list[dict[str, Any]] = []
        try:
            for case in request.suite.cases:
                results: list[dict[str, Any]] = []
                for run_index in range(1, case.runs_per_case + 1):
                    evaluation_run_key = (
                        f"{request.suite.suite_id}:{request.campaign_id}:"
                        f"{case.case_id}:{run_index:02d}"
                    )
                    provider = self.provider_factory(case, run_index)
                    results.append(
                        RemoteAccountAnalysisService(self.project, provider).analyze(
                            account_id=case.account_id,
                            options=case.options(authorized=True),
                            evaluation_run_key=evaluation_run_key,
                        )
                    )
                case_summaries.append(
                    _case_summary(
                        case,
                        results,
                        stability_threshold=request.suite.stability_threshold,
                    )
                )

            runs = [run for case in case_summaries for run in case["runs"]]
            known_costs = [
                float(run["estimated_cost_usd"])
                for run in runs
                if run["estimated_cost_usd"] is not None
            ]
            unknown_cost_runs = len(runs) - len(known_costs)
            total_estimated = round(sum(known_costs), 8)
            citation_complete_runs = sum(case["citation_complete_runs"] for case in case_summaries)
            evidence_integrity_runs = sum(
                case["evidence_integrity_passed_runs"] for case in case_summaries
            )
            stability_passed_cases = sum(
                case["stability"]["status"] == "pass" for case in case_summaries
            )
            numeric_review_runs = sum(case["numeric_claim_review_runs"] for case in case_summaries)
            hard_failure = (
                citation_complete_runs != len(runs)
                or evidence_integrity_runs != len(runs)
                or stability_passed_cases != len(case_summaries)
                or total_estimated > request.suite.max_total_cost_usd
            )
            review_required = unknown_cost_runs > 0 or numeric_review_runs > 0
            acceptance_status = (
                "fail" if hard_failure else "review_required" if review_required else "pass"
            )
            result: dict[str, Any] = {
                "ok": True,
                "result_version": GPT_EVALUATION_RESULT_VERSION,
                "suite_version": request.suite.version,
                "suite_id": request.suite.suite_id,
                "campaign_id": request.campaign_id,
                "suite_run_id": suite_run.run_id,
                "preview_hash": preview["preview_hash"],
                "suite_fingerprint": preview["suite_fingerprint"],
                "pricing_snapshot": GPT_PRICING_SNAPSHOT,
                "acceptance_status": acceptance_status,
                "already_generated": False,
                "manual_review_required": review_required,
                "counts": {
                    "cases": len(case_summaries),
                    "planned_runs": len(runs),
                    "remote_calls_performed": sum(
                        case["remote_calls_performed"] for case in case_summaries
                    ),
                    "cached_runs": sum(case["cached_runs"] for case in case_summaries),
                },
                "quality": {
                    "citation_complete_runs": citation_complete_runs,
                    "citation_completeness_rate": round(citation_complete_runs / len(runs), 6),
                    "evidence_integrity_passed_runs": evidence_integrity_runs,
                    "evidence_integrity_rate": round(evidence_integrity_runs / len(runs), 6),
                    "stability_passed_cases": stability_passed_cases,
                    "stability_threshold": request.suite.stability_threshold,
                    "numeric_claim_review_runs": numeric_review_runs,
                },
                "cost": {
                    "currency": "USD",
                    "approved_budget_usd": request.suite.max_total_cost_usd,
                    "conservative_maximum_usd": preview["budget"]["conservative_maximum_usd"],
                    "known_estimated_cost_usd": total_estimated,
                    "total_estimated_usd": (total_estimated if unknown_cost_runs == 0 else None),
                    "unknown_cost_runs": unknown_cost_runs,
                    "mean_estimated_cost_per_run_usd": (
                        round(total_estimated / len(known_costs), 8) if known_costs else None
                    ),
                    "authoritative_source": "OpenAI billing dashboard/invoice",
                },
                "cases": case_summaries,
                "authorization": {
                    "cloud_upload_confirmed": True,
                    "cost_confirmed": True,
                    "independent_paid_runs_confirmed": True,
                    "confirmed_preview_hash": request.confirmed_preview_hash,
                },
            }
            relative_paths = [self.project.relative(path) for path in paths]
            result["outputs"] = relative_paths
            output_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                suite_path,
                {
                    "suite": request.suite.model_dump(mode="json"),
                    "campaign_id": request.campaign_id,
                },
            )
            atomic_write_json(preview_path, preview)
            atomic_write_json(result_path, result)
            atomic_write_text(report_path, _render_report(result))
        except Exception as exc:
            error = (
                f"{exc.code.value}: {exc.message}"
                if isinstance(exc, DistillerError)
                else f"{type(exc).__name__}: {exc}"
            )
            self.project.finish_run(
                suite_run,
                success=False,
                errors=[error[:1_000]],
            )
            raise

        self.project.finish_run(
            suite_run,
            success=True,
            processed_counts={
                "cases": len(case_summaries),
                "runs": result["counts"]["planned_runs"],
                "remote_calls": result["counts"]["remote_calls_performed"],
            },
            output_files=result["outputs"],
        )
        return result
