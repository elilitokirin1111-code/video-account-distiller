from __future__ import annotations

from pathlib import Path

import pytest

from video_account_distiller.features.providers import (
    ModelSchemaFailure,
    StructuredFileProvider,
)
from video_account_distiller.models import CommentIntent, CommentSignalAnnotation


def test_comment_provider_retries_then_exhausts_candidates(fixtures_dir: Path) -> None:
    provider = StructuredFileProvider(fixtures_dir / "phase4" / "comment-output-retry.json")
    with pytest.raises(ModelSchemaFailure):
        provider.generate_structured("prompt", CommentSignalAnnotation)

    annotation = provider.generate_structured("prompt", CommentSignalAnnotation)
    assert annotation.intent_labels == [CommentIntent.FOLLOW_UP]
    assert annotation.confidence == 0.91

    with pytest.raises(ModelSchemaFailure, match="No unused response candidate"):
        provider.generate_structured("prompt", CommentSignalAnnotation)
