"""Streamlit page — 抖音主页一键分析.

输入抖音主页链接，自动完成：
  采集 → 导入 → 标准化 → 指标计算 → 报告 → 评论分析 → 账号提炼
"""

from __future__ import annotations

import os
import time

import requests
import streamlit as st

st.set_page_config(page_title="主页采集分析", page_icon="🎯", layout="wide")

st.title("🎯 抖音主页一键分析")
st.caption("粘贴抖音主页链接，一键拉取公开视频数据并自动生成账号分析报告")

# ── API 连接 ──────────────────────────────────────────────────────────
api_url = st.sidebar.text_input(
    "API 地址",
    value=os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000"),
)
project_path = st.sidebar.text_input(
    "项目路径", value=str(st.session_state.get("project_path", ""))
)

st.sidebar.divider()
st.sidebar.subheader("🔑 前置条件")
st.sidebar.markdown("""
1. 申请 TikHub API Key：[tikhub.dev](https://tikhub.dev)
2. 设置环境变量：`TIKHUB_API_KEY=你的key`
3. 确保 API 服务已启动
""")

st.sidebar.divider()
st.sidebar.caption("💡 先在「设置」页测试 API 连接，再使用本页功能。")


# ── 表单 ──────────────────────────────────────────────────────────────

with st.form("collection_form"):
    col_url, col_count = st.columns([3, 1])
    with col_url:
        profile_url = st.text_input(
            "📎 抖音主页链接",
            placeholder="https://www.douyin.com/user/MS4wLjABAAAA...",
            help="抖音创作者的主页 URL",
        )
    with col_count:
        count = st.number_input("采集视频数", min_value=1, max_value=100, value=10,
                                help="拉取最近 N 个视频（最多 100）")

    col1, col2, col3 = st.columns(3)
    with col1:
        sort = st.selectbox("排序方式", ["latest", "popular"],
                            help="latest=最新发布, popular=最热门")
    with col2:
        comments_per_video = st.number_input("每条视频采集评论数", min_value=0, max_value=20, value=0,
                                             help="0=不采集评论。拉取评论会产生额外 API 费用")
    with col3:
        comment_video_limit = st.number_input("评论采集视频上限", min_value=1, max_value=10, value=3,
                                              help="最多对几个视频拉取评论")

    submitted = st.form_submit_button("🔍 先预览 (dry-run)", type="secondary", use_container_width=True)
    confirm = st.form_submit_button("🚀 确认采集分析 (需要付费)", type="primary", use_container_width=True)


# ── 处理 ──────────────────────────────────────────────────────────────

def _submit(dry_run: bool) -> None:
    if not profile_url:
        st.error("请输入抖音主页链接")
        return
    if not project_path:
        st.error("请在左侧输入项目路径")
        return

    with st.spinner("提交采集任务..."):
        try:
            r = requests.post(
                f"{api_url}/api/projects/{project_path}/collection/analyze",
                json={
                    "url": profile_url,
                    "count": count,
                    "sort": sort,
                    "comments_per_video": comments_per_video,
                    "comment_video_limit": comment_video_limit,
                    "confirm_provider_cost": not dry_run,
                },
                params={"dry_run": str(dry_run).lower()},
                timeout=30,
            )
            data = r.json()
        except Exception as exc:
            st.error(f"请求失败: {exc}")
            return

    if not data.get("ok"):
        error = data.get("detail") or data.get("error", {}).get("message", "未知错误")
        st.error(f"任务创建失败: {error}")
        return

    task_id = data.get("task_id")
    if not task_id:
        # dry-run returns inline result
        st.json(data)
        return

    # ── 轮询任务状态 ──────────────────────────────────────────────
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    start = time.time()

    for tick in range(180):  # max 6 min
        try:
            tr = requests.get(f"{api_url}/api/tasks/{task_id}", timeout=10)
            td = tr.json()
        except Exception:
            time.sleep(2)
            continue

        status = td.get("status", "?")
        elapsed = int(time.time() - start)
        status_placeholder.info(f"⏳ {status} — 已等待 {elapsed} 秒")

        if status == "completed":
            progress_bar.progress(1.0)
            status_placeholder.success(f"✅ 分析完成！耗时 {elapsed} 秒")
            result = td.get("result", {})
            _show_result(result)
            return
        elif status == "failed":
            progress_bar.progress(1.0)
            err = td.get("error", {})
            status_placeholder.error(f"❌ 采集失败: {err.get('message', '未知错误')}")
            return

        progress_bar.progress(min(tick / 60, 0.95))
        time.sleep(2)

    status_placeholder.warning("⏰ 等待超时，请稍后手动查询任务状态")


def _show_result(result: dict) -> None:
    if not result:
        return

    st.divider()
    st.subheader("📊 采集结果")

    account = result.get("account", {})
    collection = result.get("collection", {})

    # 账号信息
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("昵称", account.get("display_name") or account.get("handle", "-"))
    with c2:
        st.metric("账号 ID", account.get("account_id", "-"))
    with c3:
        st.metric("采集视频数", collection.get("videos", 0))
    with c4:
        st.metric("评论数", collection.get("comments", 0))

    # 报告
    report = result.get("report", {})
    if report.get("ok"):
        st.success("✅ 账号健康报告已生成")
        with st.expander("📄 查看报告数据"):
            st.json(report.get("analysis", {}))

    # 提炼
    distillation = result.get("distillation", {})
    if distillation.get("ok"):
        st.success("✅ 账号提炼已生成")
        with st.expander("🧠 查看提炼结果"):
            st.json(distillation.get("distillation", {}))

    # 评论分析
    comment_analysis = result.get("comment_analysis", {})
    if comment_analysis and comment_analysis.get("ok"):
        st.success("✅ 评论分析已完成")
        with st.expander("💬 查看评论分析"):
            st.json(comment_analysis.get("analysis", {}))

    # 完整 JSON
    with st.expander("📋 完整结果 JSON"):
        st.json(result)


if submitted:
    _submit(dry_run=True)

if confirm:
    _submit(dry_run=False)
