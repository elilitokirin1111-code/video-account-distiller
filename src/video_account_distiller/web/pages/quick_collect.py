"""Streamlit self-service account distillation workspace."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

from video_account_distiller.web import web_state
from video_account_distiller.web.ui import (
    section_header,
    setup_page,
    stepper,
    task_progress_card,
)

st.set_page_config(
    page_title="采集任务 · Video Account Distiller",
    page_icon=":material/add_task:",
    layout="wide",
    initial_sidebar_state="expanded",
)

STAGE_LABELS = {
    "starting": "启动工作流",
    "preflight": "环境与范围预检",
    "ready": "预检完成",
    "collect": "采集账号、视频、指标和评论",
    "collection_complete": "基础数据分析完成",
    "resuming": "从安全检查点恢复",
    "media": "下载并理解视频内容",
    "media_reparse": "重新解析所选视频",
    "media_complete": "视频内容分析完成",
    "report": "生成画像、报告和分析上下文",
    "knowledge_export": "生成运营学习报告与证据附件",
    "model_request": "生成 GPT 分析",
    "completed": "全部完成",
    "failed": "执行失败",
    "cancelling": "正在安全取消",
    "cancelled": "已取消",
}

# 云端深度分析服务商与模型选项（模块级共享：GPT 分析页与任务表单都会用到）。
provider_labels = {
    "DeepSeek": "deepseek",
    "OpenAI": "openai",
    "阿里云百炼": "bailian",
}
models_by_provider = {
    "openai": {
        "均衡（GPT-5.6 Terra）": "gpt-5.6-terra",
        "高质量（GPT-5.6 Sol）": "gpt-5.6-sol",
        "高效率（GPT-5.6 Luna）": "gpt-5.6-luna",
    },
    "bailian": {
        "千问 qwen-max（质量优先，推荐）": "qwen-max",
        "千问 qwen-plus（均衡）": "qwen-plus",
        "千问 qwen-turbo（高性价比）": "qwen-turbo",
        "千问 qwen3.7-max": "qwen3.7-max",
        "千问 qwen3.7-plus": "qwen3.7-plus",
        "千问 qwen-long（长上下文）": "qwen-long",
    },
    "deepseek": {
        "高性价比深度蒸馏（DeepSeek V4 Flash）": "deepseek-v4-flash",
        "质量优先（DeepSeek V4 Pro）": "deepseek-v4-pro",
        "DeepSeek Chat": "deepseek-chat",
    },
}


def _api_url() -> str:
    value = str(st.session_state.get("api_url") or "").strip().rstrip("/")
    if not value:
        value = os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000").rstrip("/")
    if not value.startswith(("http://", "https://")):
        value = f"http://{value}"
    return value


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
            elif isinstance(detail, dict):
                message = str(detail.get("message") or response.reason)
            else:
                message = str(detail or response.reason)
            return {"ok": False, "error": {"message": message}, "status_code": response.status_code}
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": {"message": str(exc)}}
    return {"ok": False, "error": {"message": "API 返回了无法识别的数据"}}


def _encoded_project() -> str:
    return quote(_project_path(), safe="")


def _render_single_video_section(project_path: str) -> None:
    """Single-video entry: collect one interesting video by URL into the kernel.

    The deep distillation needs local transcription, so after collection the
    page guides the user to the one-command CLI (distiller video analyze) that
    downloads, transcribes, deep-distills, and optionally pushes to WeKnora.
    """
    section_header(
        "单视频蒸馏",
        "对一条感兴趣的视频做深度拆解，不关注其账号整体：采集入库后，"
        "本地转写、云端深度分析与 WeKnora 导入由一条命令完成。",
    )
    st.markdown(
        '<div class="ds-form-intro">适合“不关注这位博主，但这条视频很符合想法”的场景。'
        "TikHub API（付费，需 TIKHUB_API_KEY）或 MediaCrawler（本地浏览器，需手动登录抖音）。"
        "短链请先在浏览器打开后复制完整地址。</div>",
        unsafe_allow_html=True,
    )
    with st.form("single_video_collect_form"):
        video_url = st.text_input(
            "抖音视频链接",
            value=str(st.session_state.get("last_single_video_url") or ""),
            placeholder="https://www.douyin.com/video/<id>",
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            video_provider = st.selectbox(
                "采集方式",
                ["tikhub", "mediacrawler"],
                index=0,
                help="TikHub：付费 API；MediaCrawler：本地浏览器手动登录。",
            )
        with c2:
            video_comments = st.number_input("采集评论数", min_value=0, max_value=200, value=0)
        with c3:
            confirm_cost = st.checkbox(
                "我已知晓并确认采集费用/浏览器登录",
                value=False,
                help="TikHub 为一次性计费调用；MediaCrawler 会打开浏览器等待手动登录。",
            )
        submitted = st.form_submit_button(
            "采集这条视频",
            type="primary",
            disabled=not video_url.strip(),
            use_container_width=True,
        )
    if submitted:
        if not confirm_cost:
            st.error("请先勾选确认；TikHub 为计费调用，MediaCrawler 会打开浏览器等待手动登录。")
        elif project_path:
            st.session_state["last_single_video_url"] = video_url.strip()
            with st.spinner("正在采集单条视频并入库…"):
                response = _request(
                    f"/api/projects/{_encoded_project()}/collection/analyze-video-url",
                    method="POST",
                    timeout=180,
                    json={
                        "url": video_url.strip(),
                        "provider": video_provider,
                        "comments_per_video": int(video_comments),
                        "confirm_provider_cost": True,
                    },
                )
            if response.get("ok"):
                st.session_state["last_single_video"] = response
                st.success("采集完成，视频已写入当前工作区。")
            else:
                st.error(str(response.get("error", {}).get("message") or "单视频采集失败"))
        else:
            st.error("尚未选择工作区，请先在左侧边栏设置工作区。")

    last = st.session_state.get("last_single_video")
    if isinstance(last, dict) and last.get("ok"):
        collection = last.get("collection") or {}
        st.markdown("#### 采集结果")
        st.json(
            {
                "标题": last.get("title"),
                "platform_video_id": last.get("platform_video_id"),
                "video_id": last.get("video_id"),
                "account_id": last.get("account_id"),
                "视频数": collection.get("videos"),
                "评论数": collection.get("comments"),
                "原始证据": collection.get("raw_artifact"),
                "告警": collection.get("warnings"),
            }
        )
        st.info(
            "下一步（在命令行完成，需要本地 Whisper 环境与工作区）:\n\n"
            "```bash\n"
            f'distiller video analyze --project "{project_path}" \\\n'
            f'  --url "{last.get("url")}" --whisper-model base --deep \\\n'
            "  --deep-provider cloud   # 云端深度分析（选材/表现/拍摄/可复制清单）\n"
            "  --weknora-kb-id <知识库ID>   # 可选：导入 WeKnora\n"
            "```\n\n"
            "短链需先展开为完整地址；Whisper 转写是深度蒸馏的字幕来源。",
            icon=":material/terminal:",
        )
    elif last is not None:
        st.error(str(last.get("error", {}).get("message") or "上次单视频采集未成功"))


def _account_project() -> str:
    """Return the project that owns the last distilled account when known."""
    remembered = st.session_state.get("last_account_project") or web_state.get_state(
        "last_account_project"
    )
    return str(remembered) if remembered else _project_path()


def _encoded_account_project() -> str:
    return quote(_account_project(), safe="")


def _sanitize_folder_name(name: str) -> str:
    """Strip characters Windows forbids in folder names."""
    cleaned = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    return cleaned or "distill"


def _resolve_account_project(container: str, name: str) -> str:
    """Pick a fresh project folder under the container for one account.

    First run uses ``<container>/<name>``; later runs append ``-1``, ``-2``,
    and so on so repeated distillation of the same account never overwrites
    earlier artifacts.
    """
    base = Path(container).expanduser() / _sanitize_folder_name(name)
    candidate = base
    suffix = 0
    while candidate.exists():
        suffix += 1
        candidate = base.with_name(f"{base.name}-{suffix}")
    return str(candidate)


def _remember_account(result: dict[str, Any]) -> None:
    """Record the distilled account id and its owning project for follow-up analysis."""
    account = result.get("account") or {}
    account_id = account.get("account_id")
    if isinstance(account_id, str):
        st.session_state["last_account_id"] = account_id
        web_state.set_state(last_account_id=account_id)
    project_root = result.get("project_root") or _project_path()
    project_root = str(project_root) if project_root else ""
    if project_root.strip():
        st.session_state["last_account_project"] = project_root
        web_state.set_state(last_account_project=project_root)


def _submit_workflow(payload: dict[str, Any], *, dry_run: bool) -> bool:
    result = _request(
        f"/api/projects/{_encoded_project()}/workflows/account-distill",
        "POST",
        params={"dry_run": str(dry_run).lower()},
        json=payload,
    )
    if not result.get("ok"):
        st.error(f"任务提交失败：{(result.get('error') or {}).get('message', '未知错误')}")
        return False
    task_id = result.get("task_id")
    if not isinstance(task_id, str):
        st.error("API 未返回任务编号")
        return False
    st.session_state["active_task_id"] = task_id
    st.session_state["active_task_dry_run"] = dry_run
    st.session_state["active_task_kind"] = "account_distill"
    web_state.set_state(
        active_task_id=task_id,
        active_task_kind="account_distill",
        active_task_dry_run=dry_run,
    )
    st.session_state.pop("last_workflow_result", None)
    st.session_state.pop("last_account_id", None)
    st.session_state.pop("last_account_project", None)
    web_state.clear_state("last_account_id", "last_account_project")
    st.toast("预检任务已提交" if dry_run else "蒸馏任务已提交", icon="✅")
    return True


def _submit_gpt_analysis(account_id: str, payload: dict[str, Any]) -> bool:
    with st.status("正在提交云端深度分析…", expanded=False) as activity:
        result = _request(
            f"/api/projects/{_encoded_account_project()}/accounts/{account_id}/gpt-analysis",
            "POST",
            json=payload,
        )
    task_id = result.get("task_id")
    if not isinstance(task_id, str):
        activity.update(label="深度分析提交失败", state="error", expanded=True)
        st.error(f"深度分析提交失败：{(result.get('error') or {}).get('message', '未知错误')}")
        return False
    st.session_state["active_task_id"] = task_id
    st.session_state["active_task_kind"] = "gpt_analysis"
    web_state.set_state(active_task_id=task_id, active_task_kind="gpt_analysis")
    st.session_state.pop("last_gpt_analysis", None)
    activity.update(label="深度分析已进入后台队列", state="complete", expanded=False)
    st.toast("深度分析任务已提交；临时密钥未写入任务记录", icon="🤖")
    return True


def _submit_media_reparse(account_id: str, payload: dict[str, Any]) -> bool:
    with st.status("正在创建视频重新解析任务…", expanded=False) as activity:
        result = _request(
            (
                f"/api/projects/{_encoded_account_project()}"
                f"/analyze/accounts/{account_id}/media/reparse"
            ),
            "POST",
            json=payload,
        )
    task_id = result.get("task_id")
    if not isinstance(task_id, str):
        activity.update(label="重新解析提交失败", state="error", expanded=True)
        st.error(f"重新解析提交失败：{(result.get('error') or {}).get('message', '未知错误')}")
        return False
    st.session_state["active_task_id"] = task_id
    st.session_state["active_task_kind"] = "account_media_reparse"
    web_state.set_state(
        active_task_id=task_id,
        active_task_kind="account_media_reparse",
    )
    st.session_state.pop("last_media_reparse", None)
    activity.update(label="重新解析已进入后台队列", state="complete", expanded=False)
    st.toast("视频重新解析任务已提交", icon="🔄")
    return True


def _cancel_task(task_id: str) -> bool:
    with st.status("正在提交安全取消请求…", expanded=False) as activity:
        result = _request(f"/api/tasks/{task_id}/cancel", "POST", timeout=10)
    if result.get("task_id"):
        activity.update(label="已提交安全取消请求", state="complete", expanded=False)
        st.toast("已提交安全取消请求", icon="⏹️")
        return True
    activity.update(label="取消请求失败", state="error", expanded=True)
    st.error(f"取消失败：{(result.get('error') or {}).get('message', '未知错误')}")
    return False


def _retry_task(task_id: str) -> bool:
    with st.status("正在从安全检查点创建重试任务…", expanded=False) as activity:
        result = _request(f"/api/tasks/{task_id}/retry", "POST", timeout=30)
    new_task_id = result.get("task_id")
    if not isinstance(new_task_id, str):
        activity.update(label="重试任务创建失败", state="error", expanded=True)
        st.error(f"重试失败：{(result.get('error') or {}).get('message', '未知错误')}")
        return False
    st.session_state["active_task_id"] = new_task_id
    st.session_state["active_task_kind"] = result.get("task_type", "account_distill")
    web_state.set_state(
        active_task_id=new_task_id,
        active_task_kind=result.get("task_type", "account_distill"),
    )
    st.session_state.pop("last_workflow_result", None)
    activity.update(label="重试任务已进入后台队列", state="complete", expanded=False)
    st.toast("已从最近的安全检查点创建重试任务", icon="🔁")
    return True


def _restore_latest_task_result(task_type: str, session_key: str) -> None:
    """Restore the most recent completed task result into the session."""

    payload = _request("/api/tasks", params={"limit": 30}, timeout=10)
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("task_type") != task_type or task.get("status") != "completed":
            continue
        result = task.get("result")
        if isinstance(result, dict):
            st.session_state[session_key] = result
            if task_type == "account_distill":
                _remember_account(result)
        return


def _coverage_text(completed: Any, requested: Any, ratio: Any) -> str:
    if requested in {None, 0, "0"}:
        return "未请求"
    if isinstance(ratio, (int, float)):
        return f"{completed}/{requested}（{float(ratio):.0%}）"
    return f"{completed}/{requested}"


def _render_coverage(result: dict[str, Any]) -> None:
    coverage = result.get("workflow_coverage")
    if not isinstance(coverage, dict):
        return

    st.subheader("采集与分析完整度")
    st.caption(str(coverage.get("scope_note") or "覆盖率按本次声明范围计算。"))
    account = coverage.get("account_snapshot") or {}
    videos = coverage.get("videos") or {}
    metrics = coverage.get("metrics") or {}
    comments = coverage.get("comments") or {}
    media = coverage.get("media") or {}
    transcripts = coverage.get("transcripts") or {}
    text_analysis = coverage.get("text_analysis") or {}
    vision = coverage.get("vision") or {}

    rows = [
        {
            "环节": "账号公开字段",
            "完成情况": _coverage_text(
                account.get("available_fields"),
                account.get("total_fields"),
                account.get("ratio"),
            ),
            "状态": "已采集" if account.get("available_fields") else "缺失",
        },
        {
            "环节": "公开视频",
            "完成情况": _coverage_text(
                videos.get("collected"),
                videos.get("requested"),
                videos.get("ratio"),
            ),
            "状态": videos.get("status") or "-",
        },
        {
            "环节": "视频互动指标",
            "完成情况": _coverage_text(
                metrics.get("covered_videos"),
                metrics.get("expected_videos"),
                metrics.get("ratio"),
            ),
            "状态": f"{metrics.get('records', 0)} 条快照",
        },
        {
            "环节": "公开一级评论样本",
            "完成情况": _coverage_text(
                comments.get("collected"),
                comments.get("bounded_target"),
                comments.get("ratio"),
            ),
            "状态": comments.get("status") or "-",
        },
        {
            "环节": "视频画面/声音",
            "完成情况": _coverage_text(
                media.get("analyzed"),
                media.get("requested"),
                media.get("ratio"),
            ),
            "状态": (
                f"完成 {media.get('completed', 0)} / 降级 {media.get('degraded', 0)} / "
                f"失败 {media.get('failed', 0)}"
            ),
        },
        {
            "环节": "语音转写",
            "完成情况": _coverage_text(
                transcripts.get("ready"),
                transcripts.get("requested"),
                transcripts.get("ratio"),
            ),
            "状态": "Whisper/已有字幕",
        },
        {
            "环节": "文本内容分析",
            "完成情况": _coverage_text(
                text_analysis.get("ready"),
                text_analysis.get("requested"),
                text_analysis.get("ratio"),
            ),
            "状态": "结构化分析",
        },
        {
            "环节": "画面语义分析",
            "完成情况": _coverage_text(
                vision.get("success"),
                vision.get("requested"),
                vision.get("ratio"),
            ),
            "状态": (
                "未请求"
                if vision.get("status") == "not_requested"
                else f"成功 {vision.get('success', 0)} / 降级 {vision.get('degraded', 0)}"
            ),
        },
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    warnings = coverage.get("warnings")
    if isinstance(warnings, list) and warnings:
        with st.expander(f"覆盖率警告（{len(warnings)}）"):
            for warning in warnings:
                st.write(f"- {warning}")


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
        c4.metric("llama.cpp", "可用" if capabilities.get("local_vision") else "可选")
        with st.expander("查看完整预检结果"):
            st.json(result)
        return

    st.success("账号蒸馏已完成，运营学习报告与数据证据均已写入项目。")
    _result_metrics(result)
    _render_coverage(result)
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
            "运营学习报告与数据证据附件已生成。可在下方“本地 Obsidian 知识库”页签同步，"
            "整个过程不会上传数据；如需云端模型分析，请使用“云端深度分析”。"
        )
        st.caption("知识产物：" + "、".join(str(item) for item in knowledge.get("outputs", [])))

    media_cleanup = result.get("media_cleanup") or {}
    if media_cleanup.get("ok"):
        deleted_count = int(media_cleanup.get("deleted_count") or 0)
        deleted_bytes = int(media_cleanup.get("deleted_bytes") or 0)
        if deleted_count:
            st.info(
                f"已自动删除 {deleted_count} 个处理完成的原视频，释放约 "
                f"{deleted_bytes / 1024 / 1024:.1f} MB；字幕、关键帧和分析结果已保留。"
            )
    elif media_cleanup:
        st.warning("部分原视频未能自动删除，可在完整工作流结果中查看失败路径。")

    _remember_account(result)

    with st.expander("完整工作流结果"):
        st.json(result)


def _render_gpt_analysis(account_id: str) -> None:
    settings = _request(
        f"/api/projects/{_encoded_account_project()}/settings/cloud-model",
        timeout=10,
    )
    permission_enabled = bool(settings.get("allow_cloud_model_upload"))
    if not permission_enabled:
        st.warning(
            "该项目仍保持离线默认值。开启权限只允许后续显式提交；不会上传数据，也不会保存密钥。"
        )
        if st.button("为此项目开启云端模型权限", use_container_width=True):
            with st.status("正在更新云端模型权限…", expanded=False) as activity:
                updated = _request(
                    f"/api/projects/{_encoded_account_project()}/settings/cloud-model",
                    "PUT",
                    json={"allow_cloud_model_upload": True},
                    timeout=10,
                )
                activity.update(
                    label="云端模型权限已开启" if updated.get("ok") else "权限更新失败",
                    state="complete" if updated.get("ok") else "error",
                )
            if updated.get("ok"):
                st.success("项目权限已开启；每次调用仍需单独确认。")
                st.rerun()
            st.error(f"权限更新失败：{(updated.get('error') or {}).get('message', '未知错误')}")
        return

    template_labels = {
        "账号体检": "account_health",
        "内容策略": "content_strategy",
        "30 天增长计划": "growth_plan",
    }
    reasoning_labels = {
        "高（知识蒸馏推荐）": "high",
        "最大": "max",
        "低": "low",
        "无": "none",
        "中": "medium",
    }
    provider_label = st.selectbox("分析服务商", list(provider_labels))
    provider_key = provider_labels[provider_label]
    provider_settings = (settings.get("providers") or {}).get(provider_key) or {}
    credential_configured = bool(provider_settings.get("api_key_configured"))
    credential_source = provider_settings.get("source")
    credential_key = f"cloud_api_key_{provider_key}"
    clear_key = f"clear_cloud_api_key_{provider_key}"
    if st.session_state.pop(clear_key, False):
        st.session_state[credential_key] = ""

    credential_column, save_column, refresh_column, delete_column = st.columns(
        [2.8, 1, 1, 1], vertical_alignment="bottom"
    )
    with credential_column:
        api_key = st.text_input(
            f"{provider_label} API Key",
            type="password",
            key=credential_key,
            placeholder="已安全保存，可留空" if credential_configured else "输入后验证并保存",
            help="密钥保存到当前 Windows 用户的凭据管理器，不写入项目文件或任务数据库。",
        )
    save_clicked = save_column.button(
        "验证并保存",
        key=f"save_cloud_api_key_{provider_key}",
        use_container_width=True,
        disabled=not bool(api_key.strip()),
    )
    refresh_clicked = refresh_column.button(
        "在线识别",
        key=f"probe_cloud_api_key_{provider_key}",
        use_container_width=True,
        disabled=not credential_configured,
    )
    delete_clicked = delete_column.button(
        "删除",
        key=f"delete_cloud_api_key_{provider_key}",
        use_container_width=True,
        disabled=not bool(provider_settings.get("stored_in_os_keyring")),
    )
    probe_key = f"cloud_provider_probe_{provider_key}"
    if save_clicked:
        with st.status(f"正在验证并保存 {provider_label} API…", expanded=False) as activity:
            saved = _request(
                f"/api/cloud-model/credentials/{provider_key}",
                "PUT",
                json={"api_key": api_key},
                timeout=45,
            )
            activity.update(
                label="API 已验证并安全保存" if saved.get("ok") else "API 验证失败",
                state="complete" if saved.get("ok") else "error",
            )
        if saved.get("ok"):
            st.session_state[probe_key] = saved
            st.session_state[clear_key] = True
            st.toast(f"{provider_label} API 已验证并安全保存", icon="✅")
            st.rerun()
        else:
            st.error(f"API 验证失败：{(saved.get('error') or {}).get('message', '未知错误')}")
    if refresh_clicked:
        with st.status(f"正在识别 {provider_label} 可用模型…", expanded=False) as activity:
            checked = _request(
                f"/api/cloud-model/credentials/{provider_key}/probe",
                "POST",
                timeout=45,
            )
            activity.update(
                label="服务商与模型识别完成" if checked.get("ok") else "在线识别失败",
                state="complete" if checked.get("ok") else "error",
            )
        st.session_state[probe_key] = checked
        if checked.get("ok"):
            st.toast(f"已识别 {provider_label} 和可用模型", icon="✅")
    if delete_clicked:
        with st.status(f"正在删除 {provider_label} API Key…", expanded=False) as activity:
            deleted = _request(
                f"/api/cloud-model/credentials/{provider_key}",
                "DELETE",
                timeout=15,
            )
            activity.update(
                label="API Key 已删除" if deleted.get("ok") else "API Key 删除失败",
                state="complete" if deleted.get("ok") else "error",
            )
        if deleted.get("ok"):
            st.session_state.pop(probe_key, None)
            st.session_state[clear_key] = True
            st.toast(f"已删除保存的 {provider_label} API Key")
            st.rerun()

    probe = st.session_state.get(probe_key)
    if credential_configured and not isinstance(probe, dict):
        with st.spinner(f"正在读取 {provider_label} 可用模型…"):
            probe = _request(
                f"/api/cloud-model/credentials/{provider_key}/probe",
                "POST",
                timeout=45,
            )
        st.session_state[probe_key] = probe
    online_models = probe.get("models", []) if isinstance(probe, dict) and probe.get("ok") else []
    # 模型下拉始终展示该服务商的全部兼容选项：服务商在线模型 ID 与本地枚举
    # 命名可能不一致（例如百炼返回 qwen-max 而枚举为 qwen-max-latest），
    # 精确过滤会导致 qwen 选项消失。在线识别只用于连接状态展示。
    model_labels = models_by_provider[provider_key]
    if credential_configured:
        st.success(
            f"{provider_label} API 已保存并可持续使用"
            + (f"；来源：{credential_source}" if credential_source else "")
            + (f"；在线识别 {len(online_models)} 个模型" if online_models else "")
        )
    elif isinstance(probe, dict) and not probe.get("ok"):
        st.error(f"在线识别失败：{(probe.get('error') or {}).get('message', '未知错误')}")

    model_column, template_column, reasoning_column = st.columns(3)
    with model_column:
        model_label = st.selectbox("分析模型", list(model_labels))
    with template_column:
        template_label = st.selectbox("分析模板", list(template_labels))
    with reasoning_column:
        reasoning_label = st.selectbox("推理强度", list(reasoning_labels))
    with st.spinner("正在核对可用分析证据…"):
        scope = _request(
            (
                f"/api/projects/{_encoded_account_project()}/accounts/{account_id}"
                "/analysis-context?max_video_analyses=1"
            ),
            timeout=30,
        )
    availability = scope.get("data_availability") or {}
    analyzed_available = max(1, int(availability.get("analyzed_videos_available") or 1))
    detail_max = min(analyzed_available, 1_000)
    max_video_analyses = st.number_input(
        "纳入逐视频详细证据数",
        min_value=1,
        max_value=detail_max,
        value=detail_max,
        step=1,
        key=f"gpt_max_video_analyses_{account_id}",
        help=(
            "账号聚合规律始终覆盖全部已分析视频；这里控制额外送入模型的压缩逐视频证据，"
            "最多 1000 条。"
        ),
    )
    preview_request = {
        "provider": provider_key,
        "model": model_labels[model_label],
        "template": template_labels[template_label],
        "reasoning_effort": reasoning_labels[reasoning_label],
        "max_video_analyses": int(max_video_analyses),
        "confirm_cloud_upload": False,
        "confirm_cost": False,
    }
    with st.spinner("正在计算模型上下文与费用预览…"):
        preview = _request(
            f"/api/projects/{_encoded_account_project()}/accounts/{account_id}/gpt-analysis/preview",
            "POST",
            json=preview_request,
            timeout=30,
        )
    preview_ok = bool(preview.get("ok"))
    if preview_ok:
        data_scope = preview.get("data_scope") or {}
        cost_preview = preview.get("cost_preview") or {}
        pricing = cost_preview.get("pricing") or {}
        context_bytes = data_scope.get("context_bytes")
        context_size = (
            f"{context_bytes / 1024:.1f} KB" if isinstance(context_bytes, int) else "未知"
        )
        currency = str(cost_preview.get("currency") or pricing.get("currency") or "")
        currency_symbol = "¥" if currency == "CNY" else "$" if currency == "USD" else ""
        maximum_cost = cost_preview.get("conservative_maximum")
        maximum_cost_label = (
            f"{currency_symbol}{maximum_cost:.4f} {currency}".strip()
            if isinstance(maximum_cost, int | float)
            else "未知"
        )
        st.info(
            f"调用前预览：{preview.get('model')} / {preview.get('template')}；"
            f"上下文 {context_size}；"
            f"最多纳入 {data_scope.get('max_video_analyses')} 条视频分析；"
            f"保守费用上限约 {maximum_cost_label}。"
        )
        st.caption(
            f"当前费率快照 {pricing.get('snapshot')}：输入 {currency_symbol}{pricing.get('input')}"
            f"/百万 token，缓存输入 {currency_symbol}{pricing.get('cached_input')}/百万 token，"
            f"输出 {currency_symbol}{pricing.get('output')}/百万 token。"
            f"该上限按 UTF-8 字节和全量未缓存输入保守估算；最终以{provider_label}账单为准。"
        )
        with st.expander("查看数据范围、脱敏项与请求指纹"):
            st.json(
                {
                    "data_scope": data_scope,
                    "request_fingerprints": preview.get("request_fingerprints"),
                    "cost_preview": cost_preview,
                }
            )
    else:
        st.error(f"无法生成调用预览：{(preview.get('error') or {}).get('message', '未知错误')}")

    if not credential_configured:
        st.info("请在上方填写 API Key，并点击“验证并保存”。")

    with st.form("gpt_account_analysis_form", clear_on_submit=False):
        confirm_cloud_upload = st.checkbox(
            f"我确认将上方预览所代表的受限、脱敏上下文发送给{provider_label}"
        )
        confirm_cost = st.checkbox(
            f"我理解本次模型 API 调用可能产生费用，实际费用以{provider_label}账户为准"
        )
        submitted = st.form_submit_button(
            "生成可审计的深度分析",
            type="primary",
            use_container_width=True,
            disabled=not preview_ok or not credential_configured,
        )

    if submitted:
        if not confirm_cloud_upload or not confirm_cost:
            st.error("请同时确认数据外发与潜在费用。")
        else:
            accepted = _submit_gpt_analysis(
                account_id,
                {
                    "provider": provider_key,
                    "model": model_labels[model_label],
                    "template": template_labels[template_label],
                    "reasoning_effort": reasoning_labels[reasoning_label],
                    "max_video_analyses": int(max_video_analyses),
                    "confirm_cloud_upload": True,
                    "confirm_cost": True,
                },
            )
            if accepted:
                st.rerun()

    latest = st.session_state.get("last_gpt_analysis")
    if isinstance(latest, dict):
        analysis = latest.get("analysis")
        st.success(
            "深度分析已完成并写入本地审计工件。"
            if not latest.get("already_generated")
            else "已复用同一上下文与设置的现有分析，未重复调用 API。"
        )
        if isinstance(analysis, dict):
            result = analysis.get("result")
            if isinstance(result, dict):
                st.markdown(f"**摘要：** {result.get('executive_summary', '')}")
                cards = result.get("knowledge_cards") or []
                if cards:
                    st.markdown("#### 已形成的经营知识卡")
                    for card in cards:
                        with st.container(border=True):
                            st.markdown(f"**{card.get('title', '未命名知识卡')}**")
                            st.write(card.get("claim") or "")
                            st.caption(
                                f"Level {card.get('maturity_level', 0)} · "
                                f"{card.get('knowledge_type', 'hypothesis')} · "
                                f"目标指标：{card.get('target_metric', '-')}"
                            )
                            st.markdown(f"**决策：** {card.get('decision', '-')}")
                            st.markdown(f"**反证：** {card.get('falsifier', '-')}")
                            st.markdown(f"**停止条件：** {card.get('stop_condition', '-')}")
                with st.expander("查看结构化分析", expanded=True):
                    st.json(result)
            st.download_button(
                "下载深度分析 JSON",
                data=json.dumps(analysis, ensure_ascii=False, indent=2),
                file_name=f"{account_id}-gpt-analysis.json",
                mime="application/json",
                use_container_width=True,
            )
        st.caption("审计产物：" + "、".join(str(item) for item in latest.get("outputs", [])))
        audit = latest.get("audit")
        if isinstance(audit, dict):
            with st.expander("查看调用审计（不含密钥与原始响应）"):
                st.json(audit)
        evaluation = latest.get("evaluation")
        if isinstance(evaluation, dict):
            with st.expander("查看固定问题集评估"):
                st.json(evaluation)


def _render_media_reparse(account_id: str) -> None:
    st.caption(
        "无需重新采集账号：可只重试失败/降级的视频，也可手动指定视频。"
        "历史分析工件会保留，成功字幕默认复用。"
    )
    candidates_result = _request(
        (
            f"/api/projects/{_encoded_account_project()}"
            f"/analyze/accounts/{account_id}/media/reparse-candidates"
        ),
        timeout=30,
    )
    candidates = candidates_result.get("candidates")
    if not isinstance(candidates, list):
        st.error(
            "无法读取可重新解析的视频："
            f"{(candidates_result.get('error') or {}).get('message', '未知错误')}"
        )
        return
    if not candidates:
        st.info("当前账号没有可用的已保留视频，请先完成一次 MediaCrawler 采集。")
        return

    retry_ids = [
        str(item["video_id"])
        for item in candidates
        if isinstance(item, dict) and item.get("retry_recommended")
    ]
    st.info(f"已保留 {len(candidates)} 条视频；其中 {len(retry_ids)} 条最近一次解析失败或降级。")
    with st.expander("查看视频解析状态"):
        st.dataframe(
            [
                {
                    "视频": item.get("platform_video_id") or item.get("video_id"),
                    "总体": item.get("status"),
                    "字幕": item.get("transcription_status"),
                    "画面": item.get("vision_status") or "未运行",
                    "文本分析": item.get("text_analysis_status") or "未运行",
                    "建议重试": "是" if item.get("retry_recommended") else "否",
                }
                for item in candidates
                if isinstance(item, dict)
            ],
            use_container_width=True,
            hide_index=True,
        )

    labels = {
        str(item["video_id"]): (
            f"{item.get('platform_video_id') or item['video_id']} · "
            f"{item.get('status', '未知')} / 字幕 {item.get('transcription_status', '未知')}"
        )
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("video_id"), str)
    }
    with st.form("account_media_reparse_form"):
        mode_label = st.radio(
            "重新解析范围",
            ["仅失败或降级（推荐）", "手动选择视频", "当前保留批次"],
            horizontal=True,
        )
        selected_ids: list[str] = []
        if mode_label == "手动选择视频":
            selected_ids = st.multiselect(
                "选择要重新解析的视频",
                options=list(labels),
                format_func=lambda value: labels.get(value, value),
            )
        target_count = (
            len(retry_ids)
            if mode_label.startswith("仅失败")
            else (len(selected_ids) if mode_label == "手动选择视频" else len(candidates))
        )
        limit = st.number_input(
            "本次最多处理",
            min_value=1,
            max_value=20_000,
            value=max(1, target_count),
            help="默认覆盖当前选择的全部视频；超大账号可以主动调小后分批运行。",
        )
        refresh_media = st.checkbox(
            "重新执行画面与音频解析",
            value=True,
            help="关闭时会尽量复用已有媒体分析，只重新生成缺失字幕和文本分析。",
        )
        provider_label = st.selectbox(
            "画面理解方式",
            ["本地 llama.cpp（推荐）", "本地 Ollama", "仅关键帧与镜头"],
        )
        vision_model = st.text_input("视觉模型", value="qwen3-vl-8b")
        whisper_model = st.selectbox(
            "语音模型",
            ["tiny", "base", "small", "medium"],
            index=2,
        )
        submitted = st.form_submit_button(
            "开始重新解析",
            type="primary",
            use_container_width=True,
            disabled=(
                (mode_label.startswith("仅失败") and not retry_ids)
                or (mode_label == "手动选择视频" and not selected_ids)
            ),
        )

    if submitted:
        mode = (
            "failed_or_degraded"
            if mode_label.startswith("仅失败")
            else ("selected" if mode_label == "手动选择视频" else "all")
        )
        accepted = _submit_media_reparse(
            account_id,
            {
                "mode": mode,
                "video_ids": selected_ids,
                "limit": int(limit),
                "refresh_media": refresh_media,
                "whisper_backend": "auto",
                "whisper_model": whisper_model,
                "whisper_batch_size": 8,
                "vision_provider": (
                    "llamacpp"
                    if provider_label.startswith("本地 llama")
                    else ("ollama" if provider_label == "本地 Ollama" else None)
                ),
                "vision_model": vision_model,
            },
        )
        if accepted:
            st.rerun()

    latest = st.session_state.get("last_media_reparse")
    if isinstance(latest, dict):
        if latest.get("no_changes"):
            st.success("当前没有失败或降级项需要重新解析。")
        else:
            enrichment = latest.get("enrichment") or {}
            columns = st.columns(4)
            columns[0].metric("已选择", enrichment.get("selected_count", 0))
            columns[1].metric("完成", enrichment.get("completed_count", 0))
            columns[2].metric("降级", enrichment.get("degraded_count", 0))
            columns[3].metric("失败", enrichment.get("failed_count", 0))
            st.success("重新解析完成，账号蒸馏结果已用新证据重建。")
            cleanup = latest.get("media_cleanup") or {}
            if cleanup.get("ok") and cleanup.get("deleted_count"):
                st.caption(
                    f"已删除 {cleanup.get('deleted_count')} 个重新下载的原视频；"
                    "字幕、关键帧和分析结果仍保留。"
                )


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
    queue_position = task.get("queue_position")
    meta_parts = [f"任务 {task_id}", f"状态 {status}", "每 2 秒自动刷新"]
    if status == "pending" and isinstance(queue_position, int):
        meta_parts.append(
            f"队列第 {queue_position} 位 · 资源组 {task.get('resource_class', 'default')}"
        )
    elif status in {"running", "cancelling"}:
        meta_parts.append("后台持续运行，可安全离开本页")
    task_progress_card(
        STAGE_LABELS.get(stage, stage),
        message,
        progress=progress,
        status=status,
        meta=" · ".join(meta_parts),
    )

    if status in {"pending", "running"}:
        if st.button("安全取消任务", key=f"monitor_cancel_{task_id}", use_container_width=True):
            if _cancel_task(task_id):
                st.rerun()
    elif status == "cancelling":
        st.warning("已收到取消请求，正在等待当前不可中断的本地步骤安全结束。")

    if status == "completed":
        result = task.get("result")
        if isinstance(result, dict):
            task_kind = st.session_state.get("active_task_kind")
            if task_kind == "gpt_analysis":
                st.session_state["last_gpt_analysis"] = result
            elif task_kind == "account_media_reparse":
                st.session_state["last_media_reparse"] = result
            else:
                st.session_state["last_workflow_result"] = result
                _remember_account(result)
        st.session_state.pop("active_task_id", None)
        st.session_state.pop("active_task_kind", None)
        web_state.clear_state("active_task_id", "active_task_kind", "active_task_dry_run")
        st.success("任务已完成")
        st.rerun()
    elif status == "failed":
        error = task.get("error") or {}
        st.error(f"任务失败 [{error.get('code', 'E_UNKNOWN')}]：{error.get('message', '未知错误')}")
        budget_exceeded = error.get("code") == "E_COLLECTION_BUDGET_EXCEEDED"
        retry_column, dismiss_column = st.columns(2)
        if retry_column.button(
            "按自动预算重试" if budget_exceeded else "从安全检查点重试",
            key=f"monitor_retry_{task_id}",
            disabled=not bool(task.get("retryable")),
            use_container_width=True,
        ):
            if _retry_task(task_id):
                st.rerun()
        if dismiss_column.button(
            "关闭提示",
            key=f"monitor_dismiss_{task_id}",
            use_container_width=True,
        ):
            st.session_state.pop("active_task_id", None)
            st.session_state.pop("active_task_kind", None)
            web_state.clear_state("active_task_id", "active_task_kind", "active_task_dry_run")
            st.rerun()
    elif status == "cancelled":
        st.info("任务已安全取消；已完成的不可变数据和分析产物仍保留在项目中。")
        retry_column, dismiss_column = st.columns(2)
        if retry_column.button(
            "从安全检查点继续",
            key=f"monitor_resume_{task_id}",
            disabled=not bool(task.get("retryable")),
            use_container_width=True,
        ):
            if _retry_task(task_id):
                st.rerun()
        if dismiss_column.button(
            "关闭提示",
            key=f"monitor_cancel_dismiss_{task_id}",
            use_container_width=True,
        ):
            st.session_state.pop("active_task_id", None)
            st.session_state.pop("active_task_kind", None)
            web_state.clear_state("active_task_id", "active_task_kind", "active_task_dry_run")
            st.rerun()


context = setup_page(
    "collect",
    "新建账号蒸馏",
    "粘贴账号主页，选择分析范围，然后让系统完成采集、视频理解、运营学习报告和证据沉淀。",
    eyebrow="核心工作流",
)
st.session_state["api_url"] = context.api_url
st.session_state["project_path"] = context.project_path
project_path = context.project_path

# Restore an in-flight task after reloads / theme toggles / reconnects.
if not st.session_state.get("active_task_id"):
    persisted_task = web_state.get_state("active_task_id")
    if isinstance(persisted_task, str):
        st.session_state["active_task_id"] = persisted_task
        st.session_state["active_task_kind"] = web_state.get_state(
            "active_task_kind", "account_distill"
        )
        st.session_state["active_task_dry_run"] = web_state.get_state("active_task_dry_run", False)
# Restore the last distilled account so follow-up analysis works after reloads.
if not st.session_state.get("last_account_id"):
    persisted_account = web_state.get_state("last_account_id")
    if isinstance(persisted_account, str):
        st.session_state["last_account_id"] = persisted_account
if not st.session_state.get("last_account_project"):
    persisted_project = web_state.get_state("last_account_project")
    if isinstance(persisted_project, str):
        st.session_state["last_account_project"] = persisted_project

# Restore the most recent completed results so reloads do not lose records.
if not st.session_state.get("active_task_id"):
    if not st.session_state.get("last_workflow_result"):
        _restore_latest_task_result("account_distill", "last_workflow_result")
    if not st.session_state.get("last_gpt_analysis"):
        _restore_latest_task_result("gpt_account_analysis", "last_gpt_analysis")
    if not st.session_state.get("last_media_reparse"):
        _restore_latest_task_result("account_media_reparse", "last_media_reparse")

if st.session_state.get("active_task_id"):
    active_snapshot = _request(f"/api/tasks/{st.session_state['active_task_id']}", timeout=10)
    active_status = str(active_snapshot.get("status") or "pending")
    active_is_live = active_status in {"pending", "running", "cancelling"}
    active_label = "正在运行的任务" if active_is_live else "上次任务与恢复"
    with st.expander(active_label, expanded=active_is_live, icon=":material/progress_activity:"):
        _task_monitor()

with st.expander("任务记录（高级）"):
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
        selected = next(
            (
                item
                for item in tasks
                if isinstance(item, dict) and item.get("task_id") == selected_task
            ),
            None,
        )
        selected_status = str(selected.get("status")) if isinstance(selected, dict) else ""
        view_column, retry_column, cancel_column = st.columns(3)
        if view_column.button("恢复/查看", use_container_width=True):
            if isinstance(selected, dict) and selected.get("status") in {
                "pending",
                "running",
                "cancelling",
            }:
                st.session_state["active_task_id"] = selected_task
                st.session_state["active_task_kind"] = selected.get("task_type", "account_distill")
            elif isinstance(selected, dict) and isinstance(selected.get("result"), dict):
                selected_result = selected["result"]
                if selected.get("task_type") == "account_distill" or any(
                    key in selected_result for key in ("workflow", "workflow_plan", "collection")
                ):
                    st.session_state["last_workflow_result"] = selected_result
                    _remember_account(selected_result)
                else:
                    st.session_state["last_knowledge_result"] = selected_result
            elif isinstance(selected, dict):
                error = selected.get("error") or {}
                st.error(f"任务失败：{error.get('message', '没有可恢复的结果')}")
            st.rerun()
        if retry_column.button(
            "重试/继续",
            disabled=not (
                isinstance(selected, dict)
                and selected_status in {"failed", "cancelled"}
                and bool(selected.get("retryable"))
            ),
            use_container_width=True,
        ):
            if _retry_task(selected_task):
                st.rerun()
        if cancel_column.button(
            "安全取消",
            disabled=selected_status not in {"pending", "running"},
            use_container_width=True,
        ):
            if _cancel_task(selected_task):
                if isinstance(selected, dict):
                    st.session_state["active_task_id"] = selected_task
                    st.session_state["active_task_kind"] = selected.get(
                        "task_type", "account_distill"
                    )
                st.rerun()
    else:
        st.caption("暂无任务")

saved_template = web_state.get_state("last_collection_template")
if isinstance(saved_template, dict) and not st.session_state.get("last_collection_template"):
    st.session_state["last_collection_template"] = saved_template
template = st.session_state.get("last_collection_template") or {}

stepper(["粘贴主页", "选择范围", "开始蒸馏"], active=1)

# ── 单视频深度蒸馏入口 ────────────────────────────────────────────────
# 针对"不关注该博主、但这条视频符合想法"的场景：粘贴单条视频链接，
# 采集入库后可通过 CLI 完成本地转写与深度蒸馏（distiller video analyze）。
work_mode = st.radio(
    "工作流",
    ["账号蒸馏", "单视频蒸馏"],
    horizontal=True,
    index=0,
    key="collect_work_mode",
)
if work_mode == "单视频蒸馏":
    _render_single_video_section(project_path)
    st.stop()

with st.form("self_service_distill_form"):
    with st.container(border=True):
        st.markdown("#### 01 · 账号主页")
        st.markdown(
            '<div class="ds-form-intro">默认通过本机浏览器采集公开数据，'
            "视频、转写和分析结果保存在当前工作区。高级采集源与模型设置已收纳。</div>",
            unsafe_allow_html=True,
        )
        provider = (
            "TikHub API（付费，需要环境变量 TIKHUB_API_TOKEN）"
            if template.get("provider") == "tikhub"
            else "MediaCrawler（本地浏览器，需手动登录抖音）"
        )
        profile_url = st.text_input(
            "抖音账号主页链接",
            value=str(template.get("url") or ""),
            placeholder="https://v.douyin.com/.../ 或 https://www.douyin.com/user/...",
            help="当前自动采集链路支持抖音主页链接。",
        )
    with st.container(border=True):
        st.markdown("#### 02 · 分析范围")
        st.caption("默认分析最近 50 条作品；只有确有需要时才采集全部公开作品。")
        all_videos = st.toggle(
            "采集主页全部公开视频",
            value=bool(template.get("all_videos", False)),
            help="全主页模式受 1,000 页、20,000 条作品和调用预算上限保护。",
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            template_count = template.get("count")
            video_count = st.number_input(
                "采集视频数",
                min_value=1,
                max_value=20_000,
                value=int(template_count) if isinstance(template_count, int) else 50,
                disabled=all_videos,
                help="选择全主页模式时不使用此上限。",
            )
        with c2:
            template_comments = template.get("comments_per_video")
            comments_per_video = st.number_input(
                "每个视频采集评论数",
                min_value=0,
                max_value=20,
                value=(int(template_comments) if isinstance(template_comments, int) else 10),
                help="选择 0 可完全关闭评论采集。",
            )
        with c3:
            comments_cover_all_selected = st.checkbox(
                "评论覆盖本次采集的全部视频",
                value=True,
                disabled=int(comments_per_video) == 0,
                help="提交时直接采用最终的采集数量，不受表单内旧值影响。",
            )
            template_comment_limit = template.get("comment_video_limit")
            custom_comment_video_limit = st.number_input(
                "自定义评论视频数",
                min_value=1,
                max_value=20_000,
                value=(
                    min(int(template_comment_limit), 20_000)
                    if isinstance(template_comment_limit, int)
                    else 50
                ),
                disabled=int(comments_per_video) == 0 or comments_cover_all_selected,
                help="仅在关闭“覆盖全部视频”时生效，安全上限为 20,000 条视频。",
            )
        comment_video_limit = (
            (20_000 if all_videos else int(video_count))
            if comments_cover_all_selected
            else min(
                int(custom_comment_video_limit),
                20_000 if all_videos else int(video_count),
            )
        )
        estimated_comments = (
            int(comments_per_video) * int(comment_video_limit) if int(comments_per_video) > 0 else 0
        )
        st.markdown(
            f"""
            <div class="ds-callout">
              预计规模：{"全部公开视频" if all_videos else f"{int(video_count)} 个视频"}，
              最多采集 {estimated_comments} 条一级评论。
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.markdown("#### 内容理解")
        st.caption(
            "配置语音转写、画面语义、运营学习报告和数据证据附件。"
            "任务成功后会自动删除下载的原视频，保留字幕、关键帧和分析结果。"
        )
        template_media_limit = template.get("media_limit")
        analyze_media = st.toggle(
            "下载并分析视频本身",
            value=(
                int(template_media_limit) > 0 if isinstance(template_media_limit, int) else True
            ),
        )
        media_limit: int | None = None if analyze_media else 0
        if analyze_media:
            st.caption("内容理解将覆盖本次实际采集到的全部视频；旧模板中的 20 条上限不再生效。")

        with st.expander("高级设置", icon=":material/tune:"):
            provider = st.radio(
                "采集源",
                [
                    "MediaCrawler（本地浏览器，需手动登录抖音）",
                    "TikHub API（付费，需要环境变量 TIKHUB_API_TOKEN）",
                ],
                index=0 if template.get("provider") != "tikhub" else 1,
                horizontal=True,
            )
            account_name = st.text_input(
                "结果文件夹名称（可选）",
                value=str(template.get("account_name") or ""),
                placeholder="例如：小许的酒店日记",
                help="留空时使用当前工作区；填写后会创建同名子项目。",
            )
            template_whisper = template.get("whisper_model")
            whisper_index = (
                ["tiny", "base", "small", "medium"].index(template_whisper)
                if template_whisper in ["tiny", "base", "small", "medium"]
                else 2
            )
            template_vision_choice = template.get("vision_provider")
            engine_column, model_column, vision_column = st.columns(3)
            with engine_column:
                whisper_backend = st.selectbox(
                    "转写引擎",
                    ["GPU 加速（自动回退）", "faster-whisper", "原版 Whisper CLI"],
                    index=(
                        1
                        if template.get("whisper_backend") == "faster-whisper"
                        else (2 if template.get("whisper_backend") == "openai-whisper" else 0)
                    ),
                    disabled=not analyze_media,
                )
            with model_column:
                whisper_model = st.selectbox(
                    "语音模型",
                    ["tiny", "base", "small", "medium"],
                    index=whisper_index,
                    disabled=not analyze_media,
                )
            with vision_column:
                vision_choice = st.selectbox(
                    "画面理解",
                    ["本地 llama.cpp（推荐）", "云端 API（对比）", "仅提取关键帧/镜头"],
                    index=(
                        0
                        if template_vision_choice == "llamacpp"
                        else (1 if template_vision_choice == "cloud" else 2)
                    ),
                    disabled=not analyze_media,
                )
            template_sort = template.get("sort")
            sort = st.selectbox(
                "视频排序",
                ["latest", "popular"],
                index=(
                    ["latest", "popular"].index(template_sort)
                    if template_sort in ["latest", "popular"]
                    else 0
                ),
                format_func=lambda value: "最新发布" if value == "latest" else "热度优先",
            )
            max_provider_calls = st.number_input(
                "最大采集调用数（0 = 自动）",
                min_value=0,
                max_value=50_000,
                value=0,
                help=(
                    "建议保持 0，由视频、详情和评论范围自动规划，并继续受 20000 个视频的"
                    "硬性安全边界保护。填写正数时才会启用额外的自定义调用上限。"
                ),
            )
            vision_model = str(template.get("vision_model") or "qwen3-vl-8b")
            if vision_choice.startswith("本地"):
                vision_model = st.text_input(
                    "本地视觉模型",
                    value=vision_model,
                )
            text_source = st.radio(
                "文本分析来源",
                ["本地 llama.cpp（qwen3-8b）", "云端 API（OpenAI 兼容）"],
                index=0 if template.get("text_provider") != "cloud" else 1,
            )
            cloud_base_url = str(template.get("cloud_base_url") or "https://api.deepseek.com")
            cloud_api_key = str(template.get("cloud_api_key") or "")
            cloud_text_model = str(template.get("cloud_text_model") or "deepseek-v4-flash")
            cloud_vision_model = str(template.get("cloud_vision_model") or "qwen-vl-max-latest")
            if text_source.startswith("云端") or vision_choice.startswith("云端"):
                st.caption("云端配置仅用于本次任务；长期密钥请在设置页验证并保存。")
                cloud_endpoint_choices = {
                    "DeepSeek（https://api.deepseek.com）": "https://api.deepseek.com",
                    "阿里云百炼 DashScope（qwen）": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "阿里云百炼 MaaS 工作空间（自定义域名）": "ws-<workspace>.cn-beijing.maas.aliyuncs.com",
                    "自定义": "",
                }
                cloud_endpoint_label = st.selectbox(
                    "云端服务商",
                    list(cloud_endpoint_choices),
                    index=(
                        list(cloud_endpoint_choices).index("阿里云百炼 DashScope（qwen）")
                        if "dashscope" in cloud_base_url
                        else list(cloud_endpoint_choices).index("阿里云百炼 MaaS 工作空间（自定义域名）")
                        if "maas.aliyuncs.com" in cloud_base_url
                        else list(cloud_endpoint_choices).index("DeepSeek（https://api.deepseek.com）")
                        if "deepseek" in cloud_base_url
                        else 0
                    ),
                )
                chosen_endpoint = cloud_endpoint_choices[cloud_endpoint_label]
                # 选择预设服务商时自动带出对应地址，避免"百炼 key + DeepSeek 地址"错配。
                if cloud_endpoint_label != "自定义" and chosen_endpoint:
                    cloud_base_url = chosen_endpoint
                cloud_base_url = st.text_input(
                    "云端服务地址（OpenAI 兼容）",
                    value=cloud_base_url,
                    placeholder=chosen_endpoint or "https://...",
                    help=(
                        "无协议前缀的地址会自动补全 https://。"
                        "选择预设服务商后地址自动带出；百炼 MaaS 域名直接使用即可。"
                    ),
                )
                cloud_api_key = st.text_input(
                    "云端 API Key",
                    type="password",
                    value=cloud_api_key,
                    help="百炼密钥以 sk- 开头，请确保与所选服务商一致；错误配对会在调用时返回 401。",
                )
                cloud_models = st.columns(2)
                with cloud_models[0]:
                    cloud_text_model = st.text_input(
                        "云端文本模型",
                        value=cloud_text_model,
                        help=(
                            "百炼推荐 qwen-max / qwen-plus；DeepSeek 用 deepseek-v4-flash。"
                            "请与所选服务商一致。"
                        ),
                    )
                with cloud_models[1]:
                    cloud_vision_model = st.text_input(
                        "云端视觉模型",
                        value=cloud_vision_model,
                        help="百炼默认 qwen-vl-max-latest。",
                    )
            export_knowledge = st.checkbox(
                "生成运营学习报告与数据证据附件（用于 Obsidian 与归档）",
                value=bool(template.get("export_knowledge", True)),
            )
            knowledge_synthesis = st.checkbox(
                "生成账号级综合知识卡（云端深度分析）",
                value=bool(template.get("knowledge_analysis")),
                help=(
                    "在事实与模式整理完成后运行一次高推理强度的账号级综合，"
                    "输出机制、竞争解释、反证、决策、成功与停止条件。"
                ),
            )
            confirm_knowledge_upload = False
            confirm_knowledge_cost = False
            knowledge_analysis_payload: dict[str, Any] | None = None
            if knowledge_synthesis:
                saved_analysis = template.get("knowledge_analysis") or {}
                saved_provider = str(
                    (saved_analysis if isinstance(saved_analysis, dict) else {}).get("provider")
                    or "deepseek"
                )
                provider_label_options = list(provider_labels)
                knowledge_provider_label = st.selectbox(
                    "知识分析服务商",
                    provider_label_options,
                    index=(
                        provider_label_options.index("阿里云百炼")
                        if saved_provider == "bailian"
                        else provider_label_options.index("OpenAI")
                        if saved_provider == "openai"
                        else 0
                    ),
                    key="knowledge_provider_label",
                    help="选择「阿里云百炼」即可使用 qwen 系列模型。",
                )
                knowledge_provider_key = provider_labels[knowledge_provider_label]
                knowledge_models = models_by_provider[knowledge_provider_key]
                knowledge_model_label = st.selectbox(
                    "知识分析模型",
                    list(knowledge_models),
                    index=0,
                    key="knowledge_model_label",
                )
                st.caption(
                    f"需要先在设置页开启云模型权限，并把 {knowledge_provider_label} API Key "
                    "安全保存到当前 Windows 用户凭据。"
                )
                confirm_knowledge_upload = st.checkbox(
                    f"我确认将脱敏、受限的账号分析上下文发送给 {knowledge_provider_label}",
                    value=False,
                )
                confirm_knowledge_cost = st.checkbox(
                    f"我确认本次 {knowledge_model_label} 调用可能产生费用",
                    value=False,
                )
                knowledge_analysis_payload = {
                    "provider": knowledge_provider_key,
                    "model": knowledge_models[knowledge_model_label],
                    "template": "content_strategy",
                    "reasoning_effort": "high",
                    "max_video_analyses": max(
                        1,
                        min(
                            1_000 if all_videos else int(video_count),
                            1_000,
                        ),
                    ),
                    "confirm_cloud_upload": confirm_knowledge_upload,
                    "confirm_cost": confirm_knowledge_cost,
                }
            strict_media = st.checkbox(
                "任一视频失败即停止",
                value=bool(template.get("strict_media_enrichment", False)),
            )
            strict_vision = st.checkbox(
                "视觉模型输出异常即停止",
                value=bool(template.get("strict_vision", False)),
            )

    with st.container(border=True):
        st.markdown("#### 03 · 确认并开始")
        st.caption("系统会先核对运行能力；预检不会采集或写入账号内容。")
        summary_columns = st.columns(3)
        summary_columns[0].metric(
            "采集作品",
            "全部" if all_videos else str(int(video_count)),
        )
        summary_columns[1].metric(
            "内容理解",
            "随采集范围" if analyze_media else "关闭",
            delta=(
                "全部实际采集视频"
                if analyze_media and all_videos
                else f"预计 {int(video_count)} 个视频"
                if analyze_media
                else None
            ),
        )
        summary_columns[2].metric(
            "评论范围",
            (
                "随采集范围"
                if int(comments_per_video) > 0 and comments_cover_all_selected
                else f"{int(comment_video_limit)} 个视频"
                if int(comments_per_video) > 0
                else "关闭"
            ),
            delta=(
                f"预计最多 {estimated_comments:,} 条一级评论"
                if int(comments_per_video) > 0
                else None
            ),
        )

        if "TikHub" in provider:
            st.warning(
                "TikHub 是付费 API。首次运行前会预演并显式确认费用，"
                "且需要在环境变量中设置 TIKHUB_API_TOKEN。"
            )
        else:
            st.info(
                "默认使用本机浏览器采集，并在本地完成 GPU 转写和画面理解；"
                "首次运行时可能需要登录抖音。"
            )
        public_content_confirmed = st.checkbox(
            "我确认只分析有权处理的公开内容，并理解平台登录与访问规则",
            value=False,
        )
        preview_column, run_column = st.columns([1, 1.35])
        preview_clicked = preview_column.form_submit_button(
            "仅检查运行条件",
            icon=":material/fact_check:",
            use_container_width=True,
        )
        run_clicked = run_column.form_submit_button(
            "开始蒸馏",
            type="primary",
            icon=":material/play_arrow:",
            use_container_width=True,
        )

payload = {
    "url": profile_url,
    "profile": "standard",
    "provider": "tikhub" if "TikHub" in provider else "mediacrawler",
    "count": None if all_videos else int(video_count),
    "all_videos": all_videos,
    "sort": sort,
    "comments_per_video": int(comments_per_video),
    "comment_video_limit": int(comment_video_limit),
    "max_provider_calls": (int(max_provider_calls) if int(max_provider_calls) > 0 else None),
    "confirm_provider_cost": False,
    "media_limit": media_limit,
    "whisper_backend": (
        "faster-whisper"
        if whisper_backend == "faster-whisper"
        else ("openai-whisper" if whisper_backend.startswith("原版") else "auto")
    ),
    "whisper_model": whisper_model,
    "whisper_batch_size": 8,
    "vision_provider": (
        "llamacpp"
        if analyze_media and vision_choice.startswith("本地")
        else ("cloud" if analyze_media and vision_choice.startswith("云端") else None)
    ),
    "text_provider": "cloud" if text_source.startswith("云端") else None,
    "cloud_base_url": cloud_base_url.strip() or None,
    "cloud_api_key": cloud_api_key.strip() or None,
    "cloud_text_model": cloud_text_model.strip() or None,
    "cloud_vision_model": cloud_vision_model.strip() or None,
    "vision_model": vision_model,
    "strict_media_enrichment": strict_media,
    "strict_vision": strict_vision,
    "knowledge_analysis": knowledge_analysis_payload if knowledge_synthesis else None,
    "export_knowledge": export_knowledge,
}

if preview_clicked or run_clicked:
    if run_clicked and not public_content_confirmed:
        st.error("开始前请确认只分析有权处理的公开内容。")
    elif (
        run_clicked
        and knowledge_synthesis
        and (not confirm_knowledge_upload or not confirm_knowledge_cost)
    ):
        st.error("启用经营知识蒸馏时，请同时确认脱敏数据外发与模型费用。")
    elif not profile_url.strip():
        st.error("请输入抖音主页链接")
    elif not project_path.strip():
        st.error("请设置项目目录")
    else:
        effective_project = project_path
        if account_name.strip():
            # One folder per distilled account, with -1/-2 suffixes on reruns.
            effective_project = _resolve_account_project(project_path, account_name)
            st.caption(f"本次蒸馏项目：{effective_project}")
        action_label = "运行条件检查" if preview_clicked else "账号蒸馏"
        with st.status(f"正在准备{action_label}…", expanded=True) as activity:
            activity.write("正在初始化工作区并校验本地服务连接…")
            initialized = _request(
                "/api/projects/init",
                "POST",
                json={
                    "path": effective_project,
                    "name": Path(effective_project).name,
                    # Inherit local model settings from the container project so
                    # the new account folder uses the same local model configuration.
                    "config_template": project_path,
                },
            )
            if initialized.get("ok"):
                st.session_state["project_path"] = effective_project
                web_state.set_state(project_path=effective_project)
                activity.update(label=f"工作区已就绪，正在提交{action_label}…")
                accepted = _submit_workflow(payload, dry_run=preview_clicked)
                if accepted:
                    activity.update(
                        label=f"{action_label}已进入后台队列",
                        state="complete",
                        expanded=False,
                    )
                    st.rerun()
                else:
                    activity.update(label=f"{action_label}提交失败", state="error")
            else:
                activity.update(label="工作区初始化失败", state="error", expanded=True)
                st.error(f"项目初始化失败：{(initialized.get('error') or {}).get('message')}")

last_result = st.session_state.get("last_workflow_result")
if isinstance(last_result, dict):
    section_header("执行结果", "查看采集覆盖率、分析产出与可下载工件。")
    with st.container(border=True):
        _render_result(last_result)

account_id = st.session_state.get("last_account_id")
if isinstance(account_id, str):
    section_header("后续处理", "单独重试视频解析、生成深度分析，或同步本地知识成果。")
    reparse_tab, gpt_tab, obsidian_tab, weknora_tab = st.tabs(
        ["视频重新解析", "云端深度分析", "本地 Obsidian 知识库", "WeKnora 知识库"]
    )
    with reparse_tab:
        _render_media_reparse(account_id)

    with gpt_tab:
        _render_gpt_analysis(account_id)

    with obsidian_tab:
        st.caption(
            "把本地蒸馏结果和已完成云端深度分析一起写入 Obsidian 仓库"
            "（Markdown + 双链），不会上传任何数据。"
        )
        default_vault = st.session_state.get("obsidian_vault_path") or web_state.get_state(
            "obsidian_vault_path"
        )
        vault_path = st.text_input(
            "Obsidian 仓库路径（Vault 目录）",
            value=str(default_vault or ""),
            key="obsidian_vault_input",
            placeholder=r"D:\ObsidianVault",
            help="填写 Obsidian 的仓库根目录；同步会创建“视频账号蒸馏/<账号名>”子目录。",
        )
        obsidian_max = st.number_input(
            "纳入逐视频证据数",
            min_value=1,
            max_value=1_000,
            value=min(100, 1_000),
            step=1,
            key="obsidian_max_video_analyses",
        )
        if st.button(
            "同步当前账号到 Obsidian",
            use_container_width=True,
        ):
            cleaned_vault = vault_path.strip()
            st.session_state["obsidian_vault_path"] = cleaned_vault
            web_state.set_state(obsidian_vault_path=cleaned_vault)
            if not cleaned_vault:
                st.error("请先填写 Obsidian 仓库路径")
            else:
                with st.status("正在同步到 Obsidian…", expanded=True) as activity:
                    activity.write("正在整理 Markdown、证据附件与双链索引…")
                    sync = _request(
                        (
                            f"/api/projects/{_encoded_account_project()}"
                            f"/knowledge/obsidian/accounts/{account_id}/sync"
                        ),
                        "POST",
                        json={
                            "vault_path": cleaned_vault,
                            "max_video_analyses": obsidian_max,
                        },
                        timeout=120,
                    )
                    activity.update(
                        label="Obsidian 同步完成" if sync.get("ok") else "Obsidian 同步失败",
                        state="complete" if sync.get("ok") else "error",
                        expanded=not bool(sync.get("ok")),
                    )
                if sync.get("ok"):
                    st.success("已写入 Obsidian 知识库")
                    st.session_state["last_obsidian_sync"] = sync
                    st.write("写入文件：")
                    for path in sync.get("files", []):
                        st.write(f"- `{path}`")
                else:
                    st.error(f"Obsidian 同步失败：{(sync.get('error') or {}).get('message')}")

    with weknora_tab:
        st.caption(
            "先在 WeKnora 创建并授权目标知识库；这里仅把分析报告（Markdown）导入已有知识库，"
            "不会自行创建知识库。"
        )
        default_weknora_url = st.session_state.get("weknora_base_url") or web_state.get_state(
            "weknora_base_url",
            "http://127.0.0.1:8080",
        )
        weknora_url = st.text_input(
            "WeKnora 服务地址",
            value=str(default_weknora_url),
            key="weknora_url_input",
            placeholder="http://127.0.0.1:8080",
            help="可填写服务根地址，也可填写以 /api/v1 结尾的完整 API 地址。",
        )
        weknora_key = st.text_input(
            "WeKnora API Key",
            type="password",
            key="weknora_api_key",
            placeholder="在 WeKnora 账户页面获取",
            help="密钥只保存在当前会话，不会写入项目文件。",
        )
        if st.button(
            "读取此 API Key 可访问的知识库",
            use_container_width=True,
            disabled=not weknora_url.strip() or not weknora_key.strip(),
        ):
            cleaned_url = weknora_url.strip()
            with st.status("正在读取 WeKnora 知识库…", expanded=False) as activity:
                discovered = _request(
                    (
                        f"/api/projects/{_encoded_account_project()}"
                        "/knowledge/weknora/knowledge-bases"
                    ),
                    "POST",
                    json={"base_url": cleaned_url, "api_key": weknora_key},
                    timeout=60,
                )
                activity.update(
                    label="知识库列表读取完成" if discovered.get("ok") else "知识库读取失败",
                    state="complete" if discovered.get("ok") else "error",
                )
            if discovered.get("ok"):
                knowledge_bases = discovered.get("knowledge_bases") or []
                st.session_state["weknora_knowledge_bases"] = knowledge_bases
                st.session_state["weknora_base_url"] = cleaned_url
                web_state.set_state(weknora_base_url=cleaned_url)
                if knowledge_bases:
                    st.success(f"已读取 {len(knowledge_bases)} 个可访问知识库")
                else:
                    st.warning("此 API Key 当前看不到任何知识库，请检查它的知识库授权范围。")
            else:
                st.session_state["weknora_knowledge_bases"] = []
                message = (discovered.get("error") or {}).get("message") or "读取失败"
                st.error(f"读取 WeKnora 知识库失败：{message}")

        knowledge_bases = [
            item
            for item in st.session_state.get("weknora_knowledge_bases", [])
            if isinstance(item, dict) and item.get("id") and item.get("name")
        ]
        knowledge_base_by_id = {str(item["id"]): item for item in knowledge_bases}
        knowledge_base_ids = list(knowledge_base_by_id)
        if knowledge_base_ids:
            current_kb_id = st.session_state.get("weknora_kb_id_select")
            if current_kb_id not in knowledge_base_ids:
                persisted_kb_id = web_state.get_state("weknora_kb_id")
                st.session_state["weknora_kb_id_select"] = (
                    persisted_kb_id
                    if persisted_kb_id in knowledge_base_ids
                    else knowledge_base_ids[0]
                )
            selected_kb_id = st.selectbox(
                "选择目标知识库",
                options=knowledge_base_ids,
                format_func=lambda kb_id: f"{knowledge_base_by_id[kb_id]['name']} · {kb_id}",
                key="weknora_kb_id_select",
                help="同步请求使用知识库唯一 ID，不会因同名知识库选错目标。",
            )
            selected_kb_name = str(knowledge_base_by_id[selected_kb_id]["name"])
        else:
            selected_kb_id = ""
            selected_kb_name = ""
            st.info("请先输入 API Key 并读取可访问的知识库。")

        weknora_max = st.number_input(
            "纳入逐视频证据数",
            min_value=1,
            max_value=1_000,
            value=min(100, 1_000),
            step=1,
            key="weknora_max_video_analyses",
        )
        if st.button(
            "同步当前账号到 WeKnora",
            use_container_width=True,
            disabled=not selected_kb_id,
        ):
            cleaned_url = weknora_url.strip()
            st.session_state["weknora_base_url"] = cleaned_url
            web_state.set_state(
                weknora_base_url=cleaned_url,
                weknora_kb_id=selected_kb_id,
                weknora_kb_name=selected_kb_name,
            )
            if not cleaned_url:
                st.error("请填写 WeKnora 服务地址")
            elif not weknora_key.strip():
                st.error("请填写 WeKnora API Key")
            else:
                with st.status("正在同步到 WeKnora…", expanded=True) as activity:
                    activity.write("正在打包分析报告并上传到目标知识库…")
                    sync = _request(
                        (
                            f"/api/projects/{_encoded_account_project()}"
                            f"/knowledge/weknora/accounts/{account_id}/sync"
                        ),
                        "POST",
                        json={
                            "base_url": cleaned_url,
                            "api_key": weknora_key,
                            "kb_id": selected_kb_id,
                            "max_video_analyses": weknora_max,
                        },
                        timeout=300,
                    )
                    activity.update(
                        label="WeKnora 同步完成" if sync.get("ok") else "WeKnora 同步失败",
                        state="complete" if sync.get("ok") else "error",
                        expanded=not bool(sync.get("ok")),
                    )
                if sync.get("ok"):
                    st.success("已上传到 WeKnora 知识库")
                    st.session_state["last_weknora_sync"] = sync
                    st.write("上传文件：")
                    for path in sync.get("uploaded", []):
                        st.write(f"- `{path}`")
                else:
                    message = sync.get("message") or (sync.get("error") or {}).get("message")
                    if not message:
                        message = "请展开下方明细查看失败原因。"
                    st.error(f"WeKnora 同步失败：{message}")
                    if sync.get("error_code") == "API_KEY_SCOPE_NOT_ALLOWED":
                        st.info(
                            "在 WeKnora 的 API Key 设置中，将当前 Key 的知识库范围包含“"
                            f"{selected_kb_name}”（ID：{selected_kb_id}），并启用"
                            "文档上传或编辑权限，然后重新同步。"
                        )
                    if sync.get("errors"):
                        for error in sync["errors"]:
                            st.write(f"- {error}")

weknora_result = st.session_state.get("last_weknora_sync")
if isinstance(weknora_result, dict):
    with st.expander("最近一次 WeKnora 同步结果", expanded=True):
        st.json(weknora_result)

obsidian_result = st.session_state.get("last_obsidian_sync")
if isinstance(obsidian_result, dict):
    with st.expander("最近一次 Obsidian 同步结果", expanded=True):
        st.json(obsidian_result)
