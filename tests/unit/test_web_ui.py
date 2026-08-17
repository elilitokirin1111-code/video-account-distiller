from __future__ import annotations

from video_account_distiller.web.loading import task_progress_markup


def test_task_progress_card_renders_indeterminate_accessible_loading_state() -> None:
    markup = task_progress_markup(
        "等待模型 <响应>",
        "正在连接 & 校验",
        progress=0.0,
        status="pending",
        meta="每 2 秒自动刷新",
    )

    assert 'class="ds-live-task active"' in markup
    assert 'role="status"' in markup
    assert 'aria-live="polite"' in markup
    assert 'class="ds-live-track indeterminate"' in markup
    assert "等待中" in markup
    assert "等待模型 &lt;响应&gt;" in markup
    assert "正在连接 &amp; 校验" in markup


def test_task_progress_card_clamps_completed_progress() -> None:
    markup = task_progress_markup(
        "全部完成",
        "结果已经保存",
        progress=1.4,
        status="completed",
        meta="已保存",
    )

    assert 'class="ds-live-task "' in markup
    assert 'class="ds-live-track "' in markup
    assert "width:100.0%" in markup
    assert ">100%</div>" in markup
    assert "已保存" in markup
