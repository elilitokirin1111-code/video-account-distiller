from __future__ import annotations

from pathlib import Path

from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.models import SingleVideoAnalysis
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


def test_phase3_golden_hook_structure_cta_and_pillar(
    phase3_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    result = VideoAnalysisService(phase3_project).analyze(
        video_id=stable_id("vid_", "douyin", "p2-01"),
        model_output=fixtures_dir / "phase3" / "model-output-retry.json",
        max_attempts=2,
        dry_run=True,
    )
    analysis = SingleVideoAnalysis.model_validate(result["analysis"])
    semantics = analysis.blind_analysis.semantics
    assert semantics.primary_pillar == "酒店入住避坑"
    assert semantics.hook.primary_type.value == "number_list"
    assert [item.function.value for item in semantics.structure_segments] == [
        "hook",
        "development",
        "development",
        "cta",
    ]
    assert semantics.cta.primary_type.value == "save"
    assert [item.emotion.value for item in semantics.emotion_timeline] == [
        "curiosity",
        "action",
    ]
    assert analysis.blind_analysis.task_traces[0].attempts == 2
