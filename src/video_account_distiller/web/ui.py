"""Shared product shell and design system for the Streamlit interface."""

from __future__ import annotations

import html
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import requests
import streamlit as st
from streamlit.components.v2 import component

from video_account_distiller.web import web_state

Theme = Literal["light", "dark"]


@dataclass(frozen=True)
class PageContext:
    """Shared values exposed to every product page."""

    api_url: str
    project_path: str
    theme: Theme


_NAV_ITEMS = (
    ("dashboard", "home.py", "工作台", ":material/home:"),
    ("collect", "pages/quick_collect.py", "采集任务", ":material/add_task:"),
    ("analysis", "pages/account_analysis.py", "账号分析", ":material/monitoring:"),
    ("data", "pages/data_browser.py", "数据中心", ":material/database:"),
    ("import", "pages/import_data.py", "数据导入", ":material/upload_file:"),
    ("reports", "pages/reports.py", "分析报告", ":material/description:"),
    ("settings", "pages/settings.py", "系统设置", ":material/settings:"),
)

_THEME_BRIDGE = component(
    "distiller_theme_bridge",
    html='<span aria-hidden="true"></span>',
    css=":host, span { display: none !important; }",
    js="""
    export default function(component) {
      const { data } = component;
      const storageKey = "video-account-distiller-theme";
      const current = data.theme;
      const url = new URL(window.location.href);
      const fromUrl = url.searchParams.get("theme");
      const stored = window.localStorage.getItem(storageKey);
      if (!fromUrl && (stored === "light" || stored === "dark") && stored !== current) {
        url.searchParams.set("theme", stored);
        window.location.replace(url.toString());
        return;
      }
      window.localStorage.setItem(storageKey, current);
      document.documentElement.dataset.distillerTheme = current;
      document.body.dataset.distillerTheme = current;
    }
    """,
)


def _default_api_url() -> str:
    return os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _default_project_path() -> str:
    return os.environ.get(
        "DISTILLER_DEFAULT_PROJECT",
        str(Path.home() / "video-account-distiller-projects" / "workspace"),
    )


def _resolve_theme() -> Theme:
    query_theme = st.query_params.get("theme")
    if query_theme in {"light", "dark"}:
        theme = cast(Theme, query_theme)
    else:
        state_theme = st.session_state.get("distiller_theme") or web_state.get_state("theme")
        theme = state_theme if state_theme in {"light", "dark"} else "light"
    st.session_state["distiller_theme"] = theme
    web_state.set_state(theme=theme)
    return theme


def _inject_theme_bridge(theme: Theme) -> None:
    """Synchronize the selected theme with browser storage and the parent document."""

    _THEME_BRIDGE(
        key="distiller_theme_bridge",
        data={"theme": theme},
        height=1,
        width=1,
    )


def _inject_design_system(theme: Theme) -> None:
    st.markdown(
        """
        <style>
        :root {
          --ds-font: Inter, "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
          --ds-bg: #f5f7fb;
          --ds-bg-elevated: #fbfcff;
          --ds-surface: #ffffff;
          --ds-surface-soft: #f7f8fc;
          --ds-surface-raised: #ffffff;
          --ds-text: #111a36;
          --ds-text-soft: #52607a;
          --ds-text-muted: #8993a8;
          --ds-primary: #5367f5;
          --ds-primary-strong: #4255e8;
          --ds-primary-soft: #eef0ff;
          --ds-accent: #8b5cf6;
          --ds-success: #17a568;
          --ds-success-soft: #eaf8f1;
          --ds-warning: #d97706;
          --ds-warning-soft: #fff6e8;
          --ds-danger: #dc4c64;
          --ds-danger-soft: #fff0f3;
          --ds-info: #2f75e8;
          --ds-info-soft: #edf5ff;
          --ds-border: #e5e9f2;
          --ds-border-strong: #d7ddea;
          --ds-focus: rgba(83, 103, 245, 0.24);
          --ds-chart-1: #5367f5;
          --ds-chart-2: #9b6df3;
          --ds-chart-3: #3bb9aa;
          --ds-sidebar: rgba(255, 255, 255, 0.92);
          --ds-overlay: rgba(17, 26, 54, 0.46);
          --ds-radius-xs: 6px;
          --ds-radius-sm: 9px;
          --ds-radius-md: 12px;
          --ds-radius-lg: 16px;
          --ds-radius-xl: 20px;
          --ds-shadow-sm: 0 1px 2px rgba(18, 28, 63, 0.04), 0 6px 20px rgba(18, 28, 63, 0.04);
          --ds-shadow-md: 0 16px 44px rgba(31, 41, 81, 0.09);
          --ds-shadow-focus: 0 0 0 3px var(--ds-focus);
          --ds-space-1: 4px;
          --ds-space-2: 8px;
          --ds-space-3: 12px;
          --ds-space-4: 16px;
          --ds-space-5: 20px;
          --ds-space-6: 24px;
          --ds-space-8: 32px;
          --ds-space-10: 40px;
          color-scheme: light;
        }

        html[data-distiller-theme="dark"],
        body[data-distiller-theme="dark"] {
          --ds-bg: #0f1012;
          --ds-bg-elevated: #131518;
          --ds-surface: #1a1c20;
          --ds-surface-soft: #202329;
          --ds-surface-raised: #24272d;
          --ds-text: #f3f4f6;
          --ds-text-soft: #b9bdc7;
          --ds-text-muted: #858b99;
          --ds-primary: #d8b65a;
          --ds-primary-strong: #e4c66f;
          --ds-primary-soft: rgba(216, 182, 90, 0.12);
          --ds-accent: #b99b55;
          --ds-success: #4bc58b;
          --ds-success-soft: rgba(75, 197, 139, 0.12);
          --ds-warning: #e3a74b;
          --ds-warning-soft: rgba(227, 167, 75, 0.12);
          --ds-danger: #ed7184;
          --ds-danger-soft: rgba(237, 113, 132, 0.12);
          --ds-info: #aab7d7;
          --ds-info-soft: rgba(170, 183, 215, 0.10);
          --ds-border: #2d3036;
          --ds-border-strong: #3a3d43;
          --ds-focus: rgba(216, 182, 90, 0.22);
          --ds-chart-1: #d8b65a;
          --ds-chart-2: #eee1b5;
          --ds-chart-3: #75b7ab;
          --ds-sidebar: rgba(18, 19, 22, 0.96);
          --ds-overlay: rgba(0, 0, 0, 0.68);
          --ds-shadow-sm: 0 1px 1px rgba(0, 0, 0, 0.35), 0 12px 28px rgba(0, 0, 0, 0.16);
          --ds-shadow-md: 0 22px 52px rgba(0, 0, 0, 0.34);
          color-scheme: dark;
        }

        html, body, [class*="css"] {
          font-family: var(--ds-font);
        }

        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
          background:
            radial-gradient(circle at 78% 3%, color-mix(in srgb, var(--ds-primary) 7%, transparent) 0, transparent 25rem),
            var(--ds-bg);
          color: var(--ds-text);
        }

        [data-testid="stMainBlockContainer"] {
          max-width: 1480px;
          padding: 1.25rem 2rem 3.5rem;
        }

        [data-testid="stHeader"] {
          background: color-mix(in srgb, var(--ds-bg) 76%, transparent);
          backdrop-filter: blur(16px);
          border-bottom: 1px solid color-mix(in srgb, var(--ds-border) 74%, transparent);
        }

        #MainMenu, footer, [data-testid="stDecoration"] {
          display: none !important;
        }

        [data-testid="stSidebar"] {
          background: var(--ds-sidebar);
          border-right: 1px solid var(--ds-border);
          box-shadow: none;
        }

        [data-testid="stSidebarContent"] {
          padding: 0.75rem 0.8rem 1rem;
        }

        [data-testid="stSidebarNav"] {
          display: none;
        }

        .ds-brand {
          display: flex;
          align-items: center;
          gap: 11px;
          margin: 0.2rem 0.25rem 1.15rem;
          padding: 0.55rem 0.35rem;
        }

        .ds-brand-mark {
          position: relative;
          width: 34px;
          height: 34px;
          flex: 0 0 34px;
          border-radius: 10px;
          background: linear-gradient(145deg, var(--ds-primary), var(--ds-accent));
          box-shadow: 0 9px 24px color-mix(in srgb, var(--ds-primary) 23%, transparent);
        }

        .ds-brand-mark::before,
        .ds-brand-mark::after {
          content: "";
          position: absolute;
          bottom: 8px;
          width: 4px;
          border-radius: 4px;
          background: white;
        }

        .ds-brand-mark::before {
          left: 9px;
          height: 11px;
          box-shadow: 7px -5px 0 white, 14px -12px 0 white;
        }

        .ds-brand-name {
          color: var(--ds-text);
          font-size: 0.85rem;
          font-weight: 750;
          line-height: 1.15;
          letter-spacing: -0.01em;
        }

        .ds-brand-subtitle {
          color: var(--ds-text-muted);
          font-size: 0.65rem;
          margin-top: 3px;
        }

        .ds-nav-label {
          color: var(--ds-text-muted);
          font-size: 0.65rem;
          font-weight: 700;
          letter-spacing: 0.12em;
          margin: 0.4rem 0.65rem 0.45rem;
          text-transform: uppercase;
        }

        [data-testid="stPageLink"] a {
          min-height: 42px;
          padding: 0.55rem 0.72rem;
          margin: 2px 0;
          border: 1px solid transparent;
          border-radius: var(--ds-radius-sm);
          color: var(--ds-text-soft);
          font-size: 0.84rem;
          font-weight: 560;
          transition: all 160ms ease;
        }

        [data-testid="stPageLink"] a:hover {
          color: var(--ds-primary);
          background: var(--ds-primary-soft);
          border-color: color-mix(in srgb, var(--ds-primary) 14%, transparent);
        }

        [data-testid="stPageLink"] a[aria-current="page"] {
          color: var(--ds-primary);
          background: var(--ds-primary-soft);
          border-color: color-mix(in srgb, var(--ds-primary) 17%, transparent);
          font-weight: 700;
        }

        .ds-sidebar-status {
          margin: 1rem 0.15rem 0.2rem;
          padding: 0.9rem;
          border: 1px solid var(--ds-border);
          border-radius: var(--ds-radius-md);
          background: color-mix(in srgb, var(--ds-surface) 82%, transparent);
          box-shadow: var(--ds-shadow-sm);
        }

        .ds-status-title {
          color: var(--ds-text);
          font-size: 0.72rem;
          font-weight: 700;
          margin-bottom: 0.65rem;
        }

        .ds-status-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          color: var(--ds-text-muted);
          font-size: 0.68rem;
          margin-top: 0.45rem;
        }

        .ds-status-value {
          color: var(--ds-text-soft);
          font-weight: 650;
        }

        .ds-dot {
          display: inline-block;
          width: 7px;
          height: 7px;
          margin-right: 6px;
          border-radius: 50%;
          background: var(--ds-text-muted);
        }

        .ds-dot.success { background: var(--ds-success); box-shadow: 0 0 0 3px var(--ds-success-soft); }
        .ds-dot.warning { background: var(--ds-warning); box-shadow: 0 0 0 3px var(--ds-warning-soft); }

        .ds-page-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 1.5rem;
          margin: 0.15rem 0 1rem;
          min-height: 64px;
        }

        .ds-page-kicker {
          color: var(--ds-primary);
          font-size: 0.68rem;
          font-weight: 750;
          letter-spacing: 0.12em;
          margin-bottom: 0.35rem;
          text-transform: uppercase;
        }

        .ds-page-title {
          color: var(--ds-text);
          font-size: clamp(1.45rem, 2vw, 1.9rem);
          font-weight: 760;
          line-height: 1.15;
          letter-spacing: -0.035em;
          margin: 0;
        }

        .ds-page-description {
          color: var(--ds-text-muted);
          font-size: 0.82rem;
          line-height: 1.55;
          margin-top: 0.45rem;
          max-width: 760px;
        }

        .ds-avatar {
          display: grid;
          place-items: center;
          width: 36px;
          height: 36px;
          margin: 2px auto 0;
          border: 1px solid color-mix(in srgb, var(--ds-primary) 30%, var(--ds-border));
          border-radius: 50%;
          background: linear-gradient(145deg, var(--ds-primary-soft), var(--ds-surface-raised));
          color: var(--ds-primary);
          font-size: 0.66rem;
          font-weight: 780;
          box-shadow: var(--ds-shadow-sm);
        }

        .ds-section-head {
          display: flex;
          align-items: flex-end;
          justify-content: space-between;
          gap: 1rem;
          margin: 1.7rem 0 0.8rem;
        }

        .ds-section-title {
          color: var(--ds-text);
          font-size: 1rem;
          font-weight: 720;
          letter-spacing: -0.015em;
        }

        .ds-section-copy {
          color: var(--ds-text-muted);
          font-size: 0.73rem;
          margin-top: 0.2rem;
        }

        .ds-metric {
          position: relative;
          overflow: hidden;
          min-height: 126px;
          padding: 1.05rem 1.08rem;
          border: 1px solid var(--ds-border);
          border-radius: var(--ds-radius-lg);
          background: var(--ds-surface);
          box-shadow: var(--ds-shadow-sm);
          transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
        }

        .ds-metric::after {
          content: "";
          position: absolute;
          right: -34px;
          bottom: -46px;
          width: 116px;
          height: 116px;
          border-radius: 50%;
          background: color-mix(in srgb, var(--metric-color, var(--ds-primary)) 9%, transparent);
          filter: blur(2px);
        }

        .ds-metric:hover {
          transform: translateY(-2px);
          border-color: color-mix(in srgb, var(--metric-color, var(--ds-primary)) 30%, var(--ds-border));
          box-shadow: var(--ds-shadow-md);
        }

        .ds-metric-label {
          color: var(--ds-text-muted);
          font-size: 0.72rem;
          font-weight: 600;
        }

        .ds-metric-value {
          color: var(--ds-text);
          font-size: 1.65rem;
          font-weight: 760;
          line-height: 1.15;
          letter-spacing: -0.04em;
          margin-top: 0.55rem;
        }

        .ds-metric-delta {
          color: var(--ds-success);
          font-size: 0.68rem;
          font-weight: 650;
          margin-top: 0.5rem;
        }

        .ds-metric-delta.neutral { color: var(--ds-text-muted); }
        .ds-metric-delta.warning { color: var(--ds-warning); }

        .ds-stepper {
          display: grid;
          grid-template-columns: repeat(var(--step-count, 4), minmax(0, 1fr));
          gap: 0;
          margin: 0.6rem 0 1.25rem;
          padding: 1.15rem 1.2rem;
          border: 1px solid var(--ds-border);
          border-radius: var(--ds-radius-lg);
          background: var(--ds-surface);
          box-shadow: var(--ds-shadow-sm);
        }

        .ds-step {
          position: relative;
          display: flex;
          align-items: center;
          gap: 0.65rem;
          min-width: 0;
        }

        .ds-step:not(:last-child)::after {
          content: "";
          position: absolute;
          top: 15px;
          left: calc(31px + 0.65rem);
          right: 0.8rem;
          height: 1px;
          background: var(--ds-border-strong);
        }

        .ds-step-number {
          position: relative;
          z-index: 1;
          display: grid;
          place-items: center;
          width: 30px;
          height: 30px;
          flex: 0 0 30px;
          border: 1px solid var(--ds-border-strong);
          border-radius: 50%;
          background: var(--ds-surface);
          color: var(--ds-text-muted);
          font-size: 0.7rem;
          font-weight: 750;
        }

        .ds-step.active .ds-step-number,
        .ds-step.complete .ds-step-number {
          color: white;
          border-color: var(--ds-primary);
          background: var(--ds-primary);
          box-shadow: 0 0 0 5px var(--ds-primary-soft);
        }

        html[data-distiller-theme="dark"] .ds-step.active .ds-step-number,
        html[data-distiller-theme="dark"] .ds-step.complete .ds-step-number {
          color: #17140d;
        }

        .ds-step-label {
          position: relative;
          z-index: 1;
          overflow: hidden;
          color: var(--ds-text-muted);
          background: var(--ds-surface);
          font-size: 0.7rem;
          font-weight: 620;
          padding-right: 0.8rem;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .ds-step.active .ds-step-label,
        .ds-step.complete .ds-step-label {
          color: var(--ds-primary);
          font-weight: 720;
        }

        .ds-card-copy {
          color: var(--ds-text-muted);
          font-size: 0.76rem;
          line-height: 1.6;
        }

        .ds-mini-title {
          color: var(--ds-text);
          font-size: 0.85rem;
          font-weight: 700;
          margin-bottom: 0.15rem;
        }

        .ds-badge {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          padding: 0.22rem 0.52rem;
          border: 1px solid transparent;
          border-radius: 999px;
          background: var(--ds-primary-soft);
          color: var(--ds-primary);
          font-size: 0.64rem;
          font-weight: 680;
          white-space: nowrap;
        }

        .ds-badge.success { background: var(--ds-success-soft); color: var(--ds-success); }
        .ds-badge.warning { background: var(--ds-warning-soft); color: var(--ds-warning); }
        .ds-badge.danger { background: var(--ds-danger-soft); color: var(--ds-danger); }
        .ds-badge.neutral { background: var(--ds-surface-soft); color: var(--ds-text-muted); border-color: var(--ds-border); }

        .ds-callout {
          padding: 0.8rem 0.9rem;
          border: 1px solid color-mix(in srgb, var(--ds-primary) 18%, var(--ds-border));
          border-radius: var(--ds-radius-md);
          background: var(--ds-primary-soft);
          color: var(--ds-text-soft);
          font-size: 0.73rem;
          line-height: 1.55;
        }

        .ds-task-row {
          display: grid;
          grid-template-columns: minmax(0, 1.45fr) minmax(90px, 0.55fr) minmax(86px, 0.5fr);
          align-items: center;
          gap: 0.75rem;
          padding: 0.74rem 0;
          border-bottom: 1px solid var(--ds-border);
        }

        .ds-task-row:last-child { border-bottom: 0; }
        .ds-task-name { color: var(--ds-text); font-size: 0.76rem; font-weight: 650; }
        .ds-task-meta { color: var(--ds-text-muted); font-size: 0.66rem; margin-top: 0.2rem; }

        .ds-progress {
          height: 5px;
          overflow: hidden;
          border-radius: 999px;
          background: var(--ds-surface-soft);
        }

        .ds-progress > span {
          display: block;
          height: 100%;
          border-radius: inherit;
          background: var(--ds-primary);
        }

        .ds-empty {
          display: grid;
          place-items: center;
          min-height: 190px;
          padding: 2rem;
          border: 1px dashed var(--ds-border-strong);
          border-radius: var(--ds-radius-lg);
          background: color-mix(in srgb, var(--ds-surface-soft) 74%, transparent);
          text-align: center;
        }

        .ds-empty-mark {
          display: grid;
          place-items: center;
          width: 48px;
          height: 48px;
          border-radius: 15px;
          background: var(--ds-primary-soft);
          color: var(--ds-primary);
          font-size: 1.25rem;
          font-weight: 760;
          margin: 0 auto 0.75rem;
        }

        .ds-empty-title { color: var(--ds-text); font-size: 0.9rem; font-weight: 720; }
        .ds-empty-copy { color: var(--ds-text-muted); font-size: 0.72rem; margin-top: 0.35rem; }

        div[data-testid="stVerticalBlockBorderWrapper"] {
          border-color: var(--ds-border) !important;
          border-radius: var(--ds-radius-lg) !important;
          background: var(--ds-surface);
          box-shadow: var(--ds-shadow-sm);
        }

        div[data-testid="stVerticalBlockBorderWrapper"] > div {
          padding: 0.2rem;
        }

        [data-testid="stMetric"] {
          padding: 0.9rem 1rem;
          border: 1px solid var(--ds-border);
          border-radius: var(--ds-radius-md);
          background: var(--ds-surface);
        }

        [data-testid="stMetricLabel"] { color: var(--ds-text-muted); }
        [data-testid="stMetricValue"] { color: var(--ds-text); font-weight: 730; }

        h1, h2, h3, h4, h5, h6, p, label {
          color: var(--ds-text);
        }

        h2, h3 {
          letter-spacing: -0.02em;
        }

        [data-testid="stCaptionContainer"] {
          color: var(--ds-text-muted);
        }

        hr {
          border-color: var(--ds-border) !important;
        }

        .stButton > button,
        .stDownloadButton > button,
        [data-testid="stFormSubmitButton"] > button,
        [data-testid="stPopover"] > button {
          min-height: 40px;
          border: 1px solid var(--ds-border-strong);
          border-radius: var(--ds-radius-sm);
          background: var(--ds-surface);
          color: var(--ds-text-soft);
          font-weight: 650;
          box-shadow: none;
          transition: all 150ms ease;
        }

        .stButton > button p,
        .stDownloadButton > button p,
        [data-testid="stFormSubmitButton"] > button p,
        [data-testid="stPopover"] > button p {
          white-space: nowrap;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover,
        [data-testid="stFormSubmitButton"] > button:hover,
        [data-testid="stPopover"] > button:hover {
          color: var(--ds-primary);
          border-color: color-mix(in srgb, var(--ds-primary) 46%, var(--ds-border));
          background: var(--ds-primary-soft);
          transform: translateY(-1px);
        }

        .stButton > button:focus-visible,
        .stDownloadButton > button:focus-visible,
        [data-testid="stFormSubmitButton"] > button:focus-visible {
          box-shadow: var(--ds-shadow-focus);
        }

        .stButton > button[kind="primary"],
        [data-testid="stFormSubmitButton"] > button[kind="primary"] {
          color: white;
          border-color: var(--ds-primary);
          background: linear-gradient(135deg, var(--ds-primary), var(--ds-primary-strong));
          box-shadow: 0 8px 20px color-mix(in srgb, var(--ds-primary) 20%, transparent);
        }

        html[data-distiller-theme="dark"] .stButton > button[kind="primary"],
        html[data-distiller-theme="dark"] [data-testid="stFormSubmitButton"] > button[kind="primary"] {
          color: #17140d;
        }

        button:disabled {
          opacity: 0.46 !important;
          cursor: not-allowed !important;
          transform: none !important;
        }

        input, textarea,
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div {
          color: var(--ds-text) !important;
          border-color: var(--ds-border-strong) !important;
          border-radius: var(--ds-radius-sm) !important;
          background: var(--ds-surface) !important;
          box-shadow: none !important;
        }

        input:focus, textarea:focus,
        [data-baseweb="select"] > div:focus-within,
        [data-baseweb="input"] > div:focus-within {
          border-color: var(--ds-primary) !important;
          box-shadow: var(--ds-shadow-focus) !important;
        }

        [data-baseweb="popover"],
        [data-baseweb="menu"],
        [role="listbox"] {
          color: var(--ds-text) !important;
          border-color: var(--ds-border) !important;
          background: var(--ds-surface-raised) !important;
        }

        [data-testid="stFileUploaderDropzone"] {
          min-height: 126px;
          border: 1px dashed color-mix(in srgb, var(--ds-primary) 34%, var(--ds-border-strong));
          border-radius: var(--ds-radius-lg);
          background: linear-gradient(145deg, var(--ds-primary-soft), var(--ds-surface));
        }

        [data-testid="stFileUploaderDropzone"]:hover {
          border-color: var(--ds-primary);
        }

        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
          overflow: hidden;
          border: 1px solid var(--ds-border);
          border-radius: var(--ds-radius-md);
          background: var(--ds-surface);
        }

        [data-testid="stExpander"] {
          overflow: hidden;
          border-color: var(--ds-border) !important;
          border-radius: var(--ds-radius-md) !important;
          background: var(--ds-surface);
        }

        [data-testid="stAlert"] {
          border-radius: var(--ds-radius-md);
          border-color: var(--ds-border);
        }

        [data-testid="stProgress"] > div > div {
          background: var(--ds-primary);
        }

        [data-baseweb="tab-list"] {
          gap: 1.25rem;
          border-bottom: 1px solid var(--ds-border);
        }

        [data-baseweb="tab"] {
          color: var(--ds-text-muted);
          font-weight: 650;
        }

        [data-baseweb="tab"][aria-selected="true"] {
          color: var(--ds-primary);
        }

        [data-testid="stForm"] {
          border: 0;
          padding: 0;
        }

        [data-testid="stIFrame"] {
          min-height: 0 !important;
        }

        @media (max-width: 980px) {
          [data-testid="stMainBlockContainer"] { padding: 1rem 1rem 3rem; }
          .ds-stepper { grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 1rem; }
          .ds-step:nth-child(2)::after { display: none; }
          .ds-task-row { grid-template-columns: minmax(0, 1fr) 86px; }
          .ds-task-row > :nth-child(2) { display: none; }
        }

        @media (max-width: 640px) {
          .ds-page-header { display: block; }
          .ds-page-description { max-width: none; }
          .ds-stepper { grid-template-columns: 1fr; }
          .ds-step::after { display: none !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _inject_theme_bridge(theme)


def _render_sidebar(current_page: str) -> tuple[str, str]:
    if "global_api_url" not in st.session_state:
        st.session_state["global_api_url"] = str(
            st.session_state.get("api_url", _default_api_url())
        ).rstrip("/")
    if "global_project_path" not in st.session_state:
        st.session_state["global_project_path"] = str(
            st.session_state.get("project_path", _default_project_path())
        )

    with st.sidebar:
        st.markdown(
            """
            <div class="ds-brand">
              <div class="ds-brand-mark"></div>
              <div>
                <div class="ds-brand-name">Video Account<br>Distiller</div>
                <div class="ds-brand-subtitle">视频账号蒸馏平台</div>
              </div>
            </div>
            <div class="ds-nav-label">产品导航</div>
            """,
            unsafe_allow_html=True,
        )

        for _page_key, path, label, icon in _NAV_ITEMS:
            st.page_link(
                path,
                label=label,
                icon=icon,
                use_container_width=True,
                disabled=False,
            )

        st.markdown('<div class="ds-nav-label">工作区</div>', unsafe_allow_html=True)
        with st.expander("连接与项目", expanded=False, icon=":material/tune:"):
            if "global_api_url" not in st.session_state:
                st.session_state["global_api_url"] = web_state.get_state(
                    "api_url", "http://127.0.0.1:8000"
                )
            if "global_project_path" not in st.session_state:
                st.session_state["global_project_path"] = web_state.get_state(
                    "project_path",
                    str(Path.home() / "video-account-distiller-projects" / "workspace"),
                )
            api_url = st.text_input("API 地址", key="global_api_url")
            project_path = st.text_input("项目路径", key="global_project_path")
            st.session_state["api_url"] = api_url.rstrip("/")
            st.session_state["project_path"] = project_path
            # Persist so reloads / theme toggles / reconnects restore them.
            web_state.set_state(api_url=api_url.rstrip("/"), project_path=project_path)

            action_a, action_b = st.columns(2)
            if action_a.button(
                "检测",
                key=f"check_connection_{current_page}",
                icon=":material/cable:",
                use_container_width=True,
            ):
                try:
                    response = requests.get(f"{api_url.rstrip('/')}/api/health", timeout=5)
                    st.session_state["sidebar_api_status"] = (
                        "正常" if response.ok else f"HTTP {response.status_code}"
                    )
                except requests.RequestException:
                    st.session_state["sidebar_api_status"] = "未连接"
            if action_b.button(
                "初始化",
                key=f"init_project_{current_page}",
                icon=":material/create_new_folder:",
                use_container_width=True,
                disabled=not bool(project_path.strip()),
            ):
                try:
                    response = requests.post(
                        f"{api_url.rstrip('/')}/api/projects/init",
                        json={"path": project_path, "name": Path(project_path).name},
                        timeout=10,
                    )
                    payload = response.json()
                    if response.ok and payload.get("ok"):
                        st.session_state["sidebar_project_status"] = "已就绪"
                        st.toast("项目工作区已就绪")
                    else:
                        st.session_state["sidebar_project_status"] = "需检查"
                except (requests.RequestException, ValueError):
                    st.session_state["sidebar_project_status"] = "未连接"

        api_status = str(st.session_state.get("sidebar_api_status", "待检测"))
        project_status = str(st.session_state.get("sidebar_project_status", "待检测"))
        api_tone = "success" if api_status == "正常" else "warning"
        project_tone = "success" if project_status == "已就绪" else "warning"
        st.markdown(
            f"""
            <div class="ds-sidebar-status">
              <div class="ds-status-title">运行状态</div>
              <div class="ds-status-row">
                <span><i class="ds-dot {api_tone}"></i>API 服务</span>
                <span class="ds-status-value">{html.escape(api_status)}</span>
              </div>
              <div class="ds-status-row">
                <span><i class="ds-dot {project_tone}"></i>当前项目</span>
                <span class="ds-status-value">{html.escape(project_status)}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return (
        str(st.session_state["api_url"]).rstrip("/"),
        str(st.session_state["project_path"]),
    )


def _render_header(
    *,
    page_key: str,
    title: str,
    description: str,
    eyebrow: str,
    theme: Theme,
) -> Theme:
    title_column, actions_column = st.columns([6.4, 3.6], vertical_alignment="top")
    with title_column:
        st.markdown(
            f"""
            <div class="ds-page-header">
              <div>
                <div class="ds-page-kicker">{html.escape(eyebrow)}</div>
                <h1 class="ds-page-title">{html.escape(title)}</h1>
                <div class="ds-page-description">{html.escape(description)}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with actions_column:
        button_help, button_notice, theme_column, avatar_column = st.columns([1, 1, 1.45, 0.52])
        with button_help:
            if st.button(
                "帮助",
                key=f"header_help_{page_key}",
                icon=":material/help:",
                use_container_width=True,
            ):
                st.toast("帮助中心正在整理中；当前可在系统设置中查看 API 文档。")
        with button_notice:
            if st.button(
                "通知",
                key=f"header_notice_{page_key}",
                icon=":material/notifications:",
                use_container_width=True,
            ):
                st.toast("暂无新的系统通知")

        if st.session_state.get("_theme_control_source") != theme:
            st.session_state["distiller_theme_toggle"] = theme == "dark"
            st.session_state["_theme_control_source"] = theme
        with theme_column:
            dark_enabled = st.toggle(
                "夜间模式",
                key="distiller_theme_toggle",
                help="主题选择会保存在当前浏览器",
            )
        with avatar_column:
            st.markdown(
                '<div class="ds-avatar" title="当前用户">DA</div>',
                unsafe_allow_html=True,
            )
        selected_theme: Theme = "dark" if dark_enabled else "light"
        if selected_theme != theme:
            st.session_state["distiller_theme"] = selected_theme
            st.session_state["_theme_control_source"] = selected_theme
            st.query_params["theme"] = selected_theme
            st.rerun()
    return selected_theme


def setup_page(
    page_key: str,
    title: str,
    description: str,
    *,
    eyebrow: str = "VIDEO INTELLIGENCE",
) -> PageContext:
    """Apply the product shell and return shared connection values."""

    theme = _resolve_theme()
    _inject_design_system(theme)
    api_url, project_path = _render_sidebar(page_key)
    selected_theme = _render_header(
        page_key=page_key,
        title=title,
        description=description,
        eyebrow=eyebrow,
        theme=theme,
    )
    return PageContext(api_url=api_url, project_path=project_path, theme=selected_theme)


def section_header(title: str, description: str = "") -> None:
    st.markdown(
        f"""
        <div class="ds-section-head">
          <div>
            <div class="ds-section-title">{html.escape(title)}</div>
            <div class="ds-section-copy">{html.escape(description)}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(
    label: str,
    value: str | int,
    *,
    delta: str = "数据已同步",
    tone: Literal["primary", "purple", "green", "orange"] = "primary",
    delta_tone: Literal["positive", "neutral", "warning"] = "positive",
) -> None:
    colors = {
        "primary": "var(--ds-primary)",
        "purple": "var(--ds-accent)",
        "green": "var(--ds-success)",
        "orange": "var(--ds-warning)",
    }
    delta_class = "" if delta_tone == "positive" else delta_tone
    st.markdown(
        f"""
        <div class="ds-metric" style="--metric-color:{colors[tone]}">
          <div class="ds-metric-label">{html.escape(label)}</div>
          <div class="ds-metric-value">{html.escape(str(value))}</div>
          <div class="ds-metric-delta {delta_class}">{html.escape(delta)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def stepper(labels: list[str], *, active: int = 1, completed: int = 0) -> None:
    steps: list[str] = []
    for index, label in enumerate(labels, start=1):
        state = "complete" if index <= completed else "active" if index == active else ""
        steps.append(
            f'<div class="ds-step {state}">'
            f'<span class="ds-step-number">{index}</span>'
            f'<span class="ds-step-label">{html.escape(label)}</span>'
            "</div>"
        )
    st.markdown(
        f'<div class="ds-stepper" style="--step-count:{len(labels)}">{"".join(steps)}</div>',
        unsafe_allow_html=True,
    )


def badge(label: str, tone: str = "neutral") -> str:
    safe_tone = tone if tone in {"success", "warning", "danger", "neutral"} else ""
    return f'<span class="ds-badge {safe_tone}">{html.escape(label)}</span>'


def empty_state(title: str, description: str, *, mark: str = "—") -> None:
    st.markdown(
        f"""
        <div class="ds-empty">
          <div>
            <div class="ds-empty-mark">{html.escape(mark)}</div>
            <div class="ds-empty-title">{html.escape(title)}</div>
            <div class="ds-empty-copy">{html.escape(description)}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def task_row(
    name: str,
    meta: str,
    *,
    status: str,
    progress: float,
    tone: str = "neutral",
) -> str:
    progress_value = max(0.0, min(float(progress), 1.0))
    return (
        '<div class="ds-task-row"><div>'
        f'<div class="ds-task-name">{html.escape(name)}</div>'
        f'<div class="ds-task-meta">{html.escape(meta)}</div>'
        "</div>"
        f'<div class="ds-progress"><span style="width:{progress_value:.0%}"></span></div>'
        f"<div>{badge(status, tone)}</div></div>"
    )
