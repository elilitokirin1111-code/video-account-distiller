from __future__ import annotations

from typing import Any

import pytest

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights import (
    GptAccountAnalysis,
    GptEvaluationCase,
    GptEvaluationPreviewRequest,
    GptEvaluationRunRequest,
    GptEvaluationService,
    GptEvaluationSuite,
)
from video_account_distiller.insights.gpt_analysis import ProviderAnalysis
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_text, read_json


def _enable_cloud(project: ProjectLayout) -> None:
    config = load_config(project.config_path)
    updated = config.model_copy(
        update={"privacy": config.privacy.model_copy(update={"allow_cloud_model_upload": True})}
    )
    atomic_write_text(project.config_path, updated.as_yaml())


def _analysis(title: str = "Account snapshot is present") -> GptAccountAnalysis:
    return GptAccountAnalysis.model_validate(
        {
            "executive_summary": "The submitted evidence supports a bounded account review.",
            "findings": [
                {
                    "classification": "observed_fact",
                    "title": title,
                    "statement": "The account context contains a normalized public snapshot.",
                    "evidence_refs": ["context://account"],
                    "confidence": "high",
                }
            ],
            "priority_actions": [
                {
                    "priority": 1,
                    "action": "Continue collecting comparable snapshots.",
                    "rationale": "Growth conclusions need observations across time.",
                    "evidence_refs": ["context://growth"],
                }
            ],
            "experiments": [
                {
                    "hypothesis": "A consistent topic cadence may improve comparability.",
                    "action": "Publish within one stable topic for the next observation window.",
                    "primary_metric": "engagement_rate_by_view",
                    "observation_window": "next review window",
                    "evidence_refs": ["context://data-availability"],
                }
            ],
            "limitations": ["The evidence is limited to locally available artifacts."],
        }
    )


class EvaluationProvider:
    provider_name = "fake_openai"
    model_name = "gpt-5.6-terra"
    credential_env = "OPENAI_API_KEY"
    credential_source = "OPENAI_API_KEY"

    def __init__(self, run_index: int, calls: list[int], *, vary: bool = False) -> None:
        self.run_index = run_index
        self.calls = calls
        self.vary = vary

    def analyze(self, *, instructions: str, context_json: str) -> ProviderAnalysis:
        assert "Evidence allowlist" in instructions
        assert context_json
        self.calls.append(self.run_index)
        title = (
            f"Distinct conclusion for independent run {self.run_index}"
            if self.vary
            else "Account snapshot is present"
        )
        return ProviderAnalysis(
            response_id=f"resp_eval_{self.run_index}",
            model=self.model_name,
            status="completed",
            analysis=_analysis(title),
            usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )


def _suite(account_id: str, *, budget: float = 1.0) -> GptEvaluationSuite:
    return GptEvaluationSuite(
        suite_id="hotel-regression",
        description="Fixed local account regression set.",
        max_total_cost_usd=budget,
        cases=[
            GptEvaluationCase(
                case_id="account-health",
                account_id=account_id,
                runs_per_case=2,
            )
        ],
    )


def _run_request(
    suite: GptEvaluationSuite,
    *,
    campaign_id: str,
    preview_hash: str,
) -> GptEvaluationRunRequest:
    return GptEvaluationRunRequest(
        suite=suite,
        campaign_id=campaign_id,
        confirmed_preview_hash=preview_hash,
        confirm_cloud_upload=True,
        confirm_cost=True,
        confirm_independent_paid_runs=True,
    )


def test_evaluation_preview_is_no_network_and_budget_gate_precedes_provider(
    normalized_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    suite = _suite(account_id, budget=0.000001)
    calls: list[int] = []
    service = GptEvaluationService(
        normalized_project,
        lambda case, run_index: EvaluationProvider(run_index, calls),
    )
    preview_request = GptEvaluationPreviewRequest(
        suite=suite,
        campaign_id="budget-gate",
    )
    preview = service.preview(preview_request)

    assert preview["remote_call_performed"] is False
    assert preview["planned_independent_runs"] == 2
    assert preview["budget"]["within_limit"] is False
    assert preview["preview_hash"]
    assert not calls

    with pytest.raises(DistillerError) as stale:
        service.run(
            _run_request(
                suite,
                campaign_id="budget-gate",
                preview_hash="0" * 64,
            )
        )
    assert stale.value.code is ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED

    with pytest.raises(DistillerError) as over_budget:
        service.run(
            _run_request(
                suite,
                campaign_id="budget-gate",
                preview_hash=preview["preview_hash"],
            )
        )
    assert over_budget.value.code is ErrorCode.GPT_EVALUATION_BUDGET_EXCEEDED
    assert not calls


def test_evaluation_campaign_is_independent_retry_safe_and_audited(
    normalized_project: ProjectLayout,
) -> None:
    _enable_cloud(normalized_project)
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    suite = _suite(account_id)
    calls: list[int] = []
    service = GptEvaluationService(
        normalized_project,
        lambda case, run_index: EvaluationProvider(run_index, calls),
    )
    preview = service.preview(GptEvaluationPreviewRequest(suite=suite, campaign_id="acceptance-01"))
    request = _run_request(
        suite,
        campaign_id="acceptance-01",
        preview_hash=preview["preview_hash"],
    )

    first = service.run(request)
    first_ids = [run["analysis_id"] for run in first["cases"][0]["runs"]]
    second = service.run(request)

    assert calls == [1, 2]
    assert len(set(first_ids)) == 2
    assert first["acceptance_status"] == "pass"
    assert first["counts"] == {
        "cases": 1,
        "planned_runs": 2,
        "remote_calls_performed": 2,
        "cached_runs": 0,
    }
    assert second["already_generated"] is True
    assert second["counts"] == first["counts"]
    assert first["quality"]["citation_completeness_rate"] == 1.0
    assert first["quality"]["evidence_integrity_rate"] == 1.0
    assert first["cases"][0]["stability"]["minimum_finding_jaccard_similarity"] == 1.0
    assert first["cost"]["total_estimated_usd"] == 0.002
    for relative in first["outputs"]:
        assert (normalized_project.root / relative).is_file()

    audit_path = normalized_project.root / first["cases"][0]["runs"][0]["outputs"][1]
    audit: Any = read_json(audit_path)
    assert (
        audit["request"]["evaluation_run_key"] == "hotel-regression:acceptance-01:account-health:01"
    )
    assert audit["request"]["cloud_upload_confirmed"] is True
    assert audit["request"]["cost_confirmed"] is True

    changed_suite = suite.model_copy(update={"description": "Changed suite definition."})
    changed_preview = service.preview(
        GptEvaluationPreviewRequest(
            suite=changed_suite,
            campaign_id="acceptance-01",
        )
    )
    with pytest.raises(DistillerError) as collision:
        service.run(
            _run_request(
                changed_suite,
                campaign_id="acceptance-01",
                preview_hash=changed_preview["preview_hash"],
            )
        )
    assert collision.value.code is ErrorCode.SCHEMA_INVALID
    assert calls == [1, 2]

    next_preview = service.preview(
        GptEvaluationPreviewRequest(suite=suite, campaign_id="acceptance-02")
    )
    next_result = service.run(
        _run_request(
            suite,
            campaign_id="acceptance-02",
            preview_hash=next_preview["preview_hash"],
        )
    )
    next_ids = [run["analysis_id"] for run in next_result["cases"][0]["runs"]]
    assert calls == [1, 2, 1, 2]
    assert set(first_ids).isdisjoint(next_ids)


def test_evaluation_marks_unstable_independent_findings_as_failed(
    normalized_project: ProjectLayout,
) -> None:
    _enable_cloud(normalized_project)
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    suite = _suite(account_id)
    calls: list[int] = []
    service = GptEvaluationService(
        normalized_project,
        lambda case, run_index: EvaluationProvider(run_index, calls, vary=True),
    )
    preview = service.preview(GptEvaluationPreviewRequest(suite=suite, campaign_id="unstable"))

    result = service.run(
        _run_request(
            suite,
            campaign_id="unstable",
            preview_hash=preview["preview_hash"],
        )
    )

    assert calls == [1, 2]
    assert result["acceptance_status"] == "fail"
    assert result["cases"][0]["stability"]["status"] == "fail"
    assert result["cases"][0]["stability"]["minimum_finding_jaccard_similarity"] == 0.0
