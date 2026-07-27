"""Streamlit page — API 连接与设置."""

from __future__ import annotations

import os

import requests
import streamlit as st

st.set_page_config(page_title="设置", page_icon="⚙️", layout="wide")

st.title("⚙️ 设置")

# ── API 连接 ──────────────────────────────────────────────────────────
st.subheader("🔗 API 连接")

col1, col2 = st.columns([3, 1])
with col1:
    api_url = st.text_input(
        "后端 API 地址",
        value=st.session_state.get(
            "api_url", os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000")
        ),
        placeholder="http://127.0.0.1:8000",
        help="FastAPI 后端地址。本地开发默认 http://127.0.0.1:8000",
    )
with col2:
    st.write("")
    st.write("")
    if st.button("🔗 测试连接"):
        st.session_state["api_url"] = api_url
        try:
            r = requests.get(f"{api_url}/api/health", timeout=5)
            if r.status_code == 200:
                st.success(f"✅ 连接成功 — {r.json().get('version', 'unknown')}")
            else:
                st.error(f"HTTP {r.status_code}")
        except requests.ConnectionError:
            st.error(f"❌ 无法连接: {api_url}")
        except Exception as exc:
            st.error(f"❌ 连接失败: {exc}")

st.session_state["api_url"] = api_url

st.divider()

# ── 项目路径 ──────────────────────────────────────────────────────────
st.subheader("📁 项目路径")

project_path = st.text_input(
    "默认项目路径",
    value=st.session_state.get("project_path", str(os.path.expanduser("~/distiller-demo"))),
    help="所有页面的默认项目目录",
)
st.session_state["project_path"] = project_path

st.divider()

# ── API 状态 ──────────────────────────────────────────────────────────
st.subheader("📊 API 服务状态")

if st.button("🔄 查询状态"):
    try:
        r = requests.get(f"{api_url}/api/health", timeout=5)
        st.json(r.json())
    except Exception as exc:
        st.error(f"无法获取 API 状态: {exc}")

st.subheader("🧾 最近任务")
if st.button("刷新任务历史"):
    try:
        response = requests.get(f"{api_url}/api/tasks", params={"limit": 20}, timeout=5)
        payload = response.json()
        tasks = payload.get("tasks", [])
        if tasks:
            st.dataframe(
                [
                    {
                        "任务": item.get("task_id"),
                        "状态": item.get("status"),
                        "进度": item.get("progress"),
                        "更新时间": item.get("updated_at"),
                        "错误码": (item.get("error") or {}).get("code"),
                    }
                    for item in tasks
                ],
                use_container_width=True,
            )
        else:
            st.info("暂无任务记录")
    except Exception as exc:
        st.error(f"无法获取任务历史: {exc}")

# ── API 文档链接 ─────────────────────────────────────────────────────
st.divider()
st.subheader("📖 API 文档")

st.markdown(f"""
- **Swagger UI**: [{api_url}/docs]({api_url}/docs)
- **ReDoc**: [{api_url}/redoc]({api_url}/redoc)
""")
