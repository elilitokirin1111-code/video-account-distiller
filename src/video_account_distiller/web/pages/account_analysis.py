"""Streamlit page — 账号分析工作流."""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

st.set_page_config(page_title="账号分析", page_icon="🔬", layout="wide")

st.title("🔬 账号分析工作流")

api_url = st.sidebar.text_input(
    "API 地址",
    value=os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000"),
)
project_path = st.sidebar.text_input(
    "项目路径", value=str(st.session_state.get("project_path", ""))
)
encoded_project = quote(project_path, safe="")


def _api(path: str, method: str = "GET", **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.request(method, f"{api_url}{path}", timeout=300, **kwargs)
        payload: Any = response.json()
        return payload if isinstance(payload, dict) else {"ok": False}
    except (requests.RequestException, ValueError):
        st.error(f"无法连接 API: {api_url}")
        return {"ok": False}


def _poll_task(task_id: str) -> dict[str, Any] | None:
    placeholder = st.empty()
    for _ in range(120):
        try:
            r = requests.get(f"{api_url}/api/tasks/{task_id}", timeout=10)
            data = r.json()
            status = data.get("status")
            placeholder.caption(f"⏳ 任务状态: {status}...")
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


# ── 账号选择 ──────────────────────────────────────────────────────────
account_id = st.text_input("账号 ID", placeholder="acc_xxx")
video_id = st.text_input("视频 ID (媒体分析用)", placeholder="vid_xxx")

st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("📊 抽样 & 报告")
    size = st.number_input("样本大小", min_value=1, max_value=500, value=40)
    if st.button("🎯 分层抽样", use_container_width=True):
        r = _api(
            f"/api/projects/{encoded_project}/sample/{account_id}",
            "POST",
            json={"size": size},
        )
        if r.get("task_id"):
            st.session_state["last_task"] = r["task_id"]
            st.info(f"任务已提交: {r['task_id']}")
    if st.button("📄 生成报告", use_container_width=True):
        r = _api(
            f"/api/projects/{encoded_project}/report/{account_id}",
            "POST",
            json={"sample_size": size},
        )
        if r.get("task_id"):
            st.session_state["last_task"] = r["task_id"]
            st.info(f"任务已提交: {r['task_id']}")

with col2:
    st.subheader("🎬 内容分析")
    if st.button("🎙️ 视频盲标注", use_container_width=True):
        r = _api(
            f"/api/projects/{encoded_project}/analyze/video/{video_id}",
            "POST",
        )
        if r.get("task_id"):
            st.session_state["last_task"] = r["task_id"]
            st.info(f"任务已提交: {r['task_id']}")
    if st.button("💬 评论意图分析", use_container_width=True):
        r = _api(
            f"/api/projects/{encoded_project}/analyze/comments/{account_id}",
            "POST",
        )
        if r.get("task_id"):
            st.session_state["last_task"] = r["task_id"]
            st.info(f"任务已提交: {r['task_id']}")
    if st.button("📹 媒体分析", use_container_width=True):
        r = _api(
            f"/api/projects/{encoded_project}/analyze/media/{video_id}",
            "POST",
        )
        if r.get("task_id"):
            st.session_state["last_task"] = r["task_id"]
            st.info(f"任务已提交: {r['task_id']}")

with col3:
    st.subheader("🧠 提炼 & 闭环")
    if st.button("🏭 账号提炼", use_container_width=True):
        r = _api(
            f"/api/projects/{encoded_project}/distill/{account_id}",
            "POST",
        )
        if r.get("task_id"):
            st.session_state["last_task"] = r["task_id"]
            st.info(f"任务已提交: {r['task_id']}")
    if st.button("📈 计算指标", use_container_width=True):
        r = _api(
            f"/api/projects/{encoded_project}/metrics/{account_id}",
            "POST",
        )
        if r.get("task_id"):
            st.session_state["last_task"] = r["task_id"]
            st.info(f"任务已提交: {r['task_id']}")
    if st.button("📉 查看账号增长", use_container_width=True):
        growth = _api(f"/api/projects/{encoded_project}/accounts/{account_id}/growth")
        st.session_state["last_growth"] = growth
    if st.button("🤖 生成 GPT 上下文", use_container_width=True):
        context = _api(f"/api/projects/{encoded_project}/accounts/{account_id}/analysis-context")
        st.session_state["last_analysis_context"] = context

if "last_growth" in st.session_state:
    with st.expander("📉 账号历史增长", expanded=True):
        st.json(st.session_state["last_growth"])

if "last_analysis_context" in st.session_state:
    with st.expander("🤖 GPT 分析上下文", expanded=True):
        st.caption("该上下文不含原始评论、签名视频地址、凭据或浏览器状态。")
        st.json(st.session_state["last_analysis_context"])

# ── 任务追踪 ──────────────────────────────────────────────────────────
st.divider()
st.subheader("🔄 任务状态")

if "last_task" in st.session_state:
    task_id = st.session_state["last_task"]
    if st.button(f"📡 查询任务 {task_id[:16]}...", type="primary"):
        result = _poll_task(task_id)
        if result:
            st.json(result)
    st.caption(f"最近任务: {task_id}")
