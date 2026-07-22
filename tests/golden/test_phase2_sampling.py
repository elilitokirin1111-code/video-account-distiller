from __future__ import annotations

from video_account_distiller.models import SampleManifest
from video_account_distiller.sampling import SamplingService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


def test_phase2_golden_sample_covers_required_strata(phase2_project: ProjectLayout) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    result = SamplingService(phase2_project).select(account_id=account_id, size=15)
    manifest = SampleManifest.model_validate(result["manifest"])

    assert manifest.population_size == 30
    assert manifest.selected_size == 15
    assert set(manifest.selected_coverage.performance) >= {"S", "A", "B", "C", "D"}
    assert set(manifest.selected_coverage.content_pillar) == {"food", "room", "service"}
    assert set(manifest.selected_coverage.duration) == {
        "long_ge_60s",
        "medium_30_59s",
        "short_lt_30s",
    }
    assert manifest.selected_coverage.recency["recent"] >= 1
    assert manifest.selected_coverage.special["promoted_or_ad"] >= 1
    assert manifest.selected_coverage.special["outlier"] >= 1
    assert all(item.selection_reasons for item in manifest.selected)
    assert len({item.video_id for item in manifest.selected}) == manifest.selected_size
