"""Pure loading-state markup helpers for the Streamlit product shell."""

from __future__ import annotations

import html


def task_progress_markup(
    title: str,
    detail: str,
    *,
    progress: float,
    status: str,
    meta: str,
) -> str:
    """Build escaped, accessible markup for a live task progress card."""

    progress_value = max(0.0, min(float(progress), 1.0))
    active = status in {"pending", "running", "cancelling"}
    indeterminate = active and progress_value <= 0.0
    percent = "等待中" if indeterminate else f"{progress_value:.0%}"
    return f"""
    <div class="ds-live-task {"active" if active else ""}" role="status" aria-live="polite">
      <div class="ds-live-orbit" aria-hidden="true"><span class="ds-live-core"></span></div>
      <div class="ds-live-content">
        <div class="ds-live-title">{html.escape(title)}</div>
        <div class="ds-live-detail" title="{html.escape(detail)}">{html.escape(detail)}</div>
        <div class="ds-live-meta">{html.escape(meta)}</div>
      </div>
      <div class="ds-live-percent">{percent}</div>
      <div class="ds-live-track {"indeterminate" if indeterminate else ""}" aria-hidden="true">
        <span style="width:{progress_value:.1%}"></span>
      </div>
    </div>
    """
