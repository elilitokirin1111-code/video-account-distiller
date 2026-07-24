"""Streamlit home page — project dashboard."""

from __future__ import annotations

import os
from pathlib import Path

import requests
import streamlit as st

API_URL = os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000")

st.set_page_config(
    page_title="Video Account Distiller",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Video Account Distiller")
st.caption("基于证据的视频账号分析平台")

# ── Sidebar: Project Selection ───────────────────────────────────────

st.sidebar.header("⚙️ 项目配置")

project_path = st.sidebar.text_input(
    "项目路径",
    value=str(Path.home() / "distiller-demo"),
    help="Distiller 项目的绝对路径",
)

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("🔧 初始化项目", use_container_width=True):
        try:
            r = requests.post(
                f"{API_URL}/api/projects/init",
                json={"path": project_path, "name": Path(project_path).name},
            )
            data = r.json()
            if data.get("ok"):
                st.success("项目已就绪 ✅")
            else:
                st.error(data.get("detail", "初始化失败"))
        except requests.ConnectionError:
            st.error("无法连接到 API 服务，请先启动 `distiller-api`")

with col2:
    if st.button("🩺 系统诊断", use_container_width=True):
        try:
            r = requests.get(f"{API_URL}/api/doctor/{project_path}")
            if r.status_code == 200:
                data = r.json()["data"]
                st.session_state["doctor"] = data
        except requests.ConnectionError:
            st.error("API 未连接")

st.sidebar.divider()
st.sidebar.caption("📌 确保 API 服务已启动：`uv run distiller-api`")

# ── Main Content ──────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["📋 项目状态", "📦 数据概览", "📈 分析产出"])

with tab1:
    st.subheader("项目状态")
    if st.button("🔄 刷新状态"):
        try:
            r = requests.get(f"{API_URL}/api/projects/{project_path}/status")
            if r.status_code == 200:
                st.session_state["status"] = r.json()
        except requests.ConnectionError:
            st.error("无法连接到 API")

    status = st.session_state.get("status", {})
    if status.get("ok"):
        project = status.get("project", {})
        meta_col1, meta_col2, meta_col3 = st.columns(3)
        with meta_col1:
            st.metric("项目名称", project.get("name", "-"))
        with meta_col2:
            st.metric("导入次数", status.get("imports", {}).get("count", 0))
        with meta_col3:
            st.metric("视频数量", status.get("normalized", {}).get("videos", 0))

        st.divider()
        st.caption(f"项目 ID: {project.get('id', '-')}")
        st.caption(f"创建时间: {project.get('created_at', '-')}")
        st.caption(f"最近更新: {project.get('updated_at', '-')}")

        # Artifact counts
        artifacts = status.get("artifacts", {})
        if artifacts:
            st.subheader("分析产出")
            art_col1, art_col2, art_col3, art_col4 = st.columns(4)
            with art_col1:
                st.metric("视频分析", artifacts.get("video_analyses", 0))
            with art_col2:
                st.metric("评论分析", artifacts.get("comment_analyses", 0))
            with art_col3:
                st.metric("媒体分析", artifacts.get("media_analyses", 0))
            with art_col4:
                st.metric("账号提炼", artifacts.get("account_distillations", 0))
    elif not status.get("ok"):
        st.info("点击「刷新状态」查看项目信息")

with tab2:
    st.subheader("数据表概览")
    if status.get("ok"):
        normalized = status.get("normalized", {})
        if normalized:
            st.dataframe(
                {"表名": list(normalized.keys()), "行数": list(normalized.values())},
                use_container_width=True,
                hide_index=True,
            )

        accounts = status.get("accounts", [])
        if accounts:
            st.subheader("账号列表")
            st.dataframe(accounts, use_container_width=True, hide_index=True)

        videos = status.get("videos", {})
        if videos.get("recent"):
            st.subheader("最近视频")
            st.dataframe(videos["recent"], use_container_width=True, hide_index=True)

with tab3:
    st.subheader("报告列表")
    if status.get("ok") and st.button("📂 加载报告"):
        try:
            r = requests.get(f"{API_URL}/api/projects/{project_path}/reports/")
            if r.status_code == 200:
                reports = r.json().get("data", {}).get("reports", [])
                if reports:
                    for report in reports:
                        st.text(f"📄 {report}")
                else:
                    st.info("暂无报告")
        except requests.ConnectionError:
            st.error("API 未连接")

    # Doctor report
    if "doctor" in st.session_state:
        st.subheader("系统诊断")
        doctor = st.session_state["doctor"]
        caps = doctor.get("capabilities", {})
        d_col1, d_col2, d_col3 = st.columns(3)
        with d_col1:
            st.metric("核心可用", "✅" if caps.get("core") else "❌")
        with d_col2:
            st.metric("本地媒体", "✅" if caps.get("local_media") else "❌")
        with d_col3:
            st.metric("TikHub 采集", "✅" if caps.get("tikhub_douyin") else "❌")
