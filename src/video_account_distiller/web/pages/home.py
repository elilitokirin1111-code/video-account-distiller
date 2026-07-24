"""Streamlit home page — 项目仪表盘与设置."""

from __future__ import annotations

import os
from pathlib import Path

import requests
import streamlit as st

# ── 页面配置 ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Video Account Distiller",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 侧边栏：API 连接与设置 ───────────────────────────────────────────

st.sidebar.header("⚙️ 设置")

# API 地址
default_api = os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000")
if "api_url" not in st.session_state:
    st.session_state["api_url"] = default_api

api_url = st.sidebar.text_input(
    "🔗 后端 API 地址",
    value=st.session_state["api_url"],
    help="FastAPI 服务的地址，可按需更换",
)
st.session_state["api_url"] = api_url


def _api(path: str, method: str = "GET", **kwargs) -> requests.Response:
    url = f"{st.session_state['api_url']}{path}"
    try:
        return requests.request(method, url, timeout=30, **kwargs)
    except requests.ConnectionError:
        st.error(f"❌ 无法连接到 API：{url}")
        raise


# 项目路径
if "project_path" not in st.session_state:
    st.session_state["project_path"] = str(Path.home() / "distiller-demo")

project_path = st.sidebar.text_input(
    "📁 项目路径",
    value=st.session_state["project_path"],
    help="Distiller 项目目录的绝对路径",
)
st.session_state["project_path"] = project_path

st.sidebar.divider()

# 快速操作
st.sidebar.subheader("🛠️ 快捷操作")
col_a, col_b = st.sidebar.columns(2)
with col_a:
    if st.button("🔧 初始化项目", use_container_width=True):
        try:
            r = _api("/api/projects/init", "POST", json={"path": project_path, "name": Path(project_path).name})
            data = r.json()
            if data.get("ok"):
                st.success("项目已就绪 ✅")
            else:
                st.error(data.get("detail", "初始化失败"))
        except requests.ConnectionError:
            pass

with col_b:
    if st.button("🩺 系统诊断", use_container_width=True):
        try:
            r = _api(f"/api/doctor/{project_path}")
            if r.status_code == 200:
                st.session_state["doctor"] = r.json()["data"]
                st.success("诊断完成 ✅")
        except requests.ConnectionError:
            pass

st.sidebar.divider()
st.sidebar.caption("💡 API 未连接？先运行 `uv run distiller-web` 自动启动 API，或使用已部署的远程 API 地址。")

# ── 主内容 ────────────────────────────────────────────────────────────

st.title("📊 Video Account Distiller")
st.caption("基于证据的视频账号分析平台 — 导入数据 → 分析 → 报告 → 知识积累")

tab1, tab2, tab3, tab4 = st.tabs(["📋 项目状态", "📦 数据概览", "📈 分析产出", "🩺 诊断"])

with tab1:
    st.subheader("项目状态")

    if st.button("🔄 刷新状态", type="primary"):
        try:
            r = _api(f"/api/projects/{project_path}/status")
            if r.status_code == 200:
                st.session_state["status"] = r.json()
        except requests.ConnectionError:
            pass

    status = st.session_state.get("status", {})
    if status.get("ok"):
        project = status.get("project", {})
        meta1, meta2, meta3, meta4 = st.columns(4)
        with meta1:
            st.metric("项目名称", project.get("name", "-"))
        with meta2:
            st.metric("导入次数", status.get("imports", {}).get("count", 0))
        with meta3:
            st.metric("视频数量", status.get("normalized", {}).get("videos", 0))
        with meta4:
            st.metric("评论数量", status.get("normalized", {}).get("comments", 0))

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"**项目 ID**: {project.get('id', '-')}")
            st.caption(f"**创建时间**: {project.get('created_at', '-')}")
        with col2:
            st.caption(f"**最近更新**: {project.get('updated_at', '-')}")
            st.caption(f"**Schema 版本**: {status.get('schema_version', '-')}")

        # 导入详情
        imports = status.get("imports", {})
        if imports.get("count", 0) > 0:
            st.subheader("已导入数据结构")
            by_entity = imports.get("by_entity", {})
            st.dataframe(
                {"实体类型": [k for k in by_entity], "记录数": [by_entity[k] for k in by_entity]},
                use_container_width=True,
                hide_index=True,
            )

    else:
        st.info("👈 点击「刷新状态」查看项目信息")
        st.markdown("""
        如果没有项目，先在左侧输入项目路径，点击「初始化项目」。
        初始化后使用 **导入数据** 页面导入 CSV/JSON 文件。
        """)

with tab2:
    st.subheader("数据表概览")

    if status.get("ok"):
        normalized = status.get("normalized", {})
        if normalized:
            st.dataframe(
                [{"表名": k, "行数": v, "状态": "✅" if v > 0 else "⚠️ 空表"} for k, v in normalized.items()],
                use_container_width=True,
                hide_index=True,
            )

        accounts = status.get("accounts", [])
        if accounts:
            st.subheader("账号列表")
            st.dataframe(accounts, use_container_width=True, hide_index=True)

        videos = status.get("videos", {})
        if videos.get("recent"):
            st.subheader(f"最近视频 (共 {videos.get('total', 0)} 个)")
            if videos.get("truncated"):
                st.caption("仅显示最近 20 个视频")
            st.dataframe(videos["recent"], use_container_width=True, hide_index=True)
    else:
        st.info("请先刷新项目状态")

with tab3:
    st.subheader("分析产出")
    if status.get("ok"):
        artifacts = status.get("artifacts", {})
        art1, art2, art3, art4 = st.columns(4)
        with art1:
            st.metric("视频分析", artifacts.get("video_analyses", 0))
            st.metric("账号提炼", artifacts.get("account_distillations", 0))
        with art2:
            st.metric("评论分析", artifacts.get("comment_analyses", 0))
            st.metric("对标比较", artifacts.get("benchmark_comparisons", 0))
        with art3:
            st.metric("媒体分析", artifacts.get("media_analyses", 0))
            st.metric("报告数量", artifacts.get("account_health_reports", 0))
        with art4:
            st.metric("预测记录", artifacts.get("predictions", 0))
            st.metric("回溯复盘", artifacts.get("retros", 0))

        st.divider()
        st.subheader("时间线")
        timeline_items = []
        for field, label in [
            ("last_normalized_at", "标准化"),
            ("last_metrics_at", "指标计算"),
            ("last_sample_at", "抽样"),
            ("last_report_at", "报告"),
            ("last_video_analysis_at", "视频分析"),
            ("last_comment_analysis_at", "评论分析"),
            ("last_media_analysis_at", "媒体分析"),
            ("last_distillation_at", "提炼"),
            ("last_comparison_at", "对标"),
            ("last_scoring_at", "评分"),
            ("last_prediction_at", "预测"),
            ("last_publication_at", "发布"),
            ("last_retro_at", "复盘"),
        ]:
            ts = status.get(field)
            if ts:
                timeline_items.append({"操作": label, "最近时间": ts[:19] if isinstance(ts, str) else str(ts)})
        if timeline_items:
            st.dataframe(timeline_items, use_container_width=True, hide_index=True)
    else:
        st.info("请先刷新项目状态")

with tab4:
    st.subheader("系统诊断")
    if "doctor" in st.session_state:
        doctor = st.session_state["doctor"]
        caps = doctor.get("capabilities", {})

        st.subheader("核心能力")
        d1, d2, d3, d4, d5 = st.columns(5)
        with d1:
            st.metric("核心可用", "✅" if caps.get("core") else "❌")
        with d2:
            st.metric("FFmpeg", "✅" if caps.get("local_media") else "❌")
        with d3:
            st.metric("TikHub", "✅" if caps.get("tikhub_douyin") else "❌")
        with d4:
            st.metric("飞书", "✅" if caps.get("feishu_bitable") else "❌")
        with d5:
            st.metric("Google", "✅" if caps.get("google_sheets") else "❌")

        st.divider()
        st.subheader("运行环境")
        env1, env2, env3 = st.columns(3)
        with env1:
            st.caption(f"Python: {doctor.get('python_version', '-')}")
        with env2:
            st.caption(f"OS: {doctor.get('operating_system', '-')}")
        with env3:
            st.caption(f"包版本: {doctor.get('package_version', '-')}")

        deps = doctor.get("dependencies", [])
        if deps:
            st.subheader("依赖")
            st.dataframe(
                [{"名称": d["name"], "版本": d.get("version") or "❌ 缺失"} for d in deps],
                use_container_width=True,
                hide_index=True,
            )

        project_diag = doctor.get("project")
        if project_diag:
            st.subheader("项目诊断")
            pd1, pd2, pd3 = st.columns(3)
            with pd1:
                st.metric("可读", "✅" if project_diag.get("readable") else "❌")
            with pd2:
                st.metric("可写", "✅" if project_diag.get("writable") else "❌")
            with pd3:
                st.metric("校验", "✅" if project_diag.get("validation_ok") else "❌")
    else:
        st.info("点击左侧「系统诊断」按钮生成诊断报告")
