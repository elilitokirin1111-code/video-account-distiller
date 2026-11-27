"""CLI commands for controlled GPT regression previews and paid campaigns."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from video_account_distiller.cli_runtime import emit, execute
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights import (
    GptEvaluationPreviewRequest,
    GptEvaluationRunRequest,
    GptEvaluationService,
    GptEvaluationSuite,
    OpenAIResponsesProvider,
)
from video_account_distiller.insights.gpt_evaluation import GptEvaluationCase
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import read_json

gpt_evaluation_app = typer.Typer(
    help="Preview and run budget-gated GPT account regression campaigns.",
    no_args_is_help=True,
)


def _load_suite(path: Path) -> GptEvaluationSuite:
    try:
        payload: Any = read_json(path.expanduser().resolve())
        return GptEvaluationSuite.model_validate(payload)
    except (OSError, ValueError, ValidationError) as exc:
        details: dict[str, Any] = {
            "suite_file": str(path),
            "reason": str(exc),
        }
        if isinstance(exc, ValidationError):
            details["validation_errors"] = exc.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "GPT evaluation suite is invalid",
            details=details,
        ) from exc


@gpt_evaluation_app.command("preview")
def preview_command(
    project_dir: Path = typer.Argument(..., help="Initialized project directory."),
    suite_file: Path = typer.Option(..., "--suite", help="Versioned suite JSON file."),
    campaign_id: str = typer.Option(
        ...,
        "--campaign",
        help="Stable campaign ID; reuse it only for idempotent retries.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Preview exact fingerprints and conservative cost without a remote call."""

    def _preview() -> dict[str, Any]:
        project = ProjectLayout.open(project_dir)
        suite = _load_suite(suite_file)
        return GptEvaluationService(project).preview(
            GptEvaluationPreviewRequest(suite=suite, campaign_id=campaign_id)
        )

    preview = execute(_preview, json_output=json_output)
    emit(
        preview,
        json_output=json_output,
        human=(
            f"GPT evaluation preview {preview['preview_hash']}\n"
            f"Planned runs: {preview['planned_independent_runs']}; "
            f"ceiling: USD {preview['budget']['conservative_maximum_usd']}; "
            f"within budget: {preview['budget']['within_limit']}"
        ),
    )


@gpt_evaluation_app.command("run")
def run_command(
    project_dir: Path = typer.Argument(..., help="Initialized project directory."),
    suite_file: Path = typer.Option(..., "--suite", help="Versioned suite JSON file."),
    campaign_id: str = typer.Option(
        ...,
        "--campaign",
        help="Stable campaign ID; a new ID authorizes a new set of paid runs.",
    ),
    confirmed_preview_hash: str = typer.Option(
        ...,
        "--confirmed-preview-hash",
        help="SHA-256 hash printed by the reviewed preview.",
    ),
    confirm_cloud_upload: bool = typer.Option(
        False,
        "--confirm-cloud-upload",
        help="Confirm the bounded redacted contexts may be uploaded.",
    ),
    confirm_cost: bool = typer.Option(
        False,
        "--confirm-cost",
        help="Confirm the reviewed conservative API cost ceiling.",
    ),
    confirm_independent_paid_runs: bool = typer.Option(
        False,
        "--confirm-independent-paid-runs",
        help="Confirm multiple independent, potentially billable model calls.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Run one preview-bound campaign using OPENAI_API_KEY from the environment."""

    def _run() -> dict[str, Any]:
        project = ProjectLayout.open(project_dir)
        suite = _load_suite(suite_file)

        def _provider(case: GptEvaluationCase, _: int) -> OpenAIResponsesProvider:
            return OpenAIResponsesProvider.from_environment(
                model=case.model,
                reasoning_effort=case.reasoning_effort,
            )

        request = GptEvaluationRunRequest(
            suite=suite,
            campaign_id=campaign_id,
            confirmed_preview_hash=confirmed_preview_hash,
            confirm_cloud_upload=confirm_cloud_upload,
            confirm_cost=confirm_cost,
            confirm_independent_paid_runs=confirm_independent_paid_runs,
        )
        return GptEvaluationService(project, _provider).run(request)

    result = execute(_run, json_output=json_output)
    emit(
        result,
        json_output=json_output,
        human=(
            f"GPT evaluation {result['acceptance_status']}: "
            f"{result['counts']['remote_calls_performed']} remote call(s), "
            f"estimated USD {result['cost']['total_estimated_usd']}"
        ),
    )
