"""Guided data import page."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

from video_account_distiller.web.ui import (
    badge,
    section_header,
    setup_page,
    stepper,
)

st.set_page_config(
    page_title="数据导入 · Video Account Distiller",
    page_icon=":material/upload_file:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _api(
    api_url: str,
    path: str,
    method: str = "GET",
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        response = requests.request(method, f"{api_url}{path}", timeout=60, **kwargs)
        payload: Any = response.json()
        return payload if isinstance(payload, dict) else {"ok": False}
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "detail": str(exc)}


def _render_import_result(data: dict[str, Any]) -> None:
    if not data.get("ok"):
        error = data.get("error", {})
        detail = error.get("message") if isinstance(error, dict) else None
        st.error(f"导入失败：{detail or data.get('detail', '未知错误')}")
        return
    info = data.get("data", data)
    report = info.get("report") or info.get("quality") or {}
    stats = report.get("stats", {})
    st.success("导入完成，质量报告已生成。")
    metric_columns = st.columns(4)
    metric_columns[0].metric("输入记录", stats.get("input_rows", "?"))
    metric_columns[1].metric("已接受", stats.get("accepted_rows", "?"))
    metric_columns[2].metric("已拒绝", stats.get("rejected_rows", "?"))
    metric_columns[3].metric(
        "展开后记录",
        stats.get("expanded_rows", stats.get("input_rows", "?")),
    )
    with st.expander("查看完整质量报告", expanded=True, icon=":material/fact_check:"):
        st.json(info)


context = setup_page(
    "import",
    "数据导入",
    "通过向导接入公开数据或授权私域导出，并在写入前完成字段校验与标准化。",
    eyebrow="IMPORT WIZARD",
)
encoded_project = quote(context.project_path, safe="")

stepper(["导入方式", "数据类型", "平台", "上传与校验", "标准化结果"], active=1)

section_header("导入配置", "选择数据来源后，系统会展示对应的校验和上传要求。")
with st.container(border=True):
    st.markdown("#### 01–03 · 来源与字段")
    import_mode = st.radio(
        "导入方式",
        ["标准公开数据", "授权私域导出"],
        horizontal=True,
        help="授权私域导出必须同时提供数据文件和带授权证明、SHA-256 的 manifest。",
    )

    config_columns = st.columns([1, 1, 1.45, 0.72], gap="medium")
    if import_mode == "标准公开数据":
        with config_columns[0]:
            entity = st.selectbox(
                "数据类型",
                ["accounts", "videos", "metrics", "comments", "transcripts"],
                format_func=lambda value: {
                    "accounts": "账号",
                    "videos": "视频",
                    "metrics": "指标快照",
                    "comments": "评论",
                    "transcripts": "字幕",
                }[value],
            )
        with config_columns[1]:
            platform = st.selectbox(
                "平台",
                [
                    "douyin",
                    "xiaohongshu",
                    "wechat-channels",
                    "bilibili",
                    "tiktok",
                    "youtube",
                    "instagram",
                ],
                format_func=lambda value: {
                    "douyin": "抖音",
                    "xiaohongshu": "小红书",
                    "wechat-channels": "微信视频号",
                    "bilibili": "B站",
                    "tiktok": "TikTok",
                    "youtube": "YouTube",
                    "instagram": "Instagram",
                }[value],
            )
    else:
        entity = "authorized-export"
        platform = ""
        with config_columns[0]:
            st.text_input("数据类型", value="由 manifest 识别", disabled=True)
        with config_columns[1]:
            st.text_input("平台", value="由 manifest 识别", disabled=True)

    with config_columns[2]:
        mapping = st.text_input(
            "字段映射（可选）",
            placeholder="自定义 YAML 映射路径",
        )
    with config_columns[3]:
        dry_run = st.toggle(
            "预演模式",
            value=False,
            help="只完成解析、映射和质量校验，不写入项目。",
        )

    st.caption(
        "公开数据适用于平台公开数据和合规采集结果；"
        "授权私域导出会从 manifest 自动识别数据类型、平台和 read 授权。"
    )

section_header("上传与校验", "横向完成文件准备、状态检查和导入操作。")
upload_column, guard_column = st.columns([1.7, 1], gap="large")
uploaded_file = None
manifest_file = None
private_data_file = None

with upload_column:
    with st.container(border=True):
        st.markdown("#### 04 · 准备文件")
        st.caption("文件仅发送到当前 Distiller API，不会由页面上传到第三方。")
        if import_mode == "标准公开数据":
            uploaded_file = st.file_uploader(
                "拖拽或选择数据文件",
                type=["csv", "json", "jsonl", "ndjson", "srt", "vtt", "txt"],
                key="standard-data",
            )
            transcript_video_id = ""
            transcript_language: str | None = None
            if entity == "transcripts":
                transcript_columns = st.columns(2)
                with transcript_columns[0]:
                    transcript_video_id = st.text_input(
                        "视频 ID",
                        help="该字幕对应的视频 ID。",
                    )
                with transcript_columns[1]:
                    transcript_language_input = st.text_input(
                        "语言（可选）",
                        placeholder="zh-CN",
                    )
                    transcript_language = transcript_language_input or None

            if uploaded_file:
                st.markdown(
                    badge(f"已选择 · {uploaded_file.name}", "success"),
                    unsafe_allow_html=True,
                )
            if st.button(
                "校验并导入",
                type="primary",
                icon=":material/upload:",
                use_container_width=True,
                disabled=uploaded_file is None or not bool(context.project_path),
            ):
                assert uploaded_file is not None
                endpoint = f"/api/projects/{encoded_project}/import/{entity}"
                params: dict[str, str | int | float | bool | None] = {"dry_run": dry_run}
                if entity == "transcripts":
                    params["video_id"] = transcript_video_id
                    params["language"] = transcript_language
                else:
                    params["platform"] = platform
                    params["mapping"] = mapping or None
                try:
                    files = {
                        "file": (
                            uploaded_file.name,
                            uploaded_file.getvalue(),
                        )
                    }
                    with st.spinner("正在解析、校验并导入…"):
                        response = requests.post(
                            f"{context.api_url}{endpoint}",
                            params=params,
                            files=files,
                            timeout=120,
                        )
                    st.session_state["last_import_result"] = response.json()
                except (requests.RequestException, ValueError) as exc:
                    st.session_state["last_import_result"] = {
                        "ok": False,
                        "detail": str(exc),
                    }
        else:
            private_file_columns = st.columns(2, gap="medium")
            with private_file_columns[0]:
                manifest_file = st.file_uploader(
                    "授权 manifest",
                    type=["json", "yaml", "yml"],
                    key="authorized-manifest",
                )
            with private_file_columns[1]:
                private_data_file = st.file_uploader(
                    "创作者后台数据",
                    type=["csv", "json", "jsonl", "ndjson"],
                    key="authorized-data",
                )
            if manifest_file and private_data_file:
                st.markdown(
                    badge("授权文件与数据文件均已选择", "success"),
                    unsafe_allow_html=True,
                )
            if st.button(
                "校验授权并导入",
                type="primary",
                icon=":material/verified_user:",
                use_container_width=True,
                disabled=not (manifest_file and private_data_file and context.project_path),
            ):
                assert manifest_file is not None
                assert private_data_file is not None
                endpoint = f"/api/projects/{encoded_project}/import/authorized-export"
                files = {
                    "manifest": (manifest_file.name, manifest_file.getvalue()),
                    "data_file": (private_data_file.name, private_data_file.getvalue()),
                }
                try:
                    with st.spinner("正在验证授权、文件哈希与字段映射…"):
                        response = requests.post(
                            f"{context.api_url}{endpoint}",
                            params={
                                "dry_run": dry_run,
                                "mapping": mapping or None,
                            },
                            files=files,
                            timeout=120,
                        )
                    st.session_state["last_import_result"] = response.json()
                except (requests.RequestException, ValueError) as exc:
                    st.session_state["last_import_result"] = {
                        "ok": False,
                        "detail": str(exc),
                    }

file_ready = bool(
    uploaded_file if import_mode == "标准公开数据" else manifest_file and private_data_file
)
with guard_column:
    with st.container(border=True):
        st.markdown("#### 导入检查")
        checks = (
            ("项目路径", bool(context.project_path)),
            ("API 连接", bool(context.api_url)),
            ("字段配置", True),
            ("文件准备", file_ready),
        )
        check_columns = st.columns(2)
        for index, (label, ready) in enumerate(checks):
            with check_columns[index % 2]:
                st.markdown(f"**{label}**")
                st.markdown(
                    badge(
                        "就绪" if ready else "待完成",
                        "success" if ready else "neutral",
                    ),
                    unsafe_allow_html=True,
                )

        st.divider()
        st.markdown("#### 安全说明")
        st.caption("保留原始输入，未知值不会默认写成 0；私域导出还会校验授权、文件哈希与读取权限。")
        st.markdown(
            f"{badge('本地项目写入', 'neutral')} {badge('可先预演', 'success')}",
            unsafe_allow_html=True,
        )

last_import_result = st.session_state.get("last_import_result")
if isinstance(last_import_result, dict):
    section_header("导入结果", "查看接受、拒绝与展开记录，并进入标准化处理。")
    with st.container(border=True):
        _render_import_result(last_import_result)

section_header("标准化处理", "把已导入数据转换成统一、可追溯的分析结构。")
with st.container(border=True):
    standardize_columns = st.columns([3, 1], vertical_alignment="center")
    with standardize_columns[0]:
        st.markdown("**运行项目级标准化**")
        st.caption("处理字段映射、来源标记和跨平台规范，不修改原始输入文件。")
    with standardize_columns[1]:
        if st.button(
            "运行标准化",
            icon=":material/auto_fix_high:",
            use_container_width=True,
            disabled=not bool(context.project_path),
        ):
            with st.spinner("正在标准化数据…"):
                normalize_result = _api(
                    context.api_url,
                    f"/api/projects/{encoded_project}/normalize",
                    "POST",
                    params={"dry_run": str(dry_run).lower()},
                )
            if normalize_result.get("ok"):
                st.success("标准化完成。")
                st.json(normalize_result)
            else:
                st.error(
                    f"标准化失败：{normalize_result.get('detail') or normalize_result.get('error')}"
                )
