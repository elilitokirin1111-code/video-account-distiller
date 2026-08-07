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
    badge,
    section_header,
    setup_page,
    stepper,
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
    "media_complete": "视频内容分析完成",
    "report": "生成画像、报告和分析上下文",
    "knowledge_export": "生成 GPT/OpenKB 知识包",
    "model_request": "生成 GPT 分析",
    "completed": "全部完成",
    "failed": "执行失败",
    "cancelling": "正在安全取消",
    "cancelled": "已取消",
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


def _submit_gpt_analysis(account_id: str, payload: dict[str, Any]) -> None:
    result = _request(
        f"/api/projects/{_encoded_account_project()}/accounts/{account_id}/gpt-analysis",
        "POST",
        json=payload,
    )
    task_id = result.get("task_id")
    if not isinstance(task_id, str):
        st.error(f"深度分析提交失败：{(result.get('error') or {}).get('message', '未知错误')}")
        return
    st.session_state["active_task_id"] = task_id
    st.session_state["active_task_kind"] = "gpt_analysis"
    web_state.set_state(active_task_id=task_id, active_task_kind="gpt_analysis")
    st.session_state.pop("last_gpt_analysis", None)
    st.toast("深度分析任务已提交；临时密钥未写入任务记录", icon="🤖")


def _cancel_task(task_id: str) -> None:
    result = _request(f"/api/tasks/{task_id}/cancel", "POST", timeout=10)
    if result.get("task_id"):
        st.toast("已提交安全取消请求", icon="⏹️")
        return
    st.error(f"取消失败：{(result.get('error') or {}).get('message', '未知错误')}")


def _retry_task(task_id: str) -> None:
    result = _request(f"/api/tasks/{task_id}/retry", "POST", timeout=30)
    new_task_id = result.get("task_id")
    if not isinstance(new_task_id, str):
        st.error(f"重试失败：{(result.get('error') or {}).get('message', '未知错误')}")
        return
    st.session_state["active_task_id"] = new_task_id
    st.session_state["active_task_kind"] = result.get("task_type", "account_distill")
    web_state.set_state(
        active_task_id=new_task_id,
        active_task_kind=result.get("task_type", "account_distill"),
    )
    st.session_state.pop("last_workflow_result", None)
    st.toast("已从最近的安全检查点创建重试任务", icon="🔁")


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

    st.success("账号蒸馏已完成，数据、视频内容、报告和知识包均已写入项目。")
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
            "本地知识包已生成。可在下方“本地 Obsidian 知识库”页签同步到你的仓库，"
            "整个过程不会上传数据；如需云端模型分析，请使用“云端深度分析”。"
        )
        st.caption("知识产物：" + "、".join(str(item) for item in knowledge.get("outputs", [])))

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
            updated = _request(
                f"/api/projects/{_encoded_account_project()}/settings/cloud-model",
                "PUT",
                json={"allow_cloud_model_upload": True},
                timeout=10,
            )
            if updated.get("ok"):
                st.success("项目权限已开启；每次调用仍需单独确认。")
                st.rerun()
            st.error(f"权限更新失败：{(updated.get('error') or {}).get('message', '未知错误')}")
        return

    provider_labels = {
        "OpenAI": "openai",
        "阿里云百炼": "bailian",
        "DeepSeek": "deepseek",
    }
    models_by_provider = {
        "openai": {
            "均衡（GPT-5.6 Terra）": "gpt-5.6-terra",
            "高质量（GPT-5.6 Sol）": "gpt-5.6-sol",
            "高效率（GPT-5.6 Luna）": "gpt-5.6-luna",
        },
        "bailian": {
            "千问 3.7 Plus": "qwen3.7-plus",
        },
        "deepseek": {
            "DeepSeek Chat": "deepseek-chat",
            "DeepSeek Reasoner": "deepseek-reasoner",
        },
    }
    template_labels = {
        "账号体检": "account_health",
        "内容策略": "content_strategy",
        "30 天增长计划": "growth_plan",
    }
    reasoning_labels = {
        "低（推荐起点）": "low",
        "无": "none",
        "中": "medium",
        "高": "high",
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
        saved = _request(
            f"/api/cloud-model/credentials/{provider_key}",
            "PUT",
            json={"api_key": api_key},
            timeout=45,
        )
        if saved.get("ok"):
            st.session_state[probe_key] = saved
            st.session_state[clear_key] = True
            st.toast(f"{provider_label} API 已验证并安全保存", icon="✅")
            st.rerun()
        else:
            st.error(f"API 验证失败：{(saved.get('error') or {}).get('message', '未知错误')}")
    if refresh_clicked:
        checked = _request(
            f"/api/cloud-model/credentials/{provider_key}/probe",
            "POST",
            timeout=45,
        )
        st.session_state[probe_key] = checked
        if checked.get("ok"):
            st.toast(f"已识别 {provider_label} 和可用模型", icon="✅")
    if delete_clicked:
        deleted = _request(
            f"/api/cloud-model/credentials/{provider_key}",
            "DELETE",
            timeout=15,
        )
        if deleted.get("ok"):
            st.session_state.pop(probe_key, None)
            st.session_state[clear_key] = True
            st.toast(f"已删除保存的 {provider_label} API Key")
            st.rerun()

    probe = st.session_state.get(probe_key)
    if credential_configured and not isinstance(probe, dict):
        probe = _request(
            f"/api/cloud-model/credentials/{provider_key}/probe",
            "POST",
            timeout=45,
        )
        st.session_state[probe_key] = probe
    online_models = probe.get("models", []) if isinstance(probe, dict) and probe.get("ok") else []
    model_labels = {
        label: model
        for label, model in models_by_provider[provider_key].items()
        if model in online_models
    }
    if credential_configured:
        st.success(
            f"{provider_label} API 已保存并可持续使用"
            + (f"；来源：{credential_source}" if credential_source else "")
        )
    elif isinstance(probe, dict) and not probe.get("ok"):
        st.error(f"在线识别失败：{(probe.get('error') or {}).get('message', '未知错误')}")
    if not model_labels:
        model_labels = models_by_provider[provider_key]

    model_column, template_column, reasoning_column = st.columns(3)
    with model_column:
        model_label = st.selectbox("分析模型", list(model_labels))
    with template_column:
        template_label = st.selectbox("分析模板", list(template_labels))
    with reasoning_column:
        reasoning_label = st.selectbox("推理强度", list(reasoning_labels))
    max_video_analyses = st.slider(
        "纳入最近视频分析数",
        1,
        25,
        10,
        key="gpt_max_video_analyses",
    )
    preview_request = {
        "provider": provider_key,
        "model": model_labels[model_label],
        "template": template_labels[template_label],
        "reasoning_effort": reasoning_labels[reasoning_label],
        "max_video_analyses": max_video_analyses,
        "confirm_cloud_upload": False,
        "confirm_cost": False,
    }
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
            disabled=not preview_ok or not credential_configured or not bool(online_models),
        )

    if submitted:
        if not confirm_cloud_upload or not confirm_cost:
            st.error("请同时确认数据外发与潜在费用。")
        else:
            _submit_gpt_analysis(
                account_id,
                {
                    "provider": provider_key,
                    "model": model_labels[model_label],
                    "template": template_labels[template_label],
                    "reasoning_effort": reasoning_labels[reasoning_label],
                    "max_video_analyses": max_video_analyses,
                    "confirm_cloud_upload": True,
                    "confirm_cost": True,
                },
            )
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
    queue_position = task.get("queue_position")
    if status == "pending" and isinstance(queue_position, int):
        st.caption(
            f"持久队列第 {queue_position} 位 · 资源组 {task.get('resource_class', 'default')}"
        )

    if status in {"pending", "running"}:
        if st.button("安全取消任务", key=f"monitor_cancel_{task_id}", use_container_width=True):
            _cancel_task(task_id)
            st.rerun()
    elif status == "cancelling":
        st.warning("已收到取消请求，正在等待当前不可中断的本地步骤安全结束。")

    if status == "completed":
        result = task.get("result")
        if isinstance(result, dict):
            task_kind = st.session_state.get("active_task_kind")
            if task_kind == "openkb_sync":
                st.session_state["last_openkb_result"] = result
            elif task_kind == "gpt_analysis":
                st.session_state["last_gpt_analysis"] = result
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
        retry_column, dismiss_column = st.columns(2)
        if retry_column.button(
            "从安全检查点重试",
            key=f"monitor_retry_{task_id}",
            disabled=not bool(task.get("retryable")),
            use_container_width=True,
        ):
            _retry_task(task_id)
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
            _retry_task(task_id)
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
    "新建采集任务",
    "用一个清晰的四步流程完成来源配置、采集范围、内容理解与执行预检。",
    eyebrow="COLLECTION WORKFLOW",
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
        st.session_state["active_task_dry_run"] = web_state.get_state(
            "active_task_dry_run", False
        )
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

doctor = _request(f"/api/doctor/{_encoded_project()}", timeout=20) if project_path else {}
doctor_value = doctor.get("data")
doctor_data: dict[str, Any] = doctor_value if isinstance(doctor_value, dict) else {}
capabilities = doctor_data.get("capabilities") or {}

if st.session_state.get("active_task_id"):
    section_header("运行进度", "任务会在本地后台持续执行，刷新页面不会中断。")
    with st.container(border=True):
        _task_monitor()
        st.caption("也可以在“系统设置 → 最近任务”中继续查看。")

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
                    st.session_state["last_openkb_result"] = selected_result
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
            _retry_task(selected_task)
            st.rerun()
        if cancel_column.button(
            "安全取消",
            disabled=selected_status not in {"pending", "running"},
            use_container_width=True,
        ):
            _cancel_task(selected_task)
            if isinstance(selected, dict):
                st.session_state["active_task_id"] = selected_task
                st.session_state["active_task_kind"] = selected.get("task_type", "account_distill")
            st.rerun()
    else:
        st.caption("暂无任务")

saved_template = web_state.get_state("last_collection_template")
if isinstance(saved_template, dict) and not st.session_state.get("last_collection_template"):
    st.session_state["last_collection_template"] = saved_template
template = st.session_state.get("last_collection_template") or {}

stepper(["采集来源", "采集范围", "内容理解", "预检与执行"], active=1)

with st.form("self_service_distill_form"):
    with st.container(border=True):
        st.markdown("#### 01 · 采集来源")
        st.caption("选择合规的数据来源，并确认浏览器或 API 的可用状态。")
        provider = st.radio(
            "采集源",
            [
                "MediaCrawler（本地浏览器，需手动登录抖音）",
                "TikHub API（付费，需要环境变量 TIKHUB_API_TOKEN）",
            ],
            index=0 if template.get("provider") != "tikhub" else 1,
            horizontal=True,
            help="MediaCrawler 打开本机 Chrome 手动登录，不收费；TikHub 调用付费 API。",
        )
        profile_url = st.text_input(
            "账号主页链接",
            value=str(template.get("url") or ""),
            placeholder="https://v.douyin.com/.../ 或 https://www.douyin.com/user/...",
            help="当前自动采集链路支持抖音主页链接。",
        )
        account_name = st.text_input(
            "蒸馏对象名称（可选）",
            value=str(template.get("account_name") or ""),
            placeholder="例如：小许的酒店日记",
            help="填写后会在项目目录下自动创建同名文件夹保存本次蒸馏结果；"
            "同名文件夹已存在时自动追加 -1、-2 序号。留空则直接使用当前项目目录。",
        )
        source_status, browser_status = st.columns(2)
        with source_status:
            source_ready = (
                bool(os.environ.get("TIKHUB_API_TOKEN"))
                if "TikHub" in provider
                else bool(capabilities.get("mediacrawler_douyin"))
            )
            st.markdown("**采集源状态**")
            st.markdown(
                badge(
                    "已就绪" if source_ready else "运行时检查",
                    "success" if source_ready else "warning",
                ),
                unsafe_allow_html=True,
            )
        with browser_status:
            st.markdown("**浏览器登录**")
            st.markdown(
                badge(
                    "任务启动后检查" if "MediaCrawler" in provider else "无需浏览器",
                    "neutral",
                ),
                unsafe_allow_html=True,
            )

    with st.container(border=True):
        st.markdown("#### 02 · 采集范围")
        st.caption("控制视频、评论与调用预算，预检会再次核对安全上限。")
        collection_mode = st.radio(
            "作品采集方式",
            ["指定视频数量", "采集主页全部公开视频"],
            index=1 if template.get("all_videos") else 0,
            horizontal=True,
            help="全主页模式仍受 1,000 页/20,000 条作品安全上限与调用预算约束。",
        )
        all_videos = collection_mode == "采集主页全部公开视频"

        c1, c2, c3 = st.columns(3)
        with c1:
            template_count = template.get("count")
            video_count = st.number_input(
                "采集视频数",
                min_value=1,
                max_value=20_000,
                value=int(template_count) if isinstance(template_count, int) else 20,
                disabled=all_videos,
                help="选择全主页模式时不使用此上限。",
            )
        with c2:
            template_comments = template.get("comments_per_video")
            comments_per_video = st.number_input(
                "每个视频采集评论数",
                min_value=0,
                max_value=20,
                value=(
                    int(template_comments)
                    if isinstance(template_comments, int)
                    else 10
                ),
                help="选择 0 可完全关闭评论采集。",
            )
        with c3:
            comment_video_max = 200 if all_videos else min(int(video_count), 200)
            template_comment_limit = template.get("comment_video_limit")
            comment_video_limit = st.number_input(
                "采集评论的视频数",
                min_value=1,
                max_value=comment_video_max,
                value=(
                    min(int(template_comment_limit), comment_video_max)
                    if isinstance(template_comment_limit, int)
                    else min(20, comment_video_max)
                ),
                disabled=int(comments_per_video) == 0,
                help="可覆盖所选作品，单次最多 200 个视频。",
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
        st.markdown("#### 03 · 内容理解")
        st.caption("配置语音转写、画面语义和本地知识包生成。")
        template_media_limit = template.get("media_limit")
        analyze_media = st.toggle(
            "下载并分析视频本身",
            value=(
                int(template_media_limit) > 0
                if isinstance(template_media_limit, int)
                else True
            ),
        )
        media_limit_max = 20 if all_videos else min(int(video_count), 20)
        m1, m2, m3 = st.columns(3)
        with m1:
            template_whisper = template.get("whisper_model")
            whisper_index = (
                ["tiny", "base", "small", "medium"].index(template_whisper)
                if template_whisper in ["tiny", "base", "small", "medium"]
                else 2
            )
            template_vision_choice = template.get("vision_provider")
            media_limit = st.number_input(
                "视频内容分析数",
                min_value=1,
                max_value=media_limit_max,
                value=(
                    min(int(template_media_limit), media_limit_max)
                    if isinstance(template_media_limit, int)
                    and int(template_media_limit) > 0
                    else media_limit_max
                ),
                disabled=not analyze_media,
                help="视频下载、Whisper 与视觉分析计算量较大，单次最多 20 条。",
            )
        with m2:
            whisper_model = st.selectbox(
                "Whisper 转写模型",
                ["tiny", "base", "small", "medium"],
                index=whisper_index,
                disabled=not analyze_media,
            )
        with m3:
            vision_choice = st.selectbox(
                "画面语义分析",
                ["本地 llama.cpp（推荐）", "云端 API（对比）", "仅提取关键帧/镜头"],
                index=(
                    0
                    if template_vision_choice == "llamacpp"
                    else (1 if template_vision_choice == "cloud" else 2)
                ),
                disabled=not analyze_media,
            )

        with st.expander("高级设置", icon=":material/tune:"):
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
            template_calls = template.get("max_provider_calls")
            max_provider_calls = st.number_input(
                "最大采集调用数",
                min_value=1,
                max_value=50_000,
                value=(
                    int(template_calls)
                    if isinstance(template_calls, int) and int(template_calls) >= 1
                    else (5_000 if all_videos else max(100, int(comment_video_limit) + 10))
                ),
                help="预检会估算调用量；超过该上限时不会开始真实采集。",
            )
            vision_model = st.text_input(
                "本地视觉模型（llama.cpp）",
                value=str(template.get("vision_model") or "qwen3-vl-8b"),
            )
            text_source = st.radio(
                "文本分析来源（对比本地/云端）",
                ["本地 llama.cpp（qwen3-8b）", "云端 API（OpenAI 兼容）"],
                index=0 if template.get("text_provider") != "cloud" else 1,
            )
            cloud_base_url = st.text_input(
                "云端服务地址（OpenAI 兼容）",
                value=str(
                    template.get("cloud_base_url")
                    or "https://api.deepseek.com"
                ),
                placeholder="https://api.deepseek.com 或 DashScope compatible-mode",
            )
            cloud_api_key = st.text_input(
                "云端 API Key",
                type="password",
                value=str(template.get("cloud_api_key") or ""),
            )
            cloud_text_model = st.text_input(
                "云端文本模型",
                value=str(template.get("cloud_text_model") or "deepseek-chat"),
            )
            cloud_vision_model = st.text_input(
                "云端视觉模型",
                value=str(template.get("cloud_vision_model") or "qwen-vl-max-latest"),
            )
            export_knowledge = st.checkbox(
                "生成本地知识包（Obsidian/OpenKB）",
                value=bool(template.get("export_knowledge", True)),
            )
            strict_media = st.checkbox(
                "任一视频失败即停止",
                value=bool(template.get("strict_media_enrichment", False)),
            )
            strict_vision = st.checkbox(
                "视觉模型输出异常即停止",
                value=bool(template.get("strict_vision", False)),
            )

    with st.container(border=True):
        st.markdown("#### 04 · 预检与执行")
        st.caption("核对任务摘要、依赖与风险后，再启动完整蒸馏。")
        summary_columns = st.columns(4)
        summary_columns[0].metric(
            "视频范围",
            "全部" if all_videos else str(int(video_count)),
        )
        summary_columns[1].metric("评论上限", f"{estimated_comments:,}")
        summary_columns[2].metric(
            "内容理解",
            str(int(media_limit)) if analyze_media else "关闭",
        )
        summary_columns[3].metric(
            "预计耗时",
            "10–30 分钟" if analyze_media else "3–10 分钟",
        )

        dependency_columns = st.columns(4)
        dependency_values = (
            ("采集源", source_ready),
            ("视频处理", bool(capabilities.get("local_media")) or not analyze_media),
            ("Whisper", bool(capabilities.get("video_transcription")) or not analyze_media),
            (
                "视觉模型",
                bool(capabilities.get("local_vision")) or not vision_choice.startswith("本地"),
            ),
        )
        for column, (label, ready) in zip(
            dependency_columns,
            dependency_values,
            strict=True,
        ):
            with column:
                st.markdown(f"**{label}**")
                st.markdown(
                    badge("可用" if ready else "预检确认", "success" if ready else "warning"),
                    unsafe_allow_html=True,
                )

        if "TikHub" in provider:
            st.warning(
                "TikHub 是付费 API。首次运行前会预演并显式确认费用，"
                "且需要在环境变量中设置 TIKHUB_API_TOKEN。"
            )
        else:
            st.info(
                "MediaCrawler 首次运行可能打开 Chrome 登录页；默认内容理解只调用本机 "
                "Whisper/llama.cpp，不产生外部模型费用。"
            )
        public_content_confirmed = st.checkbox(
            "我确认只分析有权处理的公开内容，并理解平台登录与访问规则",
            value=False,
        )
        save_column, preview_column, run_column = st.columns([0.85, 1, 1.2])
        save_clicked = save_column.form_submit_button(
            "保存为模板",
            icon=":material/bookmark_add:",
            use_container_width=True,
        )
        preview_clicked = preview_column.form_submit_button(
            "运行预检",
            icon=":material/fact_check:",
            use_container_width=True,
        )
        run_clicked = run_column.form_submit_button(
            "开始蒸馏",
            type="primary",
            icon=":material/play_arrow:",
            use_container_width=True,
            disabled=not public_content_confirmed,
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
    "max_provider_calls": int(max_provider_calls),
    "confirm_provider_cost": False,
    "media_limit": int(media_limit) if analyze_media else 0,
    "whisper_model": whisper_model,
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
    "export_knowledge": export_knowledge,
}

if save_clicked:
    saved_template = {**payload, "account_name": account_name}
    st.session_state["last_collection_template"] = saved_template
    web_state.set_state(last_collection_template=saved_template)
    st.toast("任务模板已保存，刷新页面后仍可恢复")
elif preview_clicked or run_clicked:
    if not profile_url.strip():
        st.error("请输入抖音主页链接")
    elif not project_path.strip():
        st.error("请设置项目目录")
    else:
        effective_project = project_path
        if account_name.strip():
            # One folder per distilled account, with -1/-2 suffixes on reruns.
            effective_project = _resolve_account_project(project_path, account_name)
            st.caption(f"本次蒸馏项目：{effective_project}")
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
            _submit_workflow(payload, dry_run=preview_clicked)
            st.rerun()
        else:
            st.error(f"项目初始化失败：{(initialized.get('error') or {}).get('message')}")

last_result = st.session_state.get("last_workflow_result")
if isinstance(last_result, dict):
    section_header("执行结果", "查看采集覆盖率、分析产出与可下载工件。")
    with st.container(border=True):
        _render_result(last_result)

account_id = st.session_state.get("last_account_id")
if isinstance(account_id, str):
    section_header("后续分析", "在已有蒸馏结果上生成可审计的云端深度分析或同步知识库。")
    gpt_tab, obsidian_tab, weknora_tab = st.tabs(
        ["云端深度分析", "本地 Obsidian 知识库", "WeKnora 知识库"]
    )
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
        obsidian_max = st.slider(
            "纳入最近视频分析数",
            1,
            25,
            10,
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
                if sync.get("ok"):
                    st.success("已写入 Obsidian 知识库")
                    st.session_state["last_obsidian_sync"] = sync
                    st.write("写入文件：")
                    for path in sync.get("files", []):
                        st.write(f"- `{path}`")
                else:
                    st.error(
                        f"Obsidian 同步失败：{(sync.get('error') or {}).get('message')}"
                    )

    with weknora_tab:
        st.caption(
            "把分析报告上传到 WeKnora 知识库（Markdown），"
            "上传后可在 WeKnora 里检索和问答。"
        )
        default_weknora_url = st.session_state.get("weknora_base_url") or web_state.get_state(
            "weknora_base_url",
            "http://127.0.0.1:8080",
        )
        default_weknora_kb = st.session_state.get("weknora_kb_name") or web_state.get_state(
            "weknora_kb_name",
            "视频账号蒸馏",
        )
        weknora_url = st.text_input(
            "WeKnora 服务地址",
            value=str(default_weknora_url),
            key="weknora_url_input",
            placeholder="http://127.0.0.1:8080",
        )
        weknora_kb = st.text_input(
            "知识库名称",
            value=str(default_weknora_kb),
            key="weknora_kb_input",
        )
        weknora_key = st.text_input(
            "WeKnora API Key",
            type="password",
            key="weknora_api_key",
            placeholder="在 WeKnora 账户页面获取",
            help="密钥只保存在当前会话，不会写入项目文件。",
        )
        weknora_max = st.slider(
            "纳入最近视频分析数",
            1,
            25,
            10,
            key="weknora_max_video_analyses",
        )
        if st.button(
            "同步当前账号到 WeKnora",
            use_container_width=True,
        ):
            cleaned_url = weknora_url.strip()
            cleaned_kb = weknora_kb.strip()
            st.session_state["weknora_base_url"] = cleaned_url
            st.session_state["weknora_kb_name"] = cleaned_kb
            web_state.set_state(
                weknora_base_url=cleaned_url,
                weknora_kb_name=cleaned_kb,
            )
            if not cleaned_url or not cleaned_kb:
                st.error("请填写 WeKnora 服务地址和知识库名称")
            elif not weknora_key.strip():
                st.error("请填写 WeKnora API Key")
            else:
                sync = _request(
                    (
                        f"/api/projects/{_encoded_account_project()}"
                        f"/knowledge/weknora/accounts/{account_id}/sync"
                    ),
                    "POST",
                    json={
                        "base_url": cleaned_url,
                        "api_key": weknora_key,
                        "kb_name": cleaned_kb,
                        "max_video_analyses": weknora_max,
                    },
                    timeout=300,
                )
                if sync.get("ok"):
                    st.success("已上传到 WeKnora 知识库")
                    st.session_state["last_weknora_sync"] = sync
                    st.write("上传文件：")
                    for path in sync.get("uploaded", []):
                        st.write(f"- `{path}`")
                else:
                    message = (sync.get("error") or {}).get("message")
                    st.error(f"WeKnora 同步失败：{message}")
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
