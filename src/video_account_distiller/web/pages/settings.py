"""Product settings for connections, permissions and diagnostics."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

from video_account_distiller.web import web_state
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
    "设置",
    "管理工作区、AI 服务和运行诊断。日常使用通常不需要修改这里。",
    eyebrow="系统与高级工具",
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
            "保存工作区",
            type="primary",
            icon=":material/save:",
        ):
            # Widget keys cannot be reassigned after instantiation; drop them so
            # the sidebar rebuilds from the saved values on the next rerun.
            st.session_state.pop("global_api_url", None)
            st.session_state.pop("global_project_path", None)
            st.session_state["api_url"] = api_url
            st.session_state["project_path"] = project_path
            web_state.set_state(api_url=api_url, project_path=project_path)
            st.success("连接配置已保存并应用到当前会话。")
            st.rerun()

    with st.container(border=True):
        st.markdown("#### 配置说明")
        st.caption(
            "页面只保存 API 地址和项目路径，不显示、上传或持久化平台登录凭据。"
            "新建蒸馏任务时会自动初始化尚未创建的项目目录。"
        )
        st.markdown(
            f"{badge('会话级配置', 'neutral')} {badge('本地 API', 'success')}",
            unsafe_allow_html=True,
        )

with model_tab:
    section_header("云端模型权限", "选择服务商与模型；调用前仍需显式授权并逐次确认。")
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
        permission_header.markdown("#### 云端深度分析数据外发权限")
        permission_status.markdown(
            badge(
                "已启用" if cloud_permission else "默认关闭",
                "warning" if cloud_permission else "success",
            ),
            unsafe_allow_html=True,
        )
        st.caption(
            "开启后仍需在每次分析时确认数据外发和潜在费用。"
            "API Key 可在采集任务的云端深度分析页验证并保存到当前 Windows 用户凭据。"
        )
        providers = cloud_payload.get("providers") or {}
        openai_status, bailian_status, deepseek_status = st.columns(3)
        openai_status.metric(
            "OpenAI",
            "密钥已配置"
            if (providers.get("openai") or {}).get("api_key_configured")
            else "可在分析页保存",
        )
        bailian_status.metric(
            "阿里云百炼",
            "密钥已配置"
            if (providers.get("bailian") or {}).get("api_key_configured")
            else "可在分析页保存",
        )
        deepseek_status.metric(
            "DeepSeek",
            "密钥已配置"
            if (providers.get("deepseek") or {}).get("api_key_configured")
            else "可在分析页保存",
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
            ("API 密钥", "Windows 用户凭据"),
        )
        for label, value in security_rows:
            label_column, value_column = st.columns([2.5, 1])
            label_column.markdown(f"**{label}**")
            value_column.markdown(
                badge(value, "neutral"),
                unsafe_allow_html=True,
            )

    with st.container(border=True):
        st.markdown("#### 云端 API 预设")
        st.caption(
            "保存到当前项目 distiller.yaml：作为媒体文本、画面理解与知识分析的默认"
            "云端端点。保存后新建蒸馏任务会自动带出，无需每次填写。"
        )
        preset_payload: dict[str, Any] = {}
        try:
            preset_response = requests.get(
                f"{context.api_url}/api/projects/{encoded_project}/settings/cloud-preset",
                timeout=5,
            )
            preset_json: Any = preset_response.json()
            if isinstance(preset_json, dict):
                preset_payload = preset_json
        except (requests.RequestException, ValueError):
            pass
        preset_base_url = str(preset_payload.get("cloud_base_url") or "")
        preset_has_key = bool(preset_payload.get("cloud_api_key_configured"))
        preset_text_model = str(preset_payload.get("cloud_text_model") or "")
        preset_vision_model = str(preset_payload.get("cloud_vision_model") or "")
        preset_columns = st.columns(2)
        with preset_columns[0]:
            preset_base_input = st.text_input(
                "云端服务地址（OpenAI 兼容）",
                value=preset_base_url,
                placeholder="https://api.deepseek.com",
                key="settings_cloud_preset_base_url",
                help=(
                    "无协议前缀会自动补全 https://。示例："
                    "https://dashscope.aliyuncs.com/compatible-mode/v1 或 "
                    "https://ws-<workspace>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
                ),
            )
            preset_text_input = st.text_input(
                "云端文本模型",
                value=preset_text_model,
                placeholder="deepseek-v4-flash",
                key="settings_cloud_preset_text_model",
            )
        with preset_columns[1]:
            preset_key_placeholder = (
                "已保存（留空保持不变）" if preset_has_key else "输入新的 API Key"
            )
            preset_key_input = st.text_input(
                "云端 API Key",
                type="password",
                placeholder=preset_key_placeholder,
                key="settings_cloud_preset_api_key",
                help="留空时保留项目里已有的 Key；输入新值会覆盖。",
            )
            preset_vision_input = st.text_input(
                "云端视觉模型",
                value=preset_vision_model,
                placeholder="qwen-vl-max-latest",
                key="settings_cloud_preset_vision_model",
            )
        if st.button(
            "保存云端 API 预设",
            type="primary",
            icon=":material/cloud_sync:",
            disabled=not bool(context.project_path),
            key="settings_cloud_preset_save",
        ):
            preset_body: dict[str, Any] = {
                "cloud_base_url": preset_base_input.strip(),
                "cloud_api_key": preset_key_input.strip() or None,
                "cloud_text_model": preset_text_input.strip() or None,
                "cloud_vision_model": preset_vision_input.strip() or None,
            }
            try:
                preset_response = requests.put(
                    f"{context.api_url}/api/projects/{encoded_project}/settings/cloud-preset",
                    json=preset_body,
                    timeout=10,
                )
                preset_result = preset_response.json()
                if preset_response.ok and preset_result.get("ok"):
                    st.success(
                        "云端 API 预设已保存到项目配置。"
                        + ("（API Key 已更新）" if preset_key_input.strip() else "")
                    )
                else:
                    st.error(
                        (preset_result.get("error") or {}).get(
                            "message",
                            "预设保存失败",
                        )
                    )
            except (requests.RequestException, ValueError) as exc:
                st.error(f"预设保存失败：{exc}")

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
    section_header("高级工具", "低频的数据维护与开发入口集中放在这里。")
    tool_columns = st.columns(3)
    with tool_columns[0]:
        st.page_link(
            "pages/import_data.py",
            label="导入私域数据",
            icon=":material/upload_file:",
            use_container_width=True,
        )
        st.caption("导入创作者后台或其他授权导出。")
    with tool_columns[1]:
        st.page_link(
            "pages/data_browser.py",
            label="浏览底层数据",
            icon=":material/database:",
            use_container_width=True,
        )
        st.caption("查询标准化实体和来源记录。")
    with tool_columns[2]:
        st.page_link(
            "pages/account_analysis.py",
            label="手动分析流水线",
            icon=":material/account_tree:",
            use_container_width=True,
        )
        st.caption("仅用于诊断或单步重建分析。")

    section_header("开发者入口", "接口文档与受保护的维护操作。")
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
