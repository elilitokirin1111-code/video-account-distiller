"""Report center for account analysis artifacts."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

from video_account_distiller.web.ui import (
    badge,
    empty_state,
    section_header,
    setup_page,
)

st.set_page_config(
    page_title="分析报告 · Video Account Distiller",
    page_icon=":material/description:",
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
        response = requests.request(
            method,
            f"{api_url}{path}",
            timeout=30,
            **kwargs,
        )
        payload: Any = response.json()
        return payload if isinstance(payload, dict) else {"ok": False}
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "detail": str(exc)}


def _report_identity(path: str) -> tuple[str, str] | None:
    parts = path.split("/")
    if len(parts) != 5 or parts[:2] != ["reports", "accounts"] or parts[-1] != "report.json":
        return None
    return parts[2], parts[3]


context = setup_page(
    "reports",
    "分析报告",
    "集中管理账号分析产出，快速查看、导出或重新生成报告。",
    eyebrow="REPORT CENTER",
)
encoded_project = quote(context.project_path, safe="")


def _load_report_list() -> None:
    if not context.project_path:
        st.session_state["report_list"] = []
        return
    data = _api(
        context.api_url,
        f"/api/projects/{encoded_project}/reports/",
    )
    if data.get("ok"):
        reports_value = (
            data.get("data", {}).get("reports", []) if isinstance(data.get("data"), dict) else []
        )
        reports = (
            [item for item in reports_value if isinstance(item, str)]
            if isinstance(reports_value, list)
            else []
        )
        st.session_state["report_list"] = reports
    else:
        st.session_state["report_list"] = []


if "report_list" not in st.session_state and context.project_path:
    _load_report_list()

report_paths_value = st.session_state.get("report_list", [])
report_paths = (
    [item for item in report_paths_value if isinstance(item, str)]
    if isinstance(report_paths_value, list)
    else []
)
identities = [identity for path in report_paths if (identity := _report_identity(path)) is not None]
accounts = sorted({identity[0] for identity in identities})

with st.container(border=True):
    filter_columns = st.columns([1.2, 1.2, 1, 0.55])
    with filter_columns[0]:
        keyword = st.text_input(
            "搜索报告",
            placeholder="账号或报告编号",
        )
    with filter_columns[1]:
        account_filter = st.selectbox(
            "账号",
            ["全部账号", *accounts],
        )
    with filter_columns[2]:
        status_filter = st.selectbox(
            "状态",
            ["全部状态", "已生成"],
        )
    with filter_columns[3]:
        if st.button(
            "刷新",
            icon=":material/refresh:",
            use_container_width=True,
            disabled=not bool(context.project_path),
        ):
            _load_report_list()
            st.rerun()

needle = keyword.strip().casefold()
filtered_identities = [
    identity
    for identity in identities
    if (account_filter == "全部账号" or identity[0] == account_filter)
    and (not needle or needle in f"{identity[0]} {identity[1]}".casefold())
]

section_header(
    "报告列表",
    f"共 {len(filtered_identities)} 份报告，可查看 Markdown 或结构化 JSON。",
)
if filtered_identities:
    for row_start in range(0, len(filtered_identities[:18]), 3):
        card_columns = st.columns(3, gap="large")
        row_items = filtered_identities[:18][row_start : row_start + 3]
        for column, (account_id, report_id) in zip(
            card_columns,
            row_items,
            strict=False,
        ):
            with column:
                with st.container(border=True):
                    st.markdown(
                        badge("已生成", "success"),
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"#### {account_id} 账号分析")
                    st.caption(f"报告编号 · {report_id}")
                    metadata_columns = st.columns(2)
                    metadata_columns[0].markdown("**样本规模**")
                    metadata_columns[0].caption("以报告记录为准")
                    metadata_columns[1].markdown("**产物格式**")
                    metadata_columns[1].caption("Markdown / JSON")
                    st.markdown(
                        f"{badge('账号体检', 'neutral')} {badge('内容策略', 'neutral')}",
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "查看报告",
                        key=f"open_report_{account_id}_{report_id}",
                        type="primary",
                        icon=":material/visibility:",
                        use_container_width=True,
                    ):
                        data = _api(
                            context.api_url,
                            f"/api/projects/{encoded_project}/reports/accounts/"
                            f"{quote(account_id, safe='')}/{quote(report_id, safe='')}/",
                        )
                        if data.get("ok"):
                            st.session_state["current_report"] = data.get("data", {})
                            st.session_state["current_report_markdown"] = data.get("markdown")
                            st.session_state["current_report_account"] = account_id
                            st.session_state["current_report_id"] = report_id
                            st.rerun()
                        else:
                            st.error(f"报告读取失败：{data.get('detail') or data.get('error')}")
else:
    empty_state(
        "没有找到报告",
        "完成账号蒸馏后，报告会自动出现在这里；也可以调整筛选条件。",
        mark="R",
    )

report = st.session_state.get("current_report")
if isinstance(report, dict) and report:
    section_header("报告详情", "在阅读视图和结构化数据之间切换，并导出当前报告。")
    with st.container(border=True):
        detail_title, detail_actions = st.columns([2.4, 1.6], vertical_alignment="center")
        account_id = str(st.session_state.get("current_report_account") or "当前账号")
        report_id = str(st.session_state.get("current_report_id") or "latest")
        detail_title.markdown(f"### {account_id} · {report_id}")
        with detail_actions:
            download_json, regenerate = st.columns(2)
            download_json.download_button(
                "导出 JSON",
                data=json.dumps(report, ensure_ascii=False, indent=2),
                file_name=f"{account_id}-{report_id}.json",
                mime="application/json",
                icon=":material/download:",
                use_container_width=True,
            )
            if regenerate.button(
                "重新生成",
                icon=":material/autorenew:",
                use_container_width=True,
            ):
                regenerate_result = _api(
                    context.api_url,
                    f"/api/projects/{encoded_project}/report/{quote(account_id, safe='')}",
                    "POST",
                    json={"sample_size": 40},
                )
                task_id = regenerate_result.get("task_id")
                if task_id:
                    st.success(f"报告重生成任务已提交：{task_id}")
                elif regenerate_result.get("ok"):
                    st.success("报告已重新生成。")
                else:
                    st.error(
                        f"提交失败："
                        f"{regenerate_result.get('detail') or regenerate_result.get('error')}"
                    )

        markdown_tab, json_tab = st.tabs(["阅读报告", "结构化数据"])
        with markdown_tab:
            markdown = st.session_state.get("current_report_markdown")
            if isinstance(markdown, str) and markdown:
                st.markdown(markdown)
                st.download_button(
                    "导出 Markdown",
                    data=markdown,
                    file_name=f"{account_id}-{report_id}.md",
                    mime="text/markdown",
                    icon=":material/download:",
                )
            else:
                st.markdown(
                    "```json\n" + json.dumps(report, indent=2, ensure_ascii=False)[:5000] + "\n```"
                )
        with json_tab:
            st.json(report)
