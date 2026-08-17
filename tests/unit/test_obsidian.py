from __future__ import annotations

from video_account_distiller.knowledge.obsidian import _legacy_report_zh


def test_legacy_report_translation_preserves_markdown_structure() -> None:
    source = (
        "# 账号体检报告\n\n"
        "- 数据范围\n"
        "  分类：fact\n\n"
        "| 字段 | 值 |\n"
        "| --- | --- |\n"
        "| 粉丝 | 100 |\n"
        "| 获赞 | 200 |\n"
    )

    translated = _legacy_report_zh(source)

    assert "# 账号体检报告\n\n- 数据范围" in translated
    assert "  分类：fact" in translated
    assert "| 字段 | 值 |\n| --- | --- |\n| 粉丝 | 100 |" in translated
