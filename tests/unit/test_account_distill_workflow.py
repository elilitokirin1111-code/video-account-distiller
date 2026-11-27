from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from video_account_distiller.api.tasks import TaskStore, enqueue_progress_task
from video_account_distiller.models import AccountCollectionRequest
from video_account_distiller.workflows.account_distill import _workflow_coverage


@pytest.mark.enable_socket
def test_progress_task_cooperatively_cancels_and_keeps_checkpoint(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite3")

    def worker(
        *,
        progress: Any,
        checkpoint: Any,
        resume_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        assert resume_state is None
        checkpoint("collection_complete", {"stage": "collection_complete"})
        for index in range(100):
            progress(index / 100, "media", f"video {index}")
            time.sleep(0.002)
        return {"ok": True}

    async def scenario() -> dict[str, Any]:
        submitted = enqueue_progress_task(
            store,
            worker,
            task_type="account_distill",
            task_metadata={"safe": True},
        )
        task_id = str(submitted["task_id"])
        for _ in range(100):
            current = store.get(task_id) or {}
            if current.get("checkpoint_stage") == "collection_complete":
                break
            await asyncio.sleep(0.002)
        store.request_cancel(task_id)
        for _ in range(100):
            current = store.get(task_id) or {}
            if current.get("status") == "cancelled":
                return current
            await asyncio.sleep(0.002)
        raise AssertionError("Task did not reach cancelled state")

    task = asyncio.run(scenario())

    assert task["status"] == "cancelled"
    assert task["checkpoint"] == {"stage": "collection_complete"}
    assert task["progress"] < 1.0


def test_workflow_coverage_reports_each_declared_layer() -> None:
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/demo",
        count=20,
        comments_per_video=10,
        comment_video_limit=20,
    )
    media_items = [
        {
            "media_analysis_id": f"media_{index}",
            "transcription": {"status": "complete"},
            "text_analysis_id": f"text_{index}",
            "vision_status": "success" if index < 16 else "degraded",
        }
        for index in range(18)
    ]
    result = {
        "account": {
            "follower_count_current": 1_000,
            "following_count_current": 12,
            "total_likes_current": 20_000,
            "video_count_current": None,
        },
        "collection": {
            "videos": 20,
            "metrics": 20,
            "comments": 180,
            "comment_videos": 18,
            "warnings": ["comment_collection_degraded:2"],
        },
        "coverage": {
            "videos": {"status": "requested_limit_reached"},
            "comments": {"status": "partial_degraded"},
        },
        "media_enrichment": {
            "enrichment": {
                "selected_count": 20,
                "completed_count": 18,
                "degraded_count": 1,
                "failed_count": 1,
                "videos": media_items,
                "warnings": ["transcript_coverage_incomplete"],
            }
        },
    }

    coverage = _workflow_coverage(
        result,
        request=request,
        media_limit=20,
        vision_requested=True,
    )

    assert coverage["status"] == "partial"
    assert coverage["account_snapshot"]["available_fields"] == 3
    assert coverage["videos"]["ratio"] == 1.0
    assert coverage["metrics"]["ratio"] == 1.0
    assert coverage["comments"]["ratio"] == 0.9
    assert coverage["media"]["ratio"] == 0.9
    assert coverage["transcripts"]["ratio"] == 0.9
    assert coverage["vision"]["success"] == 16
    assert coverage["vision"]["ratio"] == 0.8
