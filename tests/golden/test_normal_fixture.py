from __future__ import annotations

from video_account_distiller.metrics import MetricsService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


def test_normal_fixture_has_high_middle_low_and_promoted(
    normalized_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    result = MetricsService(normalized_project).calculate(account_id=account_id)
    assert result["bands"] == {"S": 1, "A": 1, "B": 2, "C": 1, "D": 1}
