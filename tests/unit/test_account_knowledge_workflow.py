"""Regression coverage for the mutually exclusive account knowledge workflow."""

from __future__ import annotations

from typing import Any, cast

import pytest

from video_account_distiller.collection import CollectionProfile
from video_account_distiller.collection.providers import AccountCollectionProvider
from video_account_distiller.models import AccountCollectionRequest, CollectionProviderKind
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.workflows.account_distill import AccountDistillWorkflow


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
                "videos": [],
            },
        }

    def _knowledge(self: Any, **kwargs: Any) -> dict[str, Any]:
        del self
        observed["knowledge_account_id"] = kwargs["account_id"]
        return {
            "ok": True,
            "manifest": {
                "documents": [{"video_id": "vid_knowledge"}],
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
    assert result["workflow"]["distillation_mode"] == "knowledge"
    assert result["workflow"]["operational_analysis_run"] is False
    assert result["workflow"]["knowledge_documents"] == 1
    assert "distill" not in stages
    assert "report" not in stages
    assert "narrative" not in stages
    assert "video_knowledge" in stages
