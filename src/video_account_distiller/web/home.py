"""Video Account Distiller product dashboard."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
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
    page_title="工作台 · Video Account Distiller",
    page_icon=":material/space_dashboard:",
    layout="wide",
    initial_sidebar_state="expanded",
)

context = setup_page(
    "dashboard",
    "工作台",
    "集中查看采集进度、数据资产与分析产出，快速进入下一项运营工作。",
    eyebrow="OVERVIEW",
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
task_payload = _get(context.api_url, "/api/tasks?limit=100")
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
capabilities = doctor_data.get("capabilities") if isinstance(doctor_data, dict) else {}
capabilities = capabilities if isinstance(capabilities, dict) else {}

project_value = status.get("project")
project: dict[str, Any] = project_value if isinstance(project_value, dict) else {}
normalized_value = status.get("normalized")
normalized: dict[str, Any] = normalized_value if isinstance(normalized_value, dict) else {}
artifacts_value = status.get("artifacts")
artifacts: dict[str, Any] = artifacts_value if isinstance(artifacts_value, dict) else {}
accounts_value = status.get("accounts")
account_count = len(accounts_value) if isinstance(accounts_value, list) else 0

report_count = int(artifacts.get("reports", 0) or 0)
if report_count == 0:
    report_count = int(artifacts.get("account_distillations", 0) or 0)

metric_columns = st.columns(4)
with metric_columns[0]:
    metric_card(
        "采集账号总数",
        f"{account_count:,}",
        delta="当前项目已入库账号",
        tone="primary",
        delta_tone="neutral",
    )
with metric_columns[1]:
    metric_card(
        "采集视频总数",
        f"{int(normalized.get('videos', 0) or 0):,}",
        delta="标准化视频资产",
        tone="purple",
        delta_tone="neutral",
    )
with metric_columns[2]:
    metric_card(
        "分析评论总数",
        f"{int(normalized.get('comments', 0) or 0):,}",
        delta="可用于意图与需求分析",
        tone="green",
        delta_tone="neutral",
    )
with metric_columns[3]:
    metric_card(
        "生成报告总数",
        f"{report_count:,}",
        delta=f"GPT 分析 {int(artifacts.get('gpt_analyses', 0) or 0)} 份",
        tone="orange",
        delta_tone="neutral",
    )

section_header("业务概览", "最近任务、处理趋势与当前运行能力")
main_column, trend_column = st.columns([1.04, 0.96], gap="large")

with main_column:
    with st.container(border=True):
        title_column, status_column = st.columns([4, 1])
        with title_column:
            st.markdown('<div class="ds-mini-title">最近任务</div>', unsafe_allow_html=True)
            st.caption("后台任务会持续运行，可随时从采集任务或系统设置恢复查看。")
        with status_column:
            running_count = sum(
                1 for item in tasks if item.get("status") in {"pending", "running", "cancelling"}
            )
            st.markdown(
                badge(
                    f"{running_count} 个进行中",
                    "warning" if running_count else "success",
                ),
                unsafe_allow_html=True,
            )

        if tasks:
            rows: list[str] = []
            for item in tasks[:4]:
                status_name = str(item.get("status") or "pending")
                status_map = {
                    "completed": ("已完成", "success"),
                    "running": ("进行中", "warning"),
                    "pending": ("等待中", "neutral"),
                    "cancelling": ("取消中", "warning"),
                    "cancelled": ("已取消", "neutral"),
                    "failed": ("失败", "danger"),
                }
                label, tone = status_map.get(status_name, (status_name, "neutral"))
                task_type = str(item.get("task_type") or "分析任务")
                stage = str(item.get("stage") or "等待调度")
                updated = str(item.get("updated_at") or "")[:16].replace("T", " ")
                rows.append(
                    task_row(
                        task_type.replace("_", " ").title(),
                        f"{stage} · {updated or '刚刚更新'}",
                        status=label,
                        progress=float(item.get("progress", 0.0) or 0.0),
                        tone=tone,
                    )
                )
            st.markdown("".join(rows), unsafe_allow_html=True)
        else:
            empty_state("还没有任务记录", "从“采集任务”创建第一次账号蒸馏。", mark="+")

with trend_column:
    with st.container(border=True):
        st.markdown('<div class="ds-mini-title">近 7 日任务趋势</div>', unsafe_allow_html=True)
        st.caption("按任务更新时间统计，帮助判断团队的数据处理节奏。")
        today = date.today()
        dates = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
        completed_by_day: Counter[str] = Counter()
        active_by_day: Counter[str] = Counter()
        for item in tasks:
            updated_at = str(item.get("updated_at") or "")
            day_key = updated_at[:10]
            if not day_key:
                continue
            if item.get("status") == "completed":
                completed_by_day[day_key] += 1
            else:
                active_by_day[day_key] += 1
        chart_data = {
            "已完成": [completed_by_day[item.isoformat()] for item in dates],
            "其他状态": [active_by_day[item.isoformat()] for item in dates],
        }
        chart_colors: list[Any] = (
            ["#d8b65a", "#767b85"] if context.theme == "dark" else ["#5367f5", "#a8b1c7"]
        )
        st.line_chart(chart_data, color=chart_colors, height=255)
        st.caption(" · ".join(item.strftime("%m/%d") for item in dates))

section_header("快速开始", "把高频操作放到一次点击可达的位置")
quick_actions = st.columns(4)
quick_action_data = (
    (
        "pages/quick_collect.py",
        "新建采集任务",
        "从主页链接开始采集、理解与蒸馏",
        ":material/add_task:",
    ),
    (
        "pages/account_analysis.py",
        "账号分析",
        "按流程完成抽样、分析与提炼",
        ":material/monitoring:",
    ),
    (
        "pages/import_data.py",
        "导入数据",
        "接入公开数据或授权私域导出",
        ":material/upload_file:",
    ),
    (
        "pages/reports.py",
        "分析报告",
        "查看、导出并复用已有分析产出",
        ":material/description:",
    ),
)
for column, (path, label, description, icon) in zip(
    quick_actions,
    quick_action_data,
    strict=True,
):
    with column:
        with st.container(border=True):
            st.page_link(path, label=label, icon=icon, use_container_width=True)
            st.caption(description)

section_header("运行与产出", "检查本地能力、最近报告和下一步待办")
system_column, reports_column, todo_column = st.columns([0.9, 1.15, 0.95], gap="large")

with system_column:
    with st.container(border=True):
        st.markdown('<div class="ds-mini-title">运行能力</div>', unsafe_allow_html=True)
        st.caption("采集与本地模型能力来自当前项目的实时诊断。")
        capability_rows = (
            ("MediaCrawler", bool(capabilities.get("mediacrawler_douyin"))),
            ("视频处理", bool(capabilities.get("local_media"))),
            ("Whisper", bool(capabilities.get("video_transcription"))),
            ("Ollama 视觉", bool(capabilities.get("local_vision"))),
        )
        for label, ready in capability_rows:
            left, right = st.columns([2, 1])
            left.markdown(f"**{label}**")
            right.markdown(
                badge("可用" if ready else "待配置", "success" if ready else "warning"),
                unsafe_allow_html=True,
            )

with reports_column:
    with st.container(border=True):
        st.markdown('<div class="ds-mini-title">最近报告</div>', unsafe_allow_html=True)
        report_payload = (
            _get(context.api_url, f"/api/projects/{encoded_project}/reports/")
            if context.project_path
            else {}
        )
        report_paths_value = (
            report_payload.get("data", {}).get("reports", [])
            if isinstance(report_payload.get("data"), dict)
            else []
        )
        report_paths = (
            [item for item in report_paths_value if isinstance(item, str)]
            if isinstance(report_paths_value, list)
            else []
        )
        if report_paths:
            for report_path in report_paths[-3:][::-1]:
                parts = report_path.split("/")
                account_label = parts[2] if len(parts) > 2 else "未知账号"
                report_label = parts[3] if len(parts) > 3 else "最新报告"
                st.markdown(f"**{account_label}**")
                st.caption(f"{report_label} · 已生成")
        else:
            st.caption("暂无报告。完成一次蒸馏任务后，报告会显示在这里。")
        st.page_link(
            "pages/reports.py",
            label="进入报告中心",
            icon=":material/arrow_forward:",
            use_container_width=True,
        )

with todo_column:
    with st.container(border=True):
        st.markdown('<div class="ds-mini-title">待处理事项</div>', unsafe_allow_html=True)
        failed_count = sum(1 for item in tasks if item.get("status") == "failed")
        pending_count = sum(
            1 for item in tasks if item.get("status") in {"pending", "running", "cancelling"}
        )
        project_ready = bool(status.get("ok"))
        todo_items = [
            (
                "失败任务",
                f"{failed_count} 项需要检查",
                "danger" if failed_count else "success",
            ),
            (
                "运行队列",
                f"{pending_count} 项正在处理",
                "warning" if pending_count else "success",
            ),
            (
                "当前项目",
                str(project.get("name") or "尚未初始化"),
                "success" if project_ready else "warning",
            ),
        ]
        for label, value, tone in todo_items:
            st.markdown(f"**{label}**")
            st.markdown(badge(value, tone), unsafe_allow_html=True)

if st.button(
    "刷新工作台数据",
    icon=":material/refresh:",
    key="refresh_dashboard",
):
    _get.clear()
    st.rerun()

st.caption(f"最后刷新：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
