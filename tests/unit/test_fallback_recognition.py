from __future__ import annotations

from video_account_distiller.comments.pipeline import _fallback_annotation
from video_account_distiller.features.pipeline import _fallback_semantics
from video_account_distiller.models import (
    BlindVideoBundle,
    CommentIntent,
    CtaType,
    HookType,
    TranscriptInputSegment,
)


def _bundle(*, title: str | None, text: str) -> BlindVideoBundle:
    return BlindVideoBundle(
        video_id="vid_test",
        platform="douyin",
        title=title,
        duration_seconds=12,
        transcript_segments=[
            TranscriptInputSegment(
                segment_id="seg_1",
                start_ms=0,
                end_ms=12_000,
                text=text,
            )
        ],
    )


def test_video_fallback_uses_title_when_transcript_is_unusable() -> None:
    semantics = _fallback_semantics(
        _bundle(
            title="你相信命运的安排吗？#猫咪 #德文猫",
            text="嗯然后这个就是那个",
        )
    )

    assert semantics.primary_pillar == "宠物与陪伴"
    assert semantics.hook.primary_type == HookType.QUESTION_CHALLENGE
    assert semantics.hook.hook_text == "你相信命运的安排吗？#猫咪 #德文猫"
    assert semantics.primary_pillar_evidence_segment_ids == []
    assert semantics.hook.evidence_segment_ids == []
    assert "metadata_only_semantic_label_requires_review" in semantics.risk_flags
    assert "content pillar" not in semantics.unknowns


def test_video_fallback_does_not_force_a_label_without_a_signal() -> None:
    semantics = _fallback_semantics(_bundle(title="今天的记录", text="嗯然后继续"))

    assert semantics.primary_pillar == "unknown"
    assert semantics.hook.primary_type == HookType.UNKNOWN
    assert "content pillar" in semantics.unknowns


def test_video_fallback_finds_implicit_comment_cta_before_the_final_segment() -> None:
    bundle = BlindVideoBundle(
        video_id="vid_test",
        platform="douyin",
        title="酒店服务复盘",
        duration_seconds=20,
        transcript_segments=[
            TranscriptInputSegment(
                segment_id="seg_1",
                start_ms=0,
                end_ms=10_000,
                text="遇到这种客诉你会怎么处理？告诉我你的做法。",
            ),
            TranscriptInputSegment(
                segment_id="seg_2",
                start_ms=10_000,
                end_ms=20_000,
                text="今天就复盘到这里。",
            ),
        ],
    )

    semantics = _fallback_semantics(bundle)

    assert semantics.cta.primary_type == CtaType.COMMENT
    assert semantics.cta.evidence_segment_ids == ["seg_1"]
    assert semantics.structure_segments[-1].function.value == "cta"
    assert semantics.structure_segments[-1].evidence_segment_ids == ["seg_1"]


def test_comment_fallback_recognizes_experience_and_industry_identity() -> None:
    annotation = _fallback_annotation("我毕业实习在丽思卡尔顿，同行看这个很有感触")

    assert CommentIntent.SHARE_EXPERIENCE in annotation.intent_labels
    assert CommentIntent.IDENTITY_SIGNAL in annotation.intent_labels


def test_comment_fallback_recognizes_actionable_suggestions() -> None:
    annotation = _fallback_annotation("建议可以换个高速吹风机，下次记得把牵引绳带上")

    assert CommentIntent.SUGGESTION in annotation.intent_labels
    assert annotation.content_opportunities == ["整理用户提出的具体改进建议并逐项回应"]


def test_comment_fallback_keeps_ambiguous_text_unknown() -> None:
    annotation = _fallback_annotation("路过")

    assert annotation.intent_labels == [CommentIntent.UNKNOWN]
