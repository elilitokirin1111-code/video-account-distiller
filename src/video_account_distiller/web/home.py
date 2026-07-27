"""Video Account Distiller — 视频账号数据分析平台."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import streamlit as st

st.set_page_config(
    page_title="Distiller 仪表盘", page_icon="📊", layout="wide", initial_sidebar_state="expanded"
)

# ── 侧边栏 ───────────────────────────────────────────────────────────
st.sidebar.title("📊 Video Account Distiller")
st.sidebar.caption("v1.0.0 — 基于证据的视频账号分析")

api_url = st.sidebar.text_input(
    "🔗 后端 API",
    value=os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000"),
    help="FastAPI 服务地址，可按需更换",
)
st.session_state["api_url"] = api_url

project_path = st.sidebar.text_input(
    "📁 项目路径", value=str(Path.home() / "distiller-demo"), help="Distiller 项目目录的绝对路径"
)
st.session_state["project_path"] = project_path

st.sidebar.divider()

if st.sidebar.button("🚀 初始化项目", use_container_width=True):
    try:
        init_response = requests.post(
            f"{api_url}/api/projects/init",
            json={"path": project_path, "name": Path(project_path).name},
            timeout=10,
        )
        if init_response.json().get("ok"):
            st.sidebar.success("项目已就绪 ✅")
    except (requests.RequestException, ValueError) as exc:
        st.sidebar.error(f"API 未连接: {exc}")

st.sidebar.markdown("---")
st.sidebar.caption("💡 其他页面在左侧导航栏 →")
st.sidebar.caption("⬆️ 如果看不到，点击左上角 `>` 展开")


def _api(path: str) -> dict[str, Any]:
    try:
        payload: Any = requests.get(f"{api_url}{path}", timeout=15).json()
        return payload if isinstance(payload, dict) else {}
    except (requests.RequestException, ValueError):
        return {}


# ── 主页内容 ─────────────────────────────────────────────────────────
st.title("📊 Video Account Distiller")
st.caption(
    "基于证据的视频账号分析平台 — 抖音 · B站 · YouTube · TikTok · 小红书 · Instagram · 微信视频号"
)
st.caption(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# 刷新状态
if st.button("🔄 刷新项目状态", type="primary"):
    status_payload = _api(f"/api/projects/{project_path}/status")
    st.session_state["status"] = status_payload

status = st.session_state.get("status", {})
project = status.get("project", {})

if not status.get("ok"):
    st.info("👈 在左侧输入项目路径，点击「初始化项目」，然后「刷新状态」")
    st.markdown("""
    ### 快速开始
    1. **设置 API**：左侧输入后端地址
    2. **初始化项目**：点击按钮创建项目目录
    3. **采集数据**：导航到「🎯 主页采集分析」粘贴抖音链接
    4. **导入数据**：或在「📥 数据导入」上传 CSV/JSON 文件
    5. **查看报告**：在「📄 报告浏览」查看分析结果
    """)
else:
    # 统计卡片
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("项目名称", project.get("name", "-"))
    with c2:
        st.metric("账号数", len(status.get("accounts", [])))
    with c3:
        st.metric("总视频数", status.get("normalized", {}).get("videos", 0))
    with c4:
        st.metric("总评论数", status.get("normalized", {}).get("comments", 0))

    st.divider()

    # 页面快捷入口
    st.subheader("📋 功能导航")
    nav1, nav2, nav3, nav4 = st.columns(4)
    with nav1:
        st.page_link("pages/quick_collect.py", label="🎯 主页采集分析", icon="🎯")
        st.caption("粘贴抖音链接，一键采集+分析")
    with nav2:
        st.page_link("pages/import_data.py", label="📥 数据导入", icon="📥")
        st.caption("上传 CSV/JSON 文件导入数据")
    with nav3:
        st.page_link("pages/account_analysis.py", label="🔬 账号分析", icon="🔬")
        st.caption("抽样 · 报告 · 视频分析 · 提炼")
    with nav4:
        st.page_link("pages/reports.py", label="📄 报告浏览", icon="📄")
        st.caption("查看已生成的 Markdown/JSON 报告")

    st.divider()

    # 分析产出统计
    artifacts = status.get("artifacts", {})
    st.subheader("📊 分析产出")
    a1, a2, a3, a4, a5 = st.columns(5)
    with a1:
        st.metric("视频分析", artifacts.get("video_analyses", 0))
    with a2:
        st.metric("评论分析", artifacts.get("comment_analyses", 0))
    with a3:
        st.metric("媒体分析", artifacts.get("media_analyses", 0))
    with a4:
        st.metric("账号提炼", artifacts.get("account_distillations", 0))
    with a5:
        st.metric("预测记录", artifacts.get("predictions", 0))

    # 时间线
    st.divider()
    st.subheader("⏱️ 操作时间线")
    timeline = []
    for field, label in [
        ("last_video_analysis_at", "🎬 视频分析"),
        ("last_comment_analysis_at", "💬 评论分析"),
        ("last_media_analysis_at", "📹 媒体分析"),
        ("last_distillation_at", "🏭 账号提炼"),
        ("last_report_at", "📄 报告"),
        ("last_metrics_at", "📈 指标"),
        ("last_normalized_at", "📐 标准化"),
        ("last_sample_at", "🎯 抽样"),
        ("last_scoring_at", "⭐ 评分"),
        ("last_prediction_at", "🔮 预测"),
        ("last_publication_at", "📤 发布"),
        ("last_retro_at", "🔄 复盘"),
    ]:
        ts = status.get(field)
        if ts:
            timeline.append(f"{label}: {ts[:19] if isinstance(ts, str) else str(ts)}")
    for item in timeline:
        st.caption(item)
