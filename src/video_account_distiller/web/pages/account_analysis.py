"""Streamlit page — 账号分析工作流."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

from video_account_distiller.web.ui import (
    badge,
    section_header,
    setup_page,
    stepper,
    task_progress_card,
)

st.set_page_config(
    page_title="账号分析 · Video Account Distiller",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="auto",
)


def _api(path: str, method: str = "GET", **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.request(method, f"{api_url}{path}", timeout=300, **kwargs)
        payload: Any = response.json()
        return payload if isinstance(payload, dict) else {"ok": False}
    except (requests.RequestException, ValueError):
        st.error(f"无法连接 API: {api_url}")
        return {"ok": False}


def _handle_action_response(response: dict[str, Any], *, label: str) -> None:
    """Render queued and synchronous action results without silent failures."""

    task_id = response.get("task_id")
    if isinstance(task_id, str) and task_id:
        st.session_state["last_task"] = task_id
        st.info(f"{label}任务已提交: {task_id}")
        return
    if response.get("ok") is True:
        st.session_state["last_action_result"] = response
        st.success(f"{label}完成 ✅")
        return
    error = response.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    st.error(f"{label}失败: {message or 'API 未返回可用结果'}")


def _run_action(
    path: str,
    *,
    label: str,
    method: str = "POST",
    **kwargs: Any,
) -> None:
    """Submit one analysis action with immediate, visible request feedback."""

    with st.status(f"正在请求{label}…", expanded=False) as activity:
        response = _api(path, method, **kwargs)
        succeeded = bool(response.get("task_id")) or response.get("ok") is True
        activity.update(
            label=f"{label}{'已提交' if succeeded else '请求失败'}",
            state="complete" if succeeded else "error",
            expanded=not succeeded,
        )
        _handle_action_response(response, label=label)


def _poll_task(task_id: str) -> dict[str, Any] | None:
    placeholder = st.empty()
    for _ in range(120):
        try:
            r = requests.get(f"{api_url}/api/tasks/{task_id}", timeout=10)
            data = r.json()
            status = data.get("status")
            progress = float(data.get("progress") or 0.0)
            stage = str(data.get("stage") or "正在准备")
            message = str(data.get("message") or f"任务状态：{status}")
            with placeholder.container():
                task_progress_card(
                    stage,
                    message,
                    progress=progress,
                    status=str(status),
                    meta=f"任务 {task_id} · 每 2 秒自动刷新",
                )
            if status == "completed":
                placeholder.success("✅ 任务完成")
                result = data.get("result")
                return result if isinstance(result, dict) else None
            elif status == "failed":
                error = data.get("error", {})
                placeholder.error(f"❌ 任务失败: {error.get('message', '未知错误')}")
                return None
        except Exception:
            pass
        time.sleep(2)
    placeholder.warning("⏰ 任务超时")
    return None


context = setup_page(
    "analysis",
    "账号分析",
    "按顺序完成账号定位、抽样报告、内容分析与策略提炼，每一步都有明确状态。",
    eyebrow="ACCOUNT WORKFLOW",
)
api_url = context.api_url
project_path = context.project_path
encoded_project = quote(project_path, safe="")

with st.container(border=True):
    input_columns = st.columns([1, 1, 0.55], vertical_alignment="bottom")
    with input_columns[0]:
        account_id = st.text_input(
            "账号 ID",
            placeholder="acc_xxx",
            key="analysis_account_id",
        )
    with input_columns[1]:
        video_id = st.text_input(
            "视频 ID",
            placeholder="vid_xxx（媒体分析时使用）",
            key="analysis_video_id",
        )
    with input_columns[2]:
        size = st.number_input(
            "样本大小",
            min_value=1,
            max_value=500,
            value=40,
        )
    if not account_id:
        st.caption("先输入已入库的账号 ID；涉及单条视频的操作还需要视频 ID。")
    else:
        st.markdown(
            badge("账号已就绪", "success"),
            unsafe_allow_html=True,
        )

stepper(
    ["输入目标", "抽样与报告", "内容分析", "提炼闭环", "任务状态"],
    active=2 if account_id else 1,
    completed=1 if account_id else 0,
)

section_header("分析流程", "从左到右执行；需要视频 ID 的操作会在按钮旁明确提示。")
workflow_columns = st.columns(3, gap="large")

with workflow_columns[0]:
    with st.container(border=True):
        st.markdown("#### 02 · 抽样与报告")
        st.caption("先建立代表性样本，再生成基于证据的账号报告。")
        st.markdown(
            badge("可开始" if account_id else "等待账号", "success" if account_id else "neutral"),
            unsafe_allow_html=True,
        )
        if st.button(
            "分层抽样",
            icon=":material/filter_alt:",
            use_container_width=True,
            disabled=not bool(account_id),
        ):
            _run_action(
                f"/api/projects/{encoded_project}/sample/{account_id}",
                label="分层抽样",
                json={"size": size},
            )
        if st.button(
            "生成分析报告",
            icon=":material/description:",
            use_container_width=True,
            disabled=not bool(account_id),
        ):
            _run_action(
                f"/api/projects/{encoded_project}/report/{account_id}",
                label="报告生成",
                json={"sample_size": size},
            )

with workflow_columns[1]:
    with st.container(border=True):
        st.markdown("#### 03 · 内容分析")
        st.caption("对视频画面、语音和评论意图进行结构化分析。")
        st.markdown(
            badge(
                "需要视频 ID" if not video_id else "视频已就绪",
                "warning" if not video_id else "success",
            ),
            unsafe_allow_html=True,
        )
        if st.button(
            "视频盲标注",
            icon=":material/subtitles:",
            use_container_width=True,
            disabled=not bool(video_id),
        ):
            _run_action(
                f"/api/projects/{encoded_project}/analyze/video/{video_id}",
                label="视频盲标注",
            )
        if st.button(
            "评论意图分析",
            icon=":material/forum:",
            use_container_width=True,
            disabled=not bool(account_id),
        ):
            _run_action(
                f"/api/projects/{encoded_project}/analyze/comments/{account_id}",
                label="评论意图分析",
            )
        if st.button(
            "媒体深度分析",
            icon=":material/movie:",
            use_container_width=True,
            disabled=not bool(video_id),
        ):
            _run_action(
                f"/api/projects/{encoded_project}/analyze/media/{video_id}",
                label="媒体分析",
            )

with workflow_columns[2]:
    with st.container(border=True):
        st.markdown("#### 04 · 提炼与闭环")
        st.caption("聚合指标、增长轨迹与分析上下文，形成可复用策略。")
        st.markdown(
            badge("可开始" if account_id else "等待账号", "success" if account_id else "neutral"),
            unsafe_allow_html=True,
        )
        if st.button(
            "账号提炼",
            icon=":material/psychology:",
            use_container_width=True,
            disabled=not bool(account_id),
        ):
            _run_action(
                f"/api/projects/{encoded_project}/distill/{account_id}",
                label="账号提炼",
            )
        if st.button(
            "计算指标",
            icon=":material/calculate:",
            use_container_width=True,
            disabled=not bool(account_id),
        ):
            _run_action(
                f"/api/projects/{encoded_project}/metrics/{account_id}",
                label="指标计算",
            )
        detail_actions = st.columns(2)
        if detail_actions[0].button(
            "增长轨迹",
            icon=":material/trending_up:",
            use_container_width=True,
            disabled=not bool(account_id),
        ):
            with st.status("正在读取账号增长轨迹…", expanded=False) as activity:
                growth = _api(f"/api/projects/{encoded_project}/accounts/{account_id}/growth")
                activity.update(
                    label="增长轨迹读取完成" if growth.get("ok") else "增长轨迹读取失败",
                    state="complete" if growth.get("ok") else "error",
                )
            st.session_state["last_growth"] = growth
        if detail_actions[1].button(
            "GPT 上下文",
            icon=":material/data_object:",
            use_container_width=True,
            disabled=not bool(account_id),
        ):
            with st.status("正在生成 GPT 分析上下文…", expanded=False) as activity:
                analysis_context = _api(
                    f"/api/projects/{encoded_project}/accounts/{account_id}/analysis-context"
                )
                activity.update(
                    label=(
                        "GPT 分析上下文已生成"
                        if analysis_context.get("ok")
                        else "GPT 分析上下文生成失败"
                    ),
                    state="complete" if analysis_context.get("ok") else "error",
                )
            st.session_state["last_analysis_context"] = analysis_context

if "last_growth" in st.session_state:
    with st.expander("📉 账号历史增长", expanded=True):
        st.json(st.session_state["last_growth"])

if "last_analysis_context" in st.session_state:
    with st.expander("🤖 GPT 分析上下文", expanded=True):
        st.caption("该上下文不含原始评论、签名视频地址、凭据或浏览器状态。")
        st.json(st.session_state["last_analysis_context"])

if "last_action_result" in st.session_state:
    with st.expander("✅ 最近同步操作结果", expanded=True):
        st.json(st.session_state["last_action_result"])

section_header("任务状态", "查看最近异步任务的执行阶段与结果。")

if "last_task" in st.session_state:
    task_id = st.session_state["last_task"]
    with st.container(border=True):
        status_columns = st.columns([3, 1], vertical_alignment="center")
        status_columns[0].markdown(f"**最近任务** `{task_id}`")
        if status_columns[1].button(
            "查询进度",
            type="primary",
            icon=":material/sync:",
            use_container_width=True,
        ):
            result = _poll_task(task_id)
            if result:
                st.json(result)
else:
    with st.container(border=True):
        st.caption("尚未提交分析任务。完成上方任一步骤后，任务状态会显示在这里。")
