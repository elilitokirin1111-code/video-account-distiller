from __future__ import annotations

import json
from datetime import UTC, datetime

from video_account_distiller.models import Comment, Platform
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.storage.project import ProjectLayout


def test_normalization_accepts_unicode_line_separator_in_comment(
    project: ProjectLayout,
) -> None:
    """JSONL records must not be split on U+2028 inside a JSON string."""

    comment = Comment(
        record_id="cmt_unicode_separator",
        source_platform=Platform.DOUYIN,
        source_type="comment",
        source_record_id="sr_unicode_separator",
        run_id="run_test",
        raw_hash="a" * 64,
        comment_id="cmt_unicode_separator",
        video_id="vid_test",
        platform_comment_id="pc_unicode_separator",
        text="可能是我阅历还不够\u2028现代衣装设计，感觉越来越西式化了。",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    staging = project.root / "staging" / "comments"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "unicode-separator.jsonl").write_text(
        json.dumps(comment.model_dump(mode="json"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = NormalizationService(project).normalize(dry_run=True)

    assert result["ok"] is True
    assert result["counts"]["comments"] == 1
    assert not (result.get("quality") or {}).get("issues")
