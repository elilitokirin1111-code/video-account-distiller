"""Streamlit page — 数据导入."""

from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

st.set_page_config(page_title="数据导入", page_icon="📥", layout="wide")

st.title("📥 数据导入")

# ── API 连接 ──────────────────────────────────────────────────────────
api_url = st.sidebar.text_input(
    "API 地址",
    value=os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000"),
)


def _api(path: str, method: str = "GET", **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.request(method, f"{api_url}{path}", timeout=60, **kwargs)
        payload: Any = response.json()
        return payload if isinstance(payload, dict) else {"ok": False}
    except (requests.RequestException, ValueError):
        st.error(f"无法连接 API: {api_url}")
        return {"ok": False, "detail": "Connection error"}


project_path = st.sidebar.text_input(
    "项目路径", value=str(st.session_state.get("project_path", ""))
)

st.sidebar.info("左侧设置中可更改 API 地址和项目路径。点击左上角「🏠」回到首页。")

# ── 导入表单 ──────────────────────────────────────────────────────────
entity = st.selectbox("选择导入类型", ["accounts", "videos", "metrics", "comments", "transcripts"])
platform = st.selectbox(
    "平台",
    ["douyin", "xiaohongshu", "wechat-channels", "bilibili", "tiktok", "youtube", "instagram"],
)

uploaded_file = st.file_uploader(
    "选择数据文件", type=["csv", "json", "jsonl", "ndjson", "srt", "vtt", "txt"]
)

col1, col2 = st.columns(2)
with col1:
    dry_run = st.checkbox("预演模式 (dry-run)", value=False, help="只模拟导入，不实际写入")
with col2:
    mapping = st.text_input("字段映射文件路径 (可选)", placeholder="可选 YAML 路径")

transcript_video_id = ""
transcript_language: str | None = None
if entity == "transcripts":
    transcript_video_id = st.text_input("视频 ID", help="此字幕对应的视频 ID")
    transcript_language_input = st.text_input("语言 (可选)", placeholder="zh-CN")
    transcript_language = transcript_language_input or None

if uploaded_file and st.button("🚀 开始导入", type="primary"):
    endpoint = f"/api/projects/{project_path}/import/{entity}"
    params: dict[str, str | int | float | bool | None] = {
        "dry_run": dry_run,
    }

    if entity == "transcripts":
        params["video_id"] = transcript_video_id
        params["language"] = transcript_language
    else:
        params["platform"] = platform
        params["mapping"] = mapping or None

    try:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        r = requests.post(f"{api_url}{endpoint}", params=params, files=files, timeout=120)
        data = r.json()
        if data.get("ok"):
            info = data.get("data", {})
            st.success("导入成功 ✅")
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric(
                    "已接受行数", info.get("report", {}).get("stats", {}).get("accepted_rows", "?")
                )
            with col_b:
                st.metric(
                    "已拒绝行数", info.get("report", {}).get("stats", {}).get("rejected_rows", "?")
                )
            with col_c:
                st.metric(
                    "重复行数", info.get("report", {}).get("stats", {}).get("duplicate_rows", "?")
                )
            with st.expander("📄 详细报告"):
                st.json(info)
        else:
            st.error(f"导入失败: {data.get('detail', '未知错误')}")
    except Exception as exc:
        st.error(f"请求失败: {exc}")

# ── 标准化 ────────────────────────────────────────────────────────────
st.divider()
st.subheader("📐 数据标准化")

if st.button("运行标准化", type="secondary"):
    result = _api(
        f"/api/projects/{project_path}/normalize", "POST", params={"dry_run": str(dry_run).lower()}
    )
    if result.get("ok"):
        st.success("标准化完成 ✅")
        st.json(result)
    else:
        st.error(f"标准化失败: {result.get('detail')}")
