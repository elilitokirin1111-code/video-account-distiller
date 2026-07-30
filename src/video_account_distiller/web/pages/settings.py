"""Product settings for connections, permissions and diagnostics."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

from video_account_distiller.web.ui import (
    badge,
    section_header,
    setup_page,
)

st.set_page_config(
    page_title="系统设置 · Video Account Distiller",
    page_icon=":material/settings:",
    layout="wide",
    initial_sidebar_state="expanded",
)

context = setup_page(
    "settings",
    "系统设置",
    "管理工作区连接、云端模型权限与运行诊断；敏感配置保持显式、可审计。",
    eyebrow="SYSTEM SETTINGS",
)

connection_tab, model_tab, runtime_tab, developer_tab = st.tabs(
    ["连接配置", "AI 权限", "运行状态", "开发者"]
)

with connection_tab:
    section_header("连接配置", "设置所有页面共用的 API 地址与项目路径。")
    with st.container(border=True):
        st.markdown("#### API 连接")
        api_columns = st.columns([3, 1], vertical_alignment="bottom")
        with api_columns[0]:
            api_url = st.text_input(
                "后端 API 地址",
                value=context.api_url,
                placeholder="http://127.0.0.1:8000",
                help="本地一体化应用通常会自动配置此地址。",
                key="settings_api_url",
            ).rstrip("/")
        with api_columns[1]:
            if st.button(
                "测试连接",
                icon=":material/cable:",
                use_container_width=True,
            ):
                try:
                    response = requests.get(f"{api_url}/api/health", timeout=5)
                    if response.ok:
                        payload = response.json()
                        st.success(f"连接成功 · {payload.get('version', 'unknown')}")
                        st.session_state["sidebar_api_status"] = "正常"
                    else:
                        st.error(f"HTTP {response.status_code}")
                except (requests.RequestException, ValueError) as exc:
                    st.error(f"连接失败：{exc}")
                    st.session_state["sidebar_api_status"] = "未连接"

        st.markdown("#### 项目工作区")
        project_path = st.text_input(
            "默认项目路径",
            value=context.project_path,
            help="数据、报告与分析工件将写入该项目目录。",
            key="settings_project_path",
        )
        if st.button(
            "保存连接配置",
            type="primary",
            icon=":material/save:",
        ):
            st.session_state["global_api_url"] = api_url
            st.session_state["global_project_path"] = project_path
            st.session_state["api_url"] = api_url
            st.session_state["project_path"] = project_path
            st.success("连接配置已应用到当前会话。")

    with st.container(border=True):
        st.markdown("#### 配置说明")
        st.caption(
            "页面只保存 API 地址和项目路径，不显示、上传或持久化平台登录凭据。"
            "项目初始化可在左侧“连接与项目”面板完成。"
        )
        st.markdown(
            f"{badge('会话级配置', 'neutral')} {badge('本地 API', 'success')}",
            unsafe_allow_html=True,
        )

with model_tab:
    section_header("云端模型权限", "默认离线；只有显式授权与逐次确认后才允许调用云端模型。")
    encoded_project = quote(context.project_path, safe="")
    cloud_permission = False
    cloud_payload: dict[str, Any] = {}
    try:
        cloud_response = requests.get(
            f"{context.api_url}/api/projects/{encoded_project}/settings/cloud-model",
            timeout=5,
        )
        payload_value: Any = cloud_response.json()
        cloud_payload = payload_value if isinstance(payload_value, dict) else {}
        cloud_permission = bool(cloud_payload.get("allow_cloud_model_upload"))
    except (requests.RequestException, ValueError):
        pass

    with st.container(border=True):
        permission_header, permission_status = st.columns(
            [3, 1],
            vertical_alignment="center",
        )
        permission_header.markdown("#### GPT 数据外发权限")
        permission_status.markdown(
            badge(
                "已启用" if cloud_permission else "默认关闭",
                "warning" if cloud_permission else "success",
            ),
            unsafe_allow_html=True,
        )
        st.caption(
            "开启后仍需在每次分析时确认数据外发和潜在费用。"
            "这里只保存项目权限开关，API 密钥必须在服务环境中配置。"
        )
        allow_cloud_model_upload = st.toggle(
            "允许将受限、脱敏的分析上下文发送给云端模型",
            value=cloud_permission,
        )
        if st.button(
            "保存 AI 权限",
            type="primary",
            icon=":material/admin_panel_settings:",
            disabled=not bool(context.project_path),
        ):
            try:
                response = requests.put(
                    f"{context.api_url}/api/projects/{encoded_project}/settings/cloud-model",
                    json={"allow_cloud_model_upload": allow_cloud_model_upload},
                    timeout=10,
                )
                payload = response.json()
                if response.ok and payload.get("ok"):
                    st.success("云端模型权限已更新；API 密钥仍未保存。")
                else:
                    st.error(
                        (payload.get("error") or {}).get(
                            "message",
                            "设置保存失败",
                        )
                    )
            except (requests.RequestException, ValueError) as exc:
                st.error(f"设置保存失败：{exc}")

    with st.container(border=True):
        st.markdown("#### 安全边界")
        security_rows = (
            ("项目权限", "显式开关"),
            ("数据范围", "受限且脱敏"),
            ("费用确认", "每次调用确认"),
            ("API 密钥", "仅服务环境读取"),
        )
        for label, value in security_rows:
            label_column, value_column = st.columns([2.5, 1])
            label_column.markdown(f"**{label}**")
            value_column.markdown(
                badge(value, "neutral"),
                unsafe_allow_html=True,
            )

with runtime_tab:
    section_header("API 与任务状态", "按需刷新，不让诊断信息抢占日常业务操作。")
    status_column, task_column = st.columns([0.8, 1.2], gap="large")
    with status_column:
        with st.container(border=True):
            st.markdown("#### API 服务")
            if st.button(
                "刷新服务状态",
                icon=":material/health_and_safety:",
                use_container_width=True,
            ):
                try:
                    response = requests.get(
                        f"{context.api_url}/api/health",
                        timeout=5,
                    )
                    st.session_state["settings_health"] = response.json()
                except (requests.RequestException, ValueError) as exc:
                    st.session_state["settings_health"] = {
                        "ok": False,
                        "error": str(exc),
                    }
            health = st.session_state.get("settings_health")
            if isinstance(health, dict):
                st.json(health)
            else:
                st.caption("点击刷新后显示版本与服务状态。")

    with task_column:
        with st.container(border=True):
            st.markdown("#### 最近任务")
            if st.button(
                "刷新任务历史",
                icon=":material/refresh:",
                use_container_width=True,
            ):
                try:
                    response = requests.get(
                        f"{context.api_url}/api/tasks",
                        params={"limit": 20},
                        timeout=5,
                    )
                    st.session_state["settings_tasks"] = response.json()
                except (requests.RequestException, ValueError) as exc:
                    st.session_state["settings_tasks"] = {
                        "tasks": [],
                        "error": str(exc),
                    }
            tasks_payload = st.session_state.get("settings_tasks")
            tasks = tasks_payload.get("tasks", []) if isinstance(tasks_payload, dict) else []
            if isinstance(tasks, list) and tasks:
                st.dataframe(
                    [
                        {
                            "任务": item.get("task_id"),
                            "类型": item.get("task_type", "通用任务"),
                            "状态": item.get("status"),
                            "阶段": item.get("stage"),
                            "进度": item.get("progress"),
                            "更新时间": item.get("updated_at"),
                            "错误码": (item.get("error") or {}).get("code"),
                        }
                        for item in tasks
                        if isinstance(item, dict)
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("暂无任务记录，或尚未刷新。")

with developer_tab:
    section_header("开发者入口", "把调试信息放在次级区域，避免干扰运营用户。")
    documentation_column, danger_column = st.columns(2, gap="large")
    with documentation_column:
        with st.container(border=True):
            st.markdown("#### API 文档")
            st.caption("用于接口调试、契约核对与集成开发。")
            st.link_button(
                "打开 Swagger UI",
                f"{context.api_url}/docs",
                icon=":material/api:",
                use_container_width=True,
            )
            st.link_button(
                "打开 ReDoc",
                f"{context.api_url}/redoc",
                icon=":material/menu_book:",
                use_container_width=True,
            )

    with danger_column:
        with st.container(border=True):
            st.markdown("#### 危险操作")
            st.warning(
                "清理或迁移项目数据可能不可恢复。当前产品界面不提供一键删除，"
                "请先在项目目录外完成备份。"
            )
            st.button(
                "清理项目数据",
                icon=":material/delete_forever:",
                use_container_width=True,
                disabled=True,
                help="为避免误操作，此功能暂不在网页中开放。",
            )
