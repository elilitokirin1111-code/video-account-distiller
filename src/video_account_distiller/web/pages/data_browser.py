"""Normalized data browser with provenance filters."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
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
    page_title="数据中心 · Video Account Distiller",
    page_icon=":material/database:",
    layout="wide",
    initial_sidebar_state="expanded",
)

TABLE_LABELS = {
    "accounts": "账号数据",
    "account_snapshots": "账号快照",
    "videos": "视频数据",
    "metric_snapshots": "指标快照",
    "comments": "评论数据",
    "transcripts": "字幕数据",
    "audience_profiles": "粉丝画像",
}
TIER_LABELS = {
    "全部来源": None,
    "公开数据": "public",
    "授权私域": "authorized_private",
    "模型推断": "model_inferred",
    "未知来源": "unknown",
}
PLATFORM_LABELS = {
    "全部平台": None,
    "抖音": "douyin",
    "小红书": "xiaohongshu",
    "B站": "bilibili",
    "YouTube": "youtube",
    "TikTok": "tiktok",
    "Instagram": "instagram",
    "微信视频号": "wechat-channels",
}


def _get(api_url: str, path: str, **params: Any) -> dict[str, Any]:
    try:
        response = requests.get(f"{api_url}{path}", params=params, timeout=30)
        payload: Any = response.json()
        return payload if isinstance(payload, dict) else {"ok": False}
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "detail": str(exc)}


def _parse_timestamp(row: dict[str, Any]) -> datetime | None:
    for key in (
        "published_at",
        "snapshot_at",
        "created_at",
        "updated_at",
        "imported_at",
        "captured_at",
    ):
        value = row.get(key)
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    platform: str | None,
    keyword: str,
    recent_days: int | None,
) -> list[dict[str, Any]]:
    """Apply display-only filters to the current API page."""

    needle = keyword.strip().casefold()
    cutoff = datetime.now(UTC) - timedelta(days=recent_days) if recent_days is not None else None
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if platform:
            platform_value = str(row.get("platform") or row.get("source_platform") or "")
            if platform_value.casefold() != platform.casefold():
                continue
        if needle:
            searchable = " ".join(str(value) for value in row.values()).casefold()
            if needle not in searchable:
                continue
        if cutoff is not None:
            timestamp = _parse_timestamp(row)
            if timestamp is not None and timestamp < cutoff:
                continue
        filtered.append(row)
    return filtered


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


context = setup_page(
    "data",
    "数据中心",
    "统一浏览标准化账号、视频、评论与粉丝画像，并追溯每条数据的来源。",
    eyebrow="DATA EXPLORER",
)
encoded_project = quote(context.project_path, safe="")

with st.container(border=True):
    st.markdown("#### 筛选与查询")
    st.caption("平台、关键词和时间范围会在当前结果页内继续筛选。")
    with st.form("data_browser_filters"):
        first_row = st.columns([1.2, 1, 1, 0.85])
        with first_row[0]:
            table = st.selectbox(
                "数据表",
                list(TABLE_LABELS),
                format_func=lambda value: TABLE_LABELS[value],
                index=list(TABLE_LABELS).index("audience_profiles"),
            )
        with first_row[1]:
            tier_label = st.selectbox("来源", list(TIER_LABELS))
        with first_row[2]:
            platform_label = st.selectbox("平台", list(PLATFORM_LABELS))
        with first_row[3]:
            page_size = st.selectbox("每页记录", [20, 50, 100, 200], index=1)

        second_row = st.columns([1.2, 1, 0.55, 0.45])
        with second_row[0]:
            keyword = st.text_input(
                "关键词",
                placeholder="搜索账号、标题、评论或字段值",
            )
        with second_row[1]:
            time_label = st.selectbox(
                "时间范围",
                ["全部时间", "近 7 天", "近 30 天", "近 90 天"],
                index=2,
            )
        with second_row[2]:
            query_clicked = st.form_submit_button(
                "查询",
                type="primary",
                icon=":material/search:",
                use_container_width=True,
                disabled=not bool(context.project_path),
            )
        with second_row[3]:
            reset_clicked = st.form_submit_button(
                "重置",
                icon=":material/restart_alt:",
                use_container_width=True,
            )

if reset_clicked:
    st.session_state.pop("browser_result", None)
    st.session_state["browser_offset"] = 0
    st.rerun()

if query_clicked:
    st.session_state["browser_offset"] = 0
    params: dict[str, Any] = {
        "table": table,
        "limit": int(page_size),
        "offset": 0,
    }
    source_tier = TIER_LABELS[tier_label]
    if source_tier:
        params["source_tier"] = source_tier
    with st.spinner("正在查询标准化数据…"):
        result = _get(context.api_url, f"/api/projects/{encoded_project}/data", **params)
    if result.get("ok"):
        st.session_state["browser_result"] = result.get("data", {})
        st.session_state["browser_query"] = {
            "table": table,
            "tier_label": tier_label,
            "platform": PLATFORM_LABELS[platform_label],
            "keyword": keyword,
            "recent_days": {
                "全部时间": None,
                "近 7 天": 7,
                "近 30 天": 30,
                "近 90 天": 90,
            }[time_label],
            "page_size": int(page_size),
        }
    else:
        st.error(f"查询失败：{result.get('detail') or result.get('error')}")

data = st.session_state.get("browser_result")
query_state = st.session_state.get("browser_query", {})
if isinstance(data, dict):
    raw_rows_value = data.get("rows")
    raw_rows = (
        [item for item in raw_rows_value if isinstance(item, dict)]
        if isinstance(raw_rows_value, list)
        else []
    )
    rows = _filter_rows(
        raw_rows,
        platform=query_state.get("platform"),
        keyword=str(query_state.get("keyword") or ""),
        recent_days=query_state.get("recent_days"),
    )

    section_header("查询结果", "表格、导出和分页都使用同一套主题与字段视图。")
    toolbar_left, toolbar_right = st.columns([3, 1], vertical_alignment="center")
    with toolbar_left:
        metric_columns = st.columns(3)
        metric_columns[0].metric("总记录", int(data.get("total", 0) or 0))
        metric_columns[1].metric("当前显示", len(rows))
        metric_columns[2].metric(
            "来源类型",
            len(data.get("source_tier_counts", {}) or {}),
        )
    with toolbar_right:
        if rows:
            st.download_button(
                "导出当前结果",
                data=_rows_to_csv(rows).encode("utf-8-sig"),
                file_name=f"{query_state.get('table', 'distiller-data')}.csv",
                mime="text/csv",
                icon=":material/download:",
                use_container_width=True,
            )

    if rows:
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            height=min(590, 88 + len(rows) * 35),
        )
    else:
        empty_state(
            "没有匹配的数据",
            "调整来源、平台、时间或关键词后重新查询。",
            mark="0",
        )

    total = int(data.get("total", 0) or 0)
    offset = int(st.session_state.get("browser_offset", 0))
    current_page = offset // max(int(query_state.get("page_size", 50)), 1) + 1
    total_pages = max(
        1,
        (total + int(query_state.get("page_size", 50)) - 1)
        // int(query_state.get("page_size", 50)),
    )
    previous_column, page_column, next_column = st.columns([1, 4, 1])
    previous_clicked = previous_column.button(
        "上一页",
        icon=":material/chevron_left:",
        use_container_width=True,
        disabled=offset <= 0,
    )
    page_column.markdown(
        f"<div style='text-align:center;padding:.65rem;color:var(--ds-text-muted);"
        f"font-size:.75rem'>第 {current_page} / {total_pages} 页</div>",
        unsafe_allow_html=True,
    )
    next_clicked = next_column.button(
        "下一页",
        icon=":material/chevron_right:",
        use_container_width=True,
        disabled=offset + int(query_state.get("page_size", 50)) >= total,
    )

    if previous_clicked or next_clicked:
        next_offset = max(
            0,
            offset
            + (
                -int(query_state.get("page_size", 50))
                if previous_clicked
                else int(query_state.get("page_size", 50))
            ),
        )
        request_params: dict[str, Any] = {
            "table": query_state.get("table", "audience_profiles"),
            "limit": int(query_state.get("page_size", 50)),
            "offset": next_offset,
        }
        query_tier = TIER_LABELS.get(str(query_state.get("tier_label") or "全部来源"))
        if query_tier:
            request_params["source_tier"] = query_tier
        page_result = _get(
            context.api_url,
            f"/api/projects/{encoded_project}/data",
            **request_params,
        )
        if page_result.get("ok"):
            st.session_state["browser_result"] = page_result.get("data", {})
            st.session_state["browser_offset"] = next_offset
            st.rerun()
else:
    section_header("数据视图", "先设置筛选条件并执行查询。")
    empty_state(
        "等待第一次查询",
        "选择数据表与来源后，点击“查询”加载标准化记录。",
        mark="⌕",
    )

section_header("导入来源记录", "追溯授权、校验与标准化过程。")
with st.container(border=True):
    if context.project_path:
        history_params: dict[str, Any] = {}
        selected_tier = TIER_LABELS.get(tier_label)
        if selected_tier:
            history_params["source_tier"] = selected_tier
        history = _get(
            context.api_url,
            f"/api/projects/{encoded_project}/imports",
            **history_params,
        )
        if history.get("ok"):
            receipts_value = (
                history.get("data", {}).get("receipts", [])
                if isinstance(history.get("data"), dict)
                else []
            )
            receipts = receipts_value if isinstance(receipts_value, list) else []
            if receipts:
                st.dataframe(receipts, use_container_width=True, hide_index=True)
            else:
                st.markdown(badge("暂无匹配记录", "neutral"), unsafe_allow_html=True)
        else:
            st.caption("连接 API 后即可查看导入来源。")
