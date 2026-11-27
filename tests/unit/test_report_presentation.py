from __future__ import annotations

from video_account_distiller.report_presentation import (
    display_label,
    display_text,
    display_warning,
)


def test_report_labels_translate_machine_enums_without_changing_machine_value() -> None:
    raw_status = "degraded"

    assert display_label(raw_status) == "部分环节未完成（已保留有效结果）"
    assert raw_status == "degraded"
    assert display_label("insufficient") == "当前样本不足"
    assert display_label("visual_craft") == "镜头与画面"
    assert display_label("model_inference") == "模型推断"
    assert display_label(True) == "是"
    assert display_label(False) == "否"
    assert display_label("cloud") == "云端模型"
    assert display_label("ollama") == "Ollama 本地模型"
    assert display_label("llamacpp") == "llama.cpp 本地模型"
    assert display_label("S") == "S 档"
    assert display_label("pass") == "通过"
    assert display_label("schema_invalid") == "数据结构校验失败"


def test_report_text_localizes_known_codes_inside_free_text() -> None:
    text = "classification=observed_fact; confidence=low; status=degraded; hook + cta"

    localized = display_text(text)

    assert localized == (
        "分类=已观察事实; 置信度=低; 状态=部分环节未完成（已保留有效结果）; 开场钩子 + 行动引导"
    )
    assert display_text("svd_unknownabc") == "svd_unknownabc"
    assert display_text("Phase 2 content_type / DerivedMetrics = null") == (
        "第二阶段 内容类型字段 / 派生表现指标 = 缺失"
    )
    assert display_text("robust_outlier_excluded") == "已排除稳健统计识别的异常视频"
    assert display_text(
        "证据：craft_summary.average_shot_duration_ms, shot_annotations, "
        "audio.has_audio；decode_failed"
    ) == ("证据：拍摄摘要中的平均镜头时长, 镜头标注, 音频分析中的音轨状态；音频解码失败")


def test_report_warning_explains_known_codes_and_hides_raw_provider_errors() -> None:
    known = display_warning("deep_model_unavailable_deterministic_fallback")
    quota = display_warning("HTTP 429: insufficient_quota: Free quota exhausted")
    unexpected = display_warning("unexpected provider failure")

    assert "深度模型未成功启用" in known
    assert "额度不足" in quota
    assert "insufficient_quota" not in quota
    assert "此前已为该视频导入" in display_warning(
        "Transcript hash already imported for this video."
    )
    assert unexpected == (
        "处理过程中出现技术异常，系统已保留可用结果；请打开任务详情查看原因并重试。"
    )
