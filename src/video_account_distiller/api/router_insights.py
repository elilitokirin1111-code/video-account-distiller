"""Read-only account insight endpoints for people and model workflows."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.tasks import enqueue_ephemeral_task
from video_account_distiller.growth import AccountGrowthService
from video_account_distiller.insights import (
    AnalysisContextService,
    GptAnalysisRequest,
    GptEvaluationCase,
    GptEvaluationPreviewRequest,
    GptEvaluationRunRequest,
    GptEvaluationService,
    OpenAIResponsesProvider,
    RemoteAccountAnalysisService,
)

router = APIRouter()


@router.get("/{project_path:path}/accounts/{account_id}/growth")
async def account_growth(project_path: str, account_id: str) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return AccountGrowthService(layout).summarize(account_id=account_id)


@router.get("/{project_path:path}/accounts/{account_id}/analysis-context")
async def account_analysis_context(
    project_path: str,
    account_id: str,
    max_video_analyses: int = 10,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return AnalysisContextService(layout).build(
        account_id=account_id,
        max_video_analyses=max_video_analyses,
    )


@router.post("/{project_path:path}/accounts/{account_id}/gpt-analysis")
async def account_gpt_analysis(
    project_path: str,
    account_id: str,
    request: Request,
    body: GptAnalysisRequest,
) -> dict[str, Any]:
    """Run one explicitly authorized OpenAI analysis with an environment-only key."""

    layout = resolve_project(project_path)
    options = body.options()
    RemoteAccountAnalysisService.require_authorization(layout, options)
    provider = OpenAIResponsesProvider.from_environment(
        model=options.model,
        reasoning_effort=options.reasoning_effort,
        executor=getattr(request.app.state, "openai_executor", None),
    )
    service = RemoteAccountAnalysisService(layout, provider)
    return enqueue_ephemeral_task(
        request.app.state.tasks,
        service.analyze,
        account_id=account_id,
        options=options,
        task_type="gpt_account_analysis",
        resource_class="model",
    )


@router.post("/{project_path:path}/accounts/{account_id}/gpt-analysis/preview")
async def preview_account_gpt_analysis(
    project_path: str,
    account_id: str,
    body: GptAnalysisRequest,
) -> dict[str, Any]:
    """Return the bounded data scope, fingerprints, and price ceiling without a model call."""

    layout = resolve_project(project_path)
    return RemoteAccountAnalysisService.preview(
        layout,
        account_id=account_id,
        options=body.options(),
    )


@router.post("/{project_path:path}/gpt-evaluations/preview")
async def preview_gpt_evaluation(
    project_path: str,
    body: GptEvaluationPreviewRequest,
) -> dict[str, Any]:
    """Preview every fixed-account run and budget without invoking a model."""

    layout = resolve_project(project_path)
    return GptEvaluationService(layout).preview(body)


@router.post("/{project_path:path}/gpt-evaluations/run")
async def run_gpt_evaluation(
    project_path: str,
    request: Request,
    body: GptEvaluationRunRequest,
) -> dict[str, Any]:
    """Enqueue one explicitly confirmed, preview-bound paid evaluation campaign."""

    layout = resolve_project(project_path)
    evaluator = GptEvaluationService(layout)
    evaluator.authorize(body)
    executor = getattr(request.app.state, "openai_executor", None)
    providers = {
        (case.model, case.reasoning_effort): OpenAIResponsesProvider.from_environment(
            model=case.model,
            reasoning_effort=case.reasoning_effort,
            executor=executor,
        )
        for case in body.suite.cases
    }

    def _provider(case: GptEvaluationCase, _: int) -> OpenAIResponsesProvider:
        return providers[(case.model, case.reasoning_effort)]

    service = GptEvaluationService(layout, _provider)
    return enqueue_ephemeral_task(
        request.app.state.tasks,
        service.run,
        body,
        task_type="gpt_regression_evaluation",
        resource_class="model",
    )
