"""Streamlit page — 报告浏览."""

from __future__ import annotations

import json
import os

import requests
import streamlit as st

st.set_page_config(page_title="报告浏览", page_icon="📄", layout="wide")

st.title("📄 报告浏览")

api_url = st.sidebar.text_input(
    "API 地址",
    value=os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000"),
)
project_path = st.sidebar.text_input("项目路径", value=str(st.session_state.get("project_path", "")))


def _api(path: str) -> dict:
    try:
        r = requests.get(f"{api_url}{path}", timeout=10)
        return r.json()
    except requests.ConnectionError:
        st.error(f"无法连接 API: {api_url}")
        return {"ok": False}


if st.button("📂 加载所有报告"):
    data = _api(f"/api/projects/{project_path}/reports/")
    if data.get("ok"):
        reports = data.get("data", {}).get("reports", [])
        if reports:
            accounts = sorted({r.split("/")[0] for r in reports if isinstance(r, str)})
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
        report_ids = sorted({r.split("/")[1] for r in selected_reports if isinstance(r, str) and len(r.split("/")) > 1})
        selected_report = st.selectbox("选择报告", report_ids)

        if st.button("📖 打开报告"):
            data = _api(f"/api/projects/{project_path}/reports/accounts/{selected_account}/{selected_report}/")
            if data.get("ok"):
                report = data.get("data", {})
                st.session_state["current_report"] = report

    report = st.session_state.get("current_report", {})
    if report:
        st.subheader("报告内容")
        view_mode = st.radio("查看方式", ["Markdown", "JSON"], horizontal=True)
        if view_mode == "Markdown":
            # 尝试加载对应的 .md 文件
            md_data = _api(
                f"/api/projects/{project_path}/reports/{selected_reports[0].replace('report.json', 'report.md')}"
                if "selected_reports" in st.session_state and st.session_state["selected_reports"]
                else ""
            )
            if md_data.get("ok"):
                st.markdown(md_data.get("data", "无内容"))
            else:
                st.markdown("```\n" + json.dumps(report, indent=2, ensure_ascii=False)[:5000] + "\n```")
        else:
            st.json(report)

else:
    st.info("点击「加载所有报告」开始浏览")
