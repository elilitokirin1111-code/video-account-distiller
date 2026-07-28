"""Streamlit self-service account distillation workspace."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

st.set_page_config(page_title="蒸馏工作台", page_icon="🧪", layout="wide")

STAGE_LABELS = {
    "starting": "启动工作流",
    "preflight": "环境与范围预检",
    "ready": "预检完成",
    "collect": "采集账号、视频、指标和评论",
    "collection_complete": "基础数据分析完成",
    "media": "下载并理解视频内容",
    "media_complete": "视频内容分析完成",
    "report": "生成画像、报告和分析上下文",
    "knowledge_export": "生成 GPT/OpenKB 知识包",
    "completed": "全部完成",
    "failed": "执行失败",
}


def _api_url() -> str:
    return str(
        st.session_state.get(
            "api_url",
            os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000"),
        )
    ).rstrip("/")


def _project_path() -> str:
    default = os.environ.get(
        "DISTILLER_DEFAULT_PROJECT",
        str(Path.home() / "video-account-distiller-projects" / "workspace"),
    )
    return str(st.session_state.get("project_path", default))


def _request(
    path: str,
    method: str = "GET",
    *,
    timeout: int = 30,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        response = requests.request(
            method,
            f"{_api_url()}{path}",
            timeout=timeout,
            **kwargs,
        )
        payload: Any = response.json()
        if isinstance(payload, dict):
            if response.ok:
                return payload
            detail = payload.get("detail")
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or response.reason)
            else:
                message = str(detail or response.reason)
            return {"ok": False, "error": {"message": message}, "status_code": response.status_code}
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": {"message": str(exc)}}
    return {"ok": False, "error": {"message": "API 返回了无法识别的数据"}}


def _encoded_project() -> str:
    return quote(_project_path(), safe="")


def _submit_workflow(payload: dict[str, Any], *, dry_run: bool) -> None:
    result = _request(
        f"/api/projects/{_encoded_project()}/workflows/account-distill",
        "POST",
        params={"dry_run": str(dry_run).lower()},
        json=payload,
    )
    if not result.get("ok"):
        st.error(f"任务提交失败：{(result.get('error') or {}).get('message', '未知错误')}")
        return
    task_id = result.get("task_id")
    if not isinstance(task_id, str):
        st.error("API 未返回任务编号")
        return
    st.session_state["active_task_id"] = task_id
    st.session_state["active_task_dry_run"] = dry_run
    st.session_state["active_task_kind"] = "account_distill"
    st.session_state.pop("last_workflow_result", None)
    st.session_state.pop("last_account_id", None)
    st.toast("预检任务已提交" if dry_run else "蒸馏任务已提交", icon="✅")


def _result_metrics(result: dict[str, Any]) -> None:
    account = result.get("account") or {}
    collection = result.get("collection") or {}
    enrichment = (result.get("media_enrichment") or {}).get("enrichment") or {}
    columns = st.columns(6)
    columns[0].metric("账号", account.get("display_name") or account.get("handle") or "-")
    columns[1].metric("当前粉丝", account.get("follower_count_current") or "-")
    columns[2].metric("采集视频", collection.get("videos", 0))
    columns[3].metric("采集评论", collection.get("comments", 0))
    columns[4].metric("已理解视频", enrichment.get("completed_count", 0))
    columns[5].metric(
        "降级/失败",
        f"{enrichment.get('degraded_count', 0)}/{enrichment.get('failed_count', 0)}",
    )

    with st.expander("账号公开快照"):
        st.json(
            {
                "当前粉丝数": account.get("follower_count_current"),
                "当前关注数": account.get("following_count_current"),
                "当前获赞总数": account.get("total_likes_current"),
                "当前作品数": account.get("video_count_current"),
                "认证状态": account.get("verified"),
                "简介": account.get("bio"),
                "快照时间": account.get("snapshot_at"),
            }
        )


def _render_result(result: dict[str, Any]) -> None:
    if result.get("dry_run"):
        st.success("预检完成。确认能力与范围无误后，可以点击“开始完整蒸馏”。")
        plan = result.get("workflow_plan") or {}
        diagnostics = result.get("diagnostics") or {}
        capabilities = diagnostics.get("capabilities") or {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("计划视频", plan.get("media_limit", 0))
        c2.metric("MediaCrawler", "可用" if capabilities.get("mediacrawler_douyin") else "需配置")
        c3.metric("Whisper", "可用" if capabilities.get("video_transcription") else "需配置")
        c4.metric("Ollama", "可用" if capabilities.get("local_vision") else "可选")
        with st.expander("查看完整预检结果"):
            st.json(result)
        return

    st.success("账号蒸馏已完成，数据、视频内容、报告和知识包均已写入项目。")
    _result_metrics(result)
    account = result.get("account") or {}
    account_id = account.get("account_id")

    report = result.get("report") or {}
    if report.get("ok"):
        with st.expander("账号分析报告", expanded=True):
            analysis = report.get("analysis")
            if isinstance(analysis, dict):
                st.json(analysis)
            st.caption("产物：" + "、".join(str(item) for item in report.get("outputs", [])))

    context = result.get("analysis_context")
    if isinstance(context, dict):
        context_json = json.dumps(context, ensure_ascii=False, indent=2)
        st.download_button(
            "下载 GPT 分析上下文",
            data=context_json,
            file_name=f"{account_id or 'account'}-analysis-context.json",
            mime="application/json",
            use_container_width=True,
        )
        with st.expander("查看 GPT 分析上下文"):
            st.json(context)

    knowledge = result.get("knowledge_export") or {}
    if knowledge.get("ok"):
        st.info(
            "GPT/OpenKB 本地知识包已生成。只有点击下方同步并确认模型处理后，"
            "数据才会发送给已配置的 OpenKB 模型。"
        )
        st.caption("知识产物：" + "、".join(str(item) for item in knowledge.get("outputs", [])))

    if isinstance(account_id, str):
        st.session_state["last_account_id"] = account_id

    with st.expander("完整工作流结果"):
        st.json(result)


@st.fragment(run_every=2.0)
def _task_monitor() -> None:
    task_id = st.session_state.get("active_task_id")
    if not isinstance(task_id, str):
        return
    task = _request(f"/api/tasks/{task_id}", timeout=10)
    if not task.get("task_id"):
        st.error(f"无法读取任务：{(task.get('error') or {}).get('message', '未知错误')}")
        return

    status = str(task.get("status", "pending"))
    progress = float(task.get("progress", 0.0))
    stage = str(task.get("stage", "starting"))
    message = str(task.get("message") or STAGE_LABELS.get(stage, stage))
    st.progress(progress, text=f"{STAGE_LABELS.get(stage, stage)} · {message}")
    st.caption(f"任务 {task_id} · 状态 {status} · {progress:.0%}")

    if status == "completed":
        result = task.get("result")
        if isinstance(result, dict):
            if st.session_state.get("active_task_kind") == "openkb_sync":
                st.session_state["last_openkb_result"] = result
            else:
                st.session_state["last_workflow_result"] = result
        st.session_state.pop("active_task_id", None)
        st.session_state.pop("active_task_kind", None)
        st.success("任务已完成")
        st.rerun()
    elif status == "failed":
        error = task.get("error") or {}
        st.session_state.pop("active_task_id", None)
        st.session_state.pop("active_task_kind", None)
        st.error(f"任务失败 [{error.get('code', 'E_UNKNOWN')}]：{error.get('message', '未知错误')}")


st.title("🧪 账号蒸馏工作台")
st.caption("粘贴抖音主页链接，自己完成采集、视频理解、评论分析、账号蒸馏和知识包导出。")

api_url = st.sidebar.text_input("后端 API", value=_api_url())
st.session_state["api_url"] = api_url.rstrip("/")
project_path = st.sidebar.text_input("项目目录", value=_project_path())
st.session_state["project_path"] = project_path

if st.sidebar.button("初始化/检查项目", use_container_width=True):
    initialized = _request(
        "/api/projects/init",
        "POST",
        json={"path": project_path, "name": Path(project_path).name},
    )
    if initialized.get("ok"):
        st.sidebar.success("项目已就绪")
    else:
        st.sidebar.error((initialized.get("error") or {}).get("message", "初始化失败"))

doctor = _request(f"/api/doctor/{_encoded_project()}", timeout=20) if project_path else {}
doctor_value = doctor.get("data")
doctor_data: dict[str, Any] = doctor_value if isinstance(doctor_value, dict) else {}
capabilities = doctor_data.get("capabilities") or {}
with st.sidebar.expander("本机能力"):
    st.write(f"MediaCrawler：{'✅' if capabilities.get('mediacrawler_douyin') else '⚠️'}")
    st.write(f"视频处理：{'✅' if capabilities.get('local_media') else '⚠️'}")
    st.write(f"Whisper：{'✅' if capabilities.get('video_transcription') else '⚠️'}")
    st.write(f"Ollama：{'✅' if capabilities.get('local_vision') else '可选'}")

if st.session_state.get("active_task_id"):
    st.subheader("运行进度")
    _task_monitor()
    st.info("任务在本地后台运行。即使刷新页面，也可以在“设置 → 最近任务”中继续查看。")

with st.expander("最近任务与恢复"):
    task_history = _request("/api/tasks", params={"limit": 20}, timeout=10)
    tasks = task_history.get("tasks")
    if isinstance(tasks, list) and tasks:
        st.dataframe(
            [
                {
                    "任务": item.get("task_id"),
                    "类型": item.get("task_type", "通用任务"),
                    "状态": item.get("status"),
                    "阶段": STAGE_LABELS.get(str(item.get("stage")), item.get("stage", "-")),
                    "进度": f"{float(item.get('progress', 0.0)):.0%}",
                    "更新时间": item.get("updated_at"),
                }
                for item in tasks
                if isinstance(item, dict)
            ],
            use_container_width=True,
            hide_index=True,
        )
        task_ids = [
            str(item["task_id"])
            for item in tasks
            if isinstance(item, dict) and isinstance(item.get("task_id"), str)
        ]
        selected_task = st.selectbox("选择任务", task_ids)
        if st.button("恢复/查看所选任务", use_container_width=True):
            selected = next(
                (
                    item
                    for item in tasks
                    if isinstance(item, dict) and item.get("task_id") == selected_task
                ),
                None,
            )
            if isinstance(selected, dict) and selected.get("status") in {"pending", "running"}:
                st.session_state["active_task_id"] = selected_task
                st.session_state["active_task_kind"] = selected.get("task_type", "account_distill")
            elif isinstance(selected, dict) and isinstance(selected.get("result"), dict):
                selected_result = selected["result"]
                if selected.get("task_type") == "account_distill" or any(
                    key in selected_result for key in ("workflow", "workflow_plan", "collection")
                ):
                    st.session_state["last_workflow_result"] = selected_result
                else:
                    st.session_state["last_openkb_result"] = selected_result
            elif isinstance(selected, dict):
                error = selected.get("error") or {}
                st.error(f"任务失败：{error.get('message', '没有可恢复的结果')}")
            st.rerun()
    else:
        st.caption("暂无任务")

with st.form("self_service_distill_form"):
    st.subheader("1. 采集范围")
    profile_url = st.text_input(
        "抖音主页链接",
        placeholder="https://v.douyin.com/.../ 或 https://www.douyin.com/user/...",
    )
    collection_mode = st.radio(
        "作品采集方式",
        ["指定视频数量", "采集主页全部公开视频"],
        horizontal=True,
        help="全主页模式仍受 1,000 页/20,000 条作品安全上限与调用预算约束。",
    )
    all_videos = collection_mode == "采集主页全部公开视频"

    c1, c2, c3 = st.columns(3)
    with c1:
        video_count = st.number_input(
            "采集视频数",
            min_value=1,
            max_value=20_000,
            value=20,
            disabled=all_videos,
            help="选择全主页模式时不使用此上限。",
        )
    with c2:
        comments_per_video = st.number_input(
            "每个视频采集评论数",
            min_value=0,
            max_value=20,
            value=10,
            help="选择 0 可完全关闭评论采集。",
        )
    with c3:
        comment_video_max = 200 if all_videos else min(int(video_count), 200)
        comment_video_limit = st.number_input(
            "采集评论的视频数",
            min_value=1,
            max_value=comment_video_max,
            value=min(20, comment_video_max),
            disabled=int(comments_per_video) == 0,
            help="可覆盖所选作品，单次最多 200 个视频。",
        )
    estimated_comments = (
        int(comments_per_video) * int(comment_video_limit) if int(comments_per_video) > 0 else 0
    )
    st.caption(
        f"本次评论采集上限：{int(comment_video_limit)} 个视频 × "
        f"{int(comments_per_video)} 条 = {estimated_comments} 条一级评论。"
    )

    st.subheader("2. 视频内容理解")
    analyze_media = st.toggle("下载并分析视频本身", value=True)
    media_limit_max = 20 if all_videos else min(int(video_count), 20)
    m1, m2, m3 = st.columns(3)
    with m1:
        media_limit = st.number_input(
            "视频内容分析数",
            min_value=1,
            max_value=media_limit_max,
            value=media_limit_max,
            disabled=not analyze_media,
            help="视频下载、Whisper 与视觉分析计算量较大，单次最多 20 条。",
        )
    with m2:
        whisper_model = st.selectbox(
            "Whisper 转写模型",
            ["tiny", "base", "small", "medium"],
            index=1,
            disabled=not analyze_media,
        )
    with m3:
        vision_choice = st.selectbox(
            "画面语义分析",
            ["本地 Ollama（推荐）", "仅提取关键帧/镜头"],
            disabled=not analyze_media,
        )

    with st.expander("高级设置"):
        sort = st.selectbox("视频排序", ["latest", "popular"])
        max_provider_calls = st.number_input(
            "最大采集调用数",
            min_value=1,
            max_value=50_000,
            value=5_000 if all_videos else max(100, int(comment_video_limit) + 10),
            help="预检会估算调用量；超过该上限时不会开始真实采集。",
        )
        vision_model = st.text_input("Ollama 视觉模型", value="qwen3-vl:8b")
        export_knowledge = st.checkbox("生成 GPT/OpenKB 本地知识包", value=True)
        strict_media = st.checkbox("任一视频失败即停止", value=False)
        strict_vision = st.checkbox("视觉模型输出异常即停止", value=False)

    st.caption(
        "MediaCrawler 首次运行可能打开 Chrome 登录页；请在浏览器中完成抖音登录。"
        "默认工作流只调用本机 Whisper/Ollama，不产生外部模型费用。"
    )
    public_content_confirmed = st.checkbox(
        "我确认只分析有权处理的公开内容，并理解平台登录与访问规则",
        value=False,
    )
    preview, run = st.columns(2)
    preview_clicked = preview.form_submit_button("先做预检", use_container_width=True)
    run_clicked = run.form_submit_button(
        "开始完整蒸馏",
        type="primary",
        use_container_width=True,
        disabled=not public_content_confirmed,
    )

payload = {
    "url": profile_url,
    "profile": "standard",
    "provider": "mediacrawler",
    "count": None if all_videos else int(video_count),
    "all_videos": all_videos,
    "sort": sort,
    "comments_per_video": int(comments_per_video),
    "comment_video_limit": int(comment_video_limit),
    "max_provider_calls": int(max_provider_calls),
    "confirm_provider_cost": False,
    "media_limit": int(media_limit) if analyze_media else 0,
    "whisper_model": whisper_model,
    "vision_provider": "ollama" if analyze_media and vision_choice.startswith("本地") else None,
    "vision_model": vision_model,
    "strict_media_enrichment": strict_media,
    "strict_vision": strict_vision,
    "export_knowledge": export_knowledge,
}

if preview_clicked or run_clicked:
    if not profile_url.strip():
        st.error("请输入抖音主页链接")
    elif not project_path.strip():
        st.error("请设置项目目录")
    else:
        initialized = _request(
            "/api/projects/init",
            "POST",
            json={"path": project_path, "name": Path(project_path).name},
        )
        if initialized.get("ok"):
            _submit_workflow(payload, dry_run=preview_clicked)
            st.rerun()
        else:
            st.error(f"项目初始化失败：{(initialized.get('error') or {}).get('message')}")

last_result = st.session_state.get("last_workflow_result")
if isinstance(last_result, dict):
    st.divider()
    st.subheader("3. 分析结果")
    _render_result(last_result)

account_id = st.session_state.get("last_account_id")
if isinstance(account_id, str):
    st.divider()
    st.subheader("可选：同步到 OpenKB")
    st.caption("此步骤可能调用你配置的外部模型。应用不会显示或保存模型密钥。")
    confirm_model = st.checkbox("我确认将知识包交给已配置的 OpenKB/模型处理")
    if st.button(
        "同步当前账号到 OpenKB",
        disabled=not confirm_model,
        use_container_width=True,
    ):
        sync = _request(
            f"/api/projects/{_encoded_project()}/knowledge/openkb/accounts/{account_id}/sync",
            "POST",
            json={
                "confirm_model_processing": True,
                "create_kb": True,
                "force": False,
                "max_video_analyses": 20,
            },
        )
        if sync.get("task_id"):
            st.session_state["active_task_id"] = sync["task_id"]
            st.session_state["active_task_kind"] = "openkb_sync"
            st.rerun()
        else:
            st.error(f"OpenKB 同步提交失败：{(sync.get('error') or {}).get('message')}")

openkb_result = st.session_state.get("last_openkb_result")
if isinstance(openkb_result, dict):
    with st.expander("最近一次 OpenKB 同步结果", expanded=True):
        st.json(openkb_result)
