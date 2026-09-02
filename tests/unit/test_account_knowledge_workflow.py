"""Regression coverage for the mutually exclusive account knowledge workflow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from video_account_distiller.collection import CollectionProfile
from video_account_distiller.collection.providers import AccountCollectionProvider
from video_account_distiller.models import AccountCollectionRequest, CollectionProviderKind
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.workflows.account_distill import (
    AccountDistillWorkflow,
    _distill_account_creative_cards,
    _select_video_distillation_targets,
    _summarize_video_distillation,
)


class _Transcriber:
    provider_name = "fixture"
    model_name = "fixture"
    available = True
    diagnostics: dict[str, Any] = {}


def test_account_knowledge_mode_never_runs_operational_distillation(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def _collect(self: Any, **kwargs: Any) -> dict[str, Any]:
        del self
        observed["include_operational_analysis"] = kwargs["include_operational_analysis"]
        return {
            "ok": True,
            "account": {"account_id": "acc_knowledge"},
            "collection": {"videos": 1, "metrics": 1, "comments": 0},
            "coverage": {},
        }

    def _enrich(self: Any, **kwargs: Any) -> dict[str, Any]:
        del self, kwargs
        return {
            "ok": True,
            "enrichment": {
                "selected_count": 1,
                "completed_count": 1,
                "degraded_count": 0,
                "failed_count": 0,
                "videos": [
                    {
                        "video_id": "vid_knowledge",
                        "status": "complete",
                        "text_analysis_id": "ana_knowledge",
                    }
                ],
            },
        }

    def _knowledge(self: Any, **kwargs: Any) -> dict[str, Any]:
        del self
        observed["knowledge_account_id"] = kwargs["account_id"]
        observed["knowledge_video_ids"] = kwargs["video_ids"]
        return {
            "ok": True,
            "manifest": {
                "status": "complete",
                "requested_count": 1,
                "completed_count": 1,
                "degraded_count": 0,
                "documents": [{"video_id": "vid_knowledge", "status": "complete"}],
                "skipped_count": 0,
            },
            "outputs": ["knowledge/accounts/acc_knowledge/video-knowledge/avk_test/manifest.json"],
        }

    def _unexpected(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("operational account analysis must not run in knowledge mode")

    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.build_local_transcriber",
        lambda **kwargs: _Transcriber(),
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AccountCollectionService.analyze_url",
        _collect,
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AccountMediaEnrichmentService.enrich",
        _enrich,
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AccountVideoKnowledgeService.distill",
        _knowledge,
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AccountDistillationService.distill",
        _unexpected,
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.ReportService.generate_account_health",
        _unexpected,
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.NarrativeReportService.generate",
        _unexpected,
    )

    stages: list[str] = []
    workflow = AccountDistillWorkflow(
        project,
        cast(AccountCollectionProvider, object()),
    )
    result = workflow.run(
        request=AccountCollectionRequest(
            profile_url="https://www.douyin.com/user/knowledge",
            provider=CollectionProviderKind.MEDIACRAWLER,
            count=1,
            comments_per_video=0,
            comment_video_limit=1,
        ),
        collection_profile=CollectionProfile.STANDARD,
        media_limit=1,
        vision_provider=None,
        distillation_mode="knowledge",
        video_knowledge_provider="none",
        progress=lambda progress, stage, message: stages.append(stage),
    )

    assert observed["include_operational_analysis"] is False
    assert observed["knowledge_account_id"] == "acc_knowledge"
    assert observed["knowledge_video_ids"] == ["vid_knowledge"]
    assert result["workflow"]["distillation_mode"] == "knowledge"
    assert result["workflow"]["status"] == "complete"
    assert result["workflow"]["operational_analysis_run"] is False
    assert result["workflow"]["knowledge_documents"] == 1
    assert "distill" not in stages
    assert "report" not in stages
    assert "narrative" not in stages
    assert "video_knowledge" in stages


def test_complete_creative_mode_runs_video_and_account_distillation(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []
    selected_video_ids: dict[str, list[str]] = {}

    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.build_local_transcriber",
        lambda **kwargs: _Transcriber(),
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AccountCollectionService.analyze_url",
        lambda self, **kwargs: {
            "ok": True,
            "account": {"account_id": "acc_full"},
            "collection": {"videos": 1, "metrics": 1, "comments": 1},
            "coverage": {},
        },
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AccountMediaEnrichmentService.enrich",
        lambda self, **kwargs: {
            "ok": True,
            "enrichment": {
                "selected_count": 1,
                "completed_count": 1,
                "degraded_count": 0,
                "failed_count": 0,
                "videos": [
                    {
                        "video_id": "vid_full",
                        "status": "complete",
                        "text_analysis_id": "ana_full",
                    }
                ],
            },
        },
    )

    def _knowledge(self: Any, **kwargs: Any) -> dict[str, Any]:
        del self
        selected_video_ids["knowledge"] = kwargs["video_ids"]
        return {
            "ok": True,
            "manifest": {
                "status": "degraded",
                "requested_count": 1,
                "completed_count": 0,
                "degraded_count": 1,
                "documents": [{"video_id": "vid_full", "status": "degraded"}],
                "skipped_count": 0,
            },
            "outputs": [],
        }

    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AccountVideoKnowledgeService.distill",
        _knowledge,
    )

    def _creative(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args
        observed.append("video_creative")
        selected_video_ids["creative"] = kwargs["video_ids"]
        return {
            "ok": True,
            "status": "degraded",
            "requested_count": 1,
            "completed_count": 0,
            "degraded_count": 1,
            "skipped_count": 0,
            "cards": [
                {
                    "video_id": "vid_full",
                    "distillation_id": "svd_full",
                    "status": "degraded",
                    "report_path": "analyses/videos/vid_full/svd_full/report.md",
                }
            ],
            "skipped": [],
        }

    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill._distill_account_creative_cards",
        _creative,
    )

    def _account_distill(self: Any, **kwargs: Any) -> dict[str, Any]:
        del self, kwargs
        observed.append("account_distill")
        return {}

    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AccountDistillationService.distill",
        _account_distill,
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.ReportService.generate_account_health",
        lambda self, **kwargs: {},
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AccountBenchmarkProfileService.build",
        lambda self, **kwargs: {},
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.AnalysisContextService.build",
        lambda self, **kwargs: {},
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.NarrativeReportService.generate",
        lambda self, **kwargs: {},
    )

    progress_events: list[tuple[str, str]] = []
    progress_values: list[float] = []

    def record_progress(progress: float, stage: str, message: str) -> None:
        progress_values.append(progress)
        progress_events.append((stage, message))

    result = AccountDistillWorkflow(project, cast(AccountCollectionProvider, object())).run(
        request=AccountCollectionRequest(
            profile_url="https://www.douyin.com/user/full",
            provider=CollectionProviderKind.MEDIACRAWLER,
            count=1,
            comments_per_video=1,
            comment_video_limit=1,
        ),
        collection_profile=CollectionProfile.STANDARD,
        media_limit=1,
        vision_provider=None,
        distillation_mode="creative_learning",
        distill_video_knowledge=True,
        video_knowledge_provider="none",
        export_knowledge=False,
        progress=record_progress,
    )

    assert observed == ["video_creative", "account_distill"]
    assert selected_video_ids == {
        "knowledge": ["vid_full"],
        "creative": ["vid_full"],
    }
    assert result["workflow"]["distillation_mode"] == "creative_learning"
    assert result["workflow"]["status"] == "degraded"
    assert result["workflow"]["knowledge_status"] == "account_distilled_with_video_batch_warnings"
    assert result["workflow"]["video_knowledge_exported"] is True
    assert result["workflow"]["video_creative_cards"] == 1
    assert result["video_creative_card_index"]["cards"][0]["distillation_id"] == "svd_full"
    stages = [stage for stage, _ in progress_events]
    assert stages.index("video_knowledge") < stages.index("distill")
    assert "video_creative_distillation" not in stages  # helper is stubbed in this test
    assert "降级" in progress_events[-1][1]
    assert progress_values == sorted(progress_values)


def test_creative_card_batch_uses_every_video_with_text_analysis(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    videos = [
        SimpleNamespace(account_id="acc", video_id="vid_a", title="视频 A"),
        SimpleNamespace(account_id="acc", video_id="vid_b", title="视频 B"),
        SimpleNamespace(account_id="other", video_id="vid_other", title="其他"),
    ]
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.read_models",
        lambda path, model: videos,
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill._latest_text_analysis",
        lambda project, video_id: object() if video_id == "vid_a" else None,
    )

    class _Service:
        def distill(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["video_id"] == "vid_a"
            return {
                "distillation": {
                    "distillation_id": "svd_a",
                    "status": "complete",
                    "warnings": [],
                },
                "outputs": ["analyses/videos/vid_a/svd_a/report.md"],
            }

    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.SingleVideoDistillationService",
        lambda project: _Service(),
    )
    stages: list[str] = []
    result = _distill_account_creative_cards(
        project,
        account_id="acc",
        video_ids=["vid_a", "vid_b"],
        provider="cloud",
        model="deepseek-v4-flash",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test",
        strict_model=True,
        progress=lambda progress, stage, message: stages.append(stage),
    )

    assert result["requested_count"] == 2
    assert result["eligible_count"] == 1
    assert result["completed_count"] == 1
    assert result["skipped_count"] == 1
    assert result["cards"][0]["report_path"].endswith("report.md")
    assert stages == ["video_creative_distillation"]


def test_video_distillation_targets_use_current_media_selection(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.read_models",
        lambda path, model: [
            SimpleNamespace(account_id="acc", video_id="vid_old"),
        ],
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill._latest_text_analysis",
        lambda project, video_id: object() if video_id == "vid_old" else None,
    )

    targets = _select_video_distillation_targets(
        project,
        account_id="acc",
        limit=3,
        media_enrichment={
            "enrichment": {
                "videos": [
                    {
                        "video_id": "vid_current",
                        "status": "degraded",
                        "text_analysis_id": "ana_current",
                    },
                    {
                        "video_id": "vid_failed",
                        "status": "failed",
                        "text_analysis_id": "ana_failed",
                    },
                ]
            }
        },
    )

    assert targets["source"] == "current_media_enrichment"
    assert targets["video_ids"] == ["vid_current"]


def test_video_distillation_target_fallback_filters_before_limit(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    videos = [
        SimpleNamespace(account_id="acc", video_id="a_without_analysis"),
        SimpleNamespace(account_id="acc", video_id="b_eligible"),
        SimpleNamespace(account_id="acc", video_id="c_eligible"),
    ]
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill.read_models",
        lambda path, model: videos,
    )
    monkeypatch.setattr(
        "video_account_distiller.workflows.account_distill._latest_text_analysis",
        lambda project, video_id: object() if video_id.endswith("eligible") else None,
    )

    targets = _select_video_distillation_targets(
        project,
        account_id="acc",
        limit=1,
        media_enrichment={"enrichment": {"selected_count": 1}},
    )

    assert targets["source"] == "existing_text_analysis_fallback"
    assert targets["eligible_before_limit"] == 2
    assert targets["video_ids"] == ["b_eligible"]


def test_video_distillation_summary_uses_counts_not_optimistic_status() -> None:
    summary = _summarize_video_distillation(
        target_video_ids=["vid_a"],
        knowledge_result={
            "manifest": {
                "status": "complete",
                "requested_count": 1,
                "completed_count": 0,
                "degraded_count": 0,
                "skipped_count": 1,
                "documents": [],
            }
        },
        creative_result={
            "status": "complete",
            "requested_count": 1,
            "completed_count": 0,
            "degraded_count": 0,
            "skipped_count": 1,
            "cards": [],
        },
    )

    assert summary["status"] == "degraded"
    assert summary["knowledge"]["status"] == "degraded"
    assert summary["creative"]["status"] == "degraded"
