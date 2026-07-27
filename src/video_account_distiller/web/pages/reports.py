"""Streamlit page — 报告浏览."""

from __future__ import annotations

import json
import os
from typing import Any

import requests
import streamlit as st

st.set_page_config(page_title="报告浏览", page_icon="📄", layout="wide")

st.title("📄 报告浏览")

api_url = st.sidebar.text_input(
    "API 地址",
    value=os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000"),
)
project_path = st.sidebar.text_input(
    "项目路径", value=str(st.session_state.get("project_path", ""))
)


def _api(path: str) -> dict[str, Any]:
    try:
        response = requests.get(f"{api_url}{path}", timeout=10)
        payload: Any = response.json()
        return payload if isinstance(payload, dict) else {"ok": False}
    except (requests.RequestException, ValueError):
        st.error(f"无法连接 API: {api_url}")
        return {"ok": False}


def _report_identity(path: str) -> tuple[str, str] | None:
    parts = path.split("/")
    if len(parts) != 5 or parts[:2] != ["reports", "accounts"] or parts[-1] != "report.json":
        return None
    return parts[2], parts[3]


if st.button("📂 加载所有报告"):
    data = _api(f"/api/projects/{project_path}/reports/")
    if data.get("ok"):
        reports = data.get("data", {}).get("reports", [])
        if reports:
            identities = [_report_identity(path) for path in reports if isinstance(path, str)]
            accounts = sorted({identity[0] for identity in identities if identity is not None})
            st.session_state["report_accounts"] = accounts
            st.session_state["report_list"] = reports

accounts = st.session_state.get("report_accounts", [])
if accounts:
    selected_account = st.selectbox("选择账号查看报告", accounts)

    if st.button(f"📋 加载 {selected_account} 的报告"):
        data = _api(f"/api/projects/{project_path}/reports/accounts/{selected_account}/")
        if data.get("ok"):
            acc_reports = data.get("data", {}).get("reports", [])
            st.session_state["selected_reports"] = acc_reports

    selected_reports = st.session_state.get("selected_reports", [])
    if selected_reports:
        identities = [_report_identity(path) for path in selected_reports if isinstance(path, str)]
        report_ids = sorted(
            {
                identity[1]
                for identity in identities
                if identity is not None and identity[0] == selected_account
            }
        )
        selected_report = st.selectbox("选择报告", report_ids)

        if st.button("📖 打开报告"):
            data = _api(
                f"/api/projects/{project_path}/reports/accounts/{selected_account}/{selected_report}/"
            )
            if data.get("ok"):
                report = data.get("data", {})
                st.session_state["current_report"] = report
                st.session_state["current_report_markdown"] = data.get("markdown")

    report = st.session_state.get("current_report", {})
    if report:
        st.subheader("报告内容")
        view_mode = st.radio("查看方式", ["Markdown", "JSON"], horizontal=True)
        if view_mode == "Markdown":
            markdown = st.session_state.get("current_report_markdown")
            if isinstance(markdown, str) and markdown:
                st.markdown(markdown)
            else:
                st.markdown(
                    "```\n" + json.dumps(report, indent=2, ensure_ascii=False)[:5000] + "\n```"
                )
        else:
            st.json(report)

else:
    st.info("点击「加载所有报告」开始浏览")
