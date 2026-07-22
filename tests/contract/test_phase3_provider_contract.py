from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from video_account_distiller.features import StructuredFileProvider, VideoAnalysisService
from video_account_distiller.models import SingleVideoAnalysis
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class RecordingProvider:
    provider_name = "recording-fixture"
    model_name = "recording-model"

    def __init__(self, delegate: StructuredFileProvider) -> None:
        self.delegate = delegate
        self.prompts: list[str] = []

    def generate_structured(
        self,
        prompt: str,
        response_model: type[ResponseT],
        *,
        temperature: float = 0.0,
    ) -> ResponseT:
        self.prompts.append(prompt)
        return self.delegate.generate_structured(
            prompt,
            response_model,
            temperature=temperature,
        )


def test_provider_retries_schema_failure_and_never_sees_metrics(
    phase3_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    recording = RecordingProvider(
        StructuredFileProvider(fixtures_dir / "phase3" / "model-output-retry.json")
    )
    result = VideoAnalysisService(phase3_project).analyze(
        video_id=stable_id("vid_", "douyin", "p2-01"),
        provider=recording,
        max_attempts=2,
        dry_run=True,
    )
    analysis = SingleVideoAnalysis.model_validate(result["analysis"])
    assert analysis.blind_analysis.task_traces[0].attempts == 2
    assert analysis.blind_analysis.task_traces[0].status == "success"
    assert len(recording.prompts) == 3
    forbidden = (
        '"views"',
        '"likes"',
        '"performance_score"',
        '"performance_band"',
        '"engagement_rate_by_view"',
    )
    assert all(not any(key in prompt for key in forbidden) for prompt in recording.prompts)
