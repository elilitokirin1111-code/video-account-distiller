"""Focused product overview for the local account-distillation workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

from video_account_distiller.web.ui import (
    badge,
    empty_state,
    metric_card,
    section_header,
    setup_page,
    task_row,
)

st.set_page_config(
    page_title="概览 · Distiller",
    page_icon=":material/blur_on:",
    layout="wide",
    initial_sidebar_state="auto",
)

context = setup_page(
    "dashboard",
    "账号蒸馏",
    "从一个主页链接开始，得到视频内容理解、账号洞察、长文报告和可复用知识库。",
    eyebrow="本地优先 · 可审计",
)


@st.cache_data(ttl=20, show_spinner=False)
def _get(api_url: str, path: str, *, timeout: int = 8) -> dict[str, Any]:
    try:
        response = requests.get(f"{api_url}{path}", timeout=timeout)
        payload: Any = response.json()
        return payload if isinstance(payload, dict) else {}
    except (requests.RequestException, ValueError):
        return {}


encoded_project = quote(context.project_path, safe="")
status = (
    _get(context.api_url, f"/api/projects/{encoded_project}/status") if context.project_path else {}
)
task_payload = _get(context.api_url, "/api/tasks?limit=20")
tasks_value = task_payload.get("tasks")
tasks: list[dict[str, Any]] = (
    [item for item in tasks_value if isinstance(item, dict)]
    if isinstance(tasks_value, list)
    else []
)
doctor = (
    _get(context.api_url, f"/api/doctor/{encoded_project}", timeout=12)
    if context.project_path
    else {}
)
doctor_data = doctor.get("data") if isinstance(doctor.get("data"), dict) else {}
capabilities_value = doctor_data.get("capabilities") if isinstance(doctor_data, dict) else {}
capabilities = capabilities_value if isinstance(capabilities_value, dict) else {}

normalized_value = status.get("normalized")
normalized: dict[str, Any] = normalized_value if isinstance(normalized_value, dict) else {}
artifacts_value = status.get("artifacts")
artifacts: dict[str, Any] = artifacts_value if isinstance(artifacts_value, dict) else {}
accounts_value = status.get("accounts")
account_count = len(accounts_value) if isinstance(accounts_value, list) else 0
report_count = int(artifacts.get("reports", 0) or artifacts.get("account_distillations", 0) or 0)
running_count = sum(
    1 for item in tasks if item.get("status") in {"pending", "running", "cancelling"}
)
failed_count = sum(1 for item in tasks if item.get("status") == "failed")

st.markdown(
    f"""
    <div class="ds-hero">
      <div class="ds-hero-eyebrow">从主页到知识，只保留一条主路径</div>
      <div class="ds-hero-title">粘贴抖音主页，自动理解最近作品并生成完整账号报告。</div>
      <div class="ds-hero-copy">
        采集互动数据、解析画面与语音、总结内容方法，并将结果保存到本地项目。
        云端模型和知识库同步始终由你显式选择。
      </div>
      <div class="ds-hero-meta">
        <span>本地优先</span><span>GPU 转写</span><span>最多 100 条内容分析</span>
        <span>{running_count} 个任务运行中</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

primary_action, secondary_action, action_spacer = st.columns([1.25, 1, 3.2])
with primary_action:
    st.page_link(
        "pages/quick_collect.py",
        label="开始新的账号蒸馏",
        icon=":material/play_circle:",
        use_container_width=True,
    )
with secondary_action:
    st.page_link(
        "pages/reports.py",
        label="查看已有报告",
        icon=":material/article:",
        use_container_width=True,
    )
del action_spacer

metric_columns = st.columns(3)
with metric_columns[0]:
    metric_card(
        "已蒸馏账号",
        f"{account_count:,}",
        delta="当前工作区",
        tone="primary",
        delta_tone="neutral",
    )
with metric_columns[1]:
    metric_card(
        "内容资产",
        f"{int(normalized.get('videos', 0) or 0):,}",
        delta="已标准化视频",
        tone="purple",
        delta_tone="neutral",
    )
with metric_columns[2]:
    metric_card(
        "可读报告",
        f"{report_count:,}",
        delta="长文分析与账号体检",
        tone="green",
        delta_tone="neutral",
    )

section_header("最近进展", "只显示需要继续处理或最近完成的工作")
task_column, output_column = st.columns([1.22, 0.78], gap="large")

with task_column:
    with st.container(border=True):
        title_column, state_column = st.columns([3, 1])
        title_column.markdown('<div class="ds-mini-title">任务</div>', unsafe_allow_html=True)
        state_column.markdown(
            badge(
                f"{running_count} 个运行中",
                "warning" if running_count else "success",
            ),
            unsafe_allow_html=True,
        )
        if tasks:
            rows: list[str] = []
            for item in tasks[:5]:
                status_name = str(item.get("status") or "pending")
                status_map = {
                    "completed": ("已完成", "success"),
                    "running": ("进行中", "warning"),
                    "pending": ("等待中", "neutral"),
                    "cancelling": ("取消中", "warning"),
                    "cancelled": ("已取消", "neutral"),
                    "failed": ("需处理", "danger"),
                }
                label, tone = status_map.get(status_name, (status_name, "neutral"))
                task_type = str(item.get("task_type") or "分析任务")
                type_name = {
                    "account_distill": "账号蒸馏",
                    "gpt_account_analysis": "云端深度分析",
                }.get(task_type, task_type.replace("_", " ").title())
                stage = str(item.get("stage") or "等待调度")
                updated = str(item.get("updated_at") or "")[:16].replace("T", " ")
                rows.append(
                    task_row(
                        type_name,
                        f"{stage} · {updated or '刚刚更新'}",
                        status=label,
                        progress=float(item.get("progress", 0.0) or 0.0),
                        tone=tone,
                    )
                )
            st.markdown("".join(rows), unsafe_allow_html=True)
        else:
            empty_state("还没有任务", "从一个主页链接开始第一次账号蒸馏。", mark="+")
        st.page_link(
            "pages/quick_collect.py",
            label="查看任务与恢复进度",
            icon=":material/arrow_forward:",
            use_container_width=True,
        )

with output_column:
    with st.container(border=True):
        st.markdown('<div class="ds-mini-title">运行就绪度</div>', unsafe_allow_html=True)
        readiness = (
            ("主页采集", bool(capabilities.get("mediacrawler_douyin"))),
            ("视频处理", bool(capabilities.get("local_media"))),
            ("GPU 转写", bool(capabilities.get("video_transcription"))),
            ("画面理解", bool(capabilities.get("local_vision"))),
        )
        for label, ready in readiness:
            left, right = st.columns([2, 1])
            left.markdown(f"**{label}**")
            right.markdown(
                badge("可用" if ready else "待配置", "success" if ready else "warning"),
                unsafe_allow_html=True,
            )
        st.markdown(
            f"""
            <div class="ds-runtime-strip">
              <span>失败任务</span><strong>{failed_count}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.page_link(
            "pages/settings.py",
            label="检查连接与模型设置",
            icon=":material/settings:",
            use_container_width=True,
        )

refresh_column, timestamp_column = st.columns([1, 4], vertical_alignment="center")
with refresh_column:
    if st.button("刷新", icon=":material/refresh:", key="refresh_dashboard"):
        _get.clear()
        st.rerun()
with timestamp_column:
    st.caption(f"数据刷新于 {datetime.now().strftime('%H:%M')}")
