from __future__ import annotations

import pytest

from video_account_distiller.models import Platform, Video
from video_account_distiller.reports.pipeline import _content_pillar
from video_account_distiller.sampling.dataset import (
    AccountDataset,
    AccountVideoRecord,
    load_account_dataset,
)
from video_account_distiller.sampling.pipeline import _pillar, _sampling_warnings
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.content_pillars import infer_video_content_pillar
from video_account_distiller.utils.ids import stable_id


def _video(
    *,
    content_type: str | None = None,
    title: str | None = None,
    description: str | None = None,
    hashtags: list[str] | None = None,
    transcript_path: str | None = None,
) -> Video:
    return Video(
        record_id="rec_video",
        source_platform=Platform.DOUYIN,
        source_type="video",
        source_record_id="source_video",
        run_id="run_test",
        raw_hash="hash",
        video_id="vid_test",
        account_id="acc_test",
        platform=Platform.DOUYIN,
        platform_video_id="platform_video",
        content_type=content_type,
        title=title,
        description=description,
        hashtags=hashtags or [],
        transcript_path=transcript_path,
    )


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("food", "餐饮与菜品"),
        ("Food & Dining", "餐饮与菜品"),
        ("room", "客房与住宿"),
        ("service-process", "服务与幕后"),
        ("自定义栏目", "自定义栏目"),
    ],
)
def test_meaningful_source_content_type_is_normalized_without_inference(
    content_type: str,
    expected: str,
) -> None:
    assert infer_video_content_pillar(_video(content_type=content_type)) == (expected, False)


@pytest.mark.parametrize("content_type", [None, "", "55", " 68 ", "55.0", "unknown", "degraded"])
def test_unusable_content_type_uses_public_chinese_metadata(content_type: str | None) -> None:
    video = _video(
        content_type=content_type,
        title="来看看这场宝宝宴都有什么菜",
        description="酒店承接百岁宴",
        hashtags=["#婚宴", "即墨"],
    )

    assert infer_video_content_pillar(video) == ("宴会与庆典", True)


@pytest.mark.parametrize(
    ("title", "hashtags", "expected"),
    [
        ("360代400的代金券，直接下单", [], "优惠与活动"),
        ("酒店大厨现炒三十多种菜品", ["小食堂"], "餐饮与菜品"),
        ("带你看不同房型和客房床品", [], "客房与住宿"),
        ("婚宴背后的服务细节", ["幕后"], "服务与幕后"),
        ("妈妈生日快乐，感谢一路陪伴", [], "节日与情感"),
        ("婚礼前六个月应该怎么选场地", ["避坑指南"], "知识与教程"),
        ("接班人的酒店日常", ["记录生活"], "人物与日常"),
    ],
)
def test_public_metadata_maps_to_human_readable_pillars(
    title: str,
    hashtags: list[str],
    expected: str,
) -> None:
    assert infer_video_content_pillar(
        _video(content_type="55", title=title, hashtags=hashtags)
    ) == (expected, True)


def test_inference_does_not_treat_private_or_media_paths_as_content_evidence() -> None:
    video = _video(
        content_type="68",
        title="wedding tutorial",
        description="hotel room promotion",
        transcript_path="private/婚宴客房优惠.txt",
    )

    assert infer_video_content_pillar(video) == ("其他主题", True)


def test_sampling_and_report_use_the_same_shared_resolution() -> None:
    video = _video(content_type="55", title="锦程小食堂三十多种菜品")
    record = AccountVideoRecord(video=video, metric=None, derived=None)

    assert _pillar(record) == "餐饮与菜品"
    assert _content_pillar(record) == _pillar(record)


def test_sampling_warns_when_pillars_are_inferred_from_public_text(
    phase2_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    source = load_account_dataset(phase2_project, account_id)
    inferred_record = AccountVideoRecord(
        video=source.records[0].video.model_copy(
            update={"content_type": "55", "title": "酒店大厨现炒三十多种菜品"}
        ),
        metric=source.records[0].metric,
        derived=source.records[0].derived,
    )
    dataset = AccountDataset(
        account=source.account,
        records=[inferred_record, *source.records[1:]],
        input_hashes=source.input_hashes,
    )

    warnings = _sampling_warnings(dataset, dataset.records, [])

    assert "部分内容方向由标题、描述和话题标签中的明确关键词推断，建议人工复核。" in warnings
