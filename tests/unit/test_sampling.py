from __future__ import annotations

from pathlib import Path

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.sampling import SamplingService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


def test_sampling_requires_derived_metrics(normalized_project: ProjectLayout) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    with pytest.raises(DistillerError) as captured:
        SamplingService(normalized_project).select(account_id=account_id)
    assert captured.value.code is ErrorCode.INSUFFICIENT_SAMPLE
    assert "distiller metrics" in captured.value.details["next_command"]


def test_sampling_dry_run_write_and_reuse(phase2_project: ProjectLayout) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = SamplingService(phase2_project)
    preview = service.select(account_id=account_id, size=15, dry_run=True)
    preview_path = phase2_project.root / Path(str(preview["output"]))
    assert preview["dry_run"] is True
    assert not preview_path.exists()

    created = service.select(account_id=account_id, size=15)
    manifest = created["manifest"]
    assert manifest["population_size"] == 30
    assert manifest["selected_size"] == 15
    assert preview["manifest"]["sample_manifest_id"] == manifest["sample_manifest_id"]
    assert preview_path.is_file()

    reused = service.select(account_id=account_id, size=15)
    assert reused["already_generated"] is True
    assert reused["manifest"]["run_id"] == manifest["run_id"]

    all_rows = service.select(account_id=account_id, size=100, dry_run=True)["manifest"]
    assert all_rows["requested_size"] == 100
    assert all_rows["target_size"] == 30
    assert all_rows["selected_size"] == 30
    assert any("requested_size_reduced" in warning for warning in all_rows["warnings"])
    assert all("population:all" in item["selection_reasons"] for item in all_rows["selected"])


def test_sampling_rejects_zero_size_at_library_boundary(phase2_project: ProjectLayout) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    with pytest.raises(DistillerError) as captured:
        SamplingService(phase2_project).select(account_id=account_id, size=0)
    assert captured.value.code is ErrorCode.SCHEMA_INVALID
