"""Shared product shell and design system for the Streamlit interface."""

from __future__ import annotations

import html
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests
import streamlit as st
from streamlit.components.v2 import component

from video_account_distiller.web import web_state
from video_account_distiller.web.loading import task_progress_markup

Theme = Literal["light", "dark"]


@dataclass(frozen=True)
class PageContext:
    """Shared values exposed to every product page."""

    api_url: str
    project_path: str
    theme: Theme


_NAV_ITEMS = (
    ("dashboard", "home.py", "概览", ":material/space_dashboard:"),
    ("collect", "pages/quick_collect.py", "新建蒸馏", ":material/add_circle:"),
    ("reports", "pages/reports.py", "报告", ":material/article:"),
    ("settings", "pages/settings.py", "设置", ":material/settings:"),
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
      if (url.searchParams.has("theme")) {
        url.searchParams.delete("theme");
        history.replaceState(null, "", url.toString());
      }
      const stored = window.localStorage.getItem(storageKey);
      if (stored !== current) {
        window.localStorage.setItem(storageKey, current);
      }
      document.documentElement.dataset.distillerTheme = current;
      document.body.dataset.distillerTheme = current;
    }
    """,
)


_DIAG_BRIDGE = component(
    "distiller_sidebar_diag",
    html='<span aria-hidden="true"></span>',
    css=":host, span { display: none !important; }",
    js="""
    export default function() {
      function update() {
        const doc = window.parent.document;
        const nodes = doc.querySelectorAll('#ds-sidebar-diag, #ds-page-diag');
        if (!nodes.length) return;
        const sidebar = doc.querySelector('[data-testid="stSidebar"]');
        const visible = sidebar ? sidebar.getBoundingClientRect().width >= 8 : false;
        const text = 'build 20260818c · 窗口 ' + window.parent.innerWidth + 'px · 侧边栏 '
          + (visible ? '可见' : '隐藏');
        nodes.forEach(function(el) { el.textContent = text; });
      }
      // One-shot recovery only: if the browser remembered a collapsed sidebar,
      // expand it once on page load. Users can still collapse/expand freely
      // afterwards. The narrow mobile layout keeps its bottom navigation.
      function expandOnce() {
        const doc = window.parent.document;
        if (window.parent.innerWidth < 641) return;
        const button = doc.querySelector('[data-testid="stExpandSidebarButton"]');
        if (button) button.click();
      }
      update();
      setTimeout(expandOnce, 900);
      const timer = setInterval(update, 800);
      window.addEventListener('beforeunload', function() { clearInterval(timer); });
    }
    """,
)


def _default_api_url() -> str:
    return os.environ.get("DISTILLER_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _inject_sidebar_diagnostics() -> None:
    """Show a small runtime badge with viewport width and sidebar visibility.

    The badge lives in both the sidebar and the main area so it remains
    readable even when the sidebar is collapsed, which makes browser-side
    layout issues diagnosable without opening dev tools.
    """

    st.markdown(
        '<div id="ds-page-diag" class="ds-build-mark">诊断载入中…</div>',
        unsafe_allow_html=True,
    )
    _DIAG_BRIDGE(key="distiller_sidebar_diag_bridge", height=1, width=1)


def _default_project_path() -> str:
    return os.environ.get(
        "DISTILLER_DEFAULT_PROJECT",
        str(Path.home() / "video-account-distiller-projects" / "workspace"),
    )


def _resolve_theme() -> Theme:
    # The UI is fixed to dark mode; light mode was removed to stop theme
    # toggling/reload churn between pages.
    theme: Theme = "dark"
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
          --ds-font: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
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
          --ds-bg: #09090b;
          --ds-bg-elevated: #0d0d10;
          --ds-surface: rgba(28, 28, 30, 0.82);
          --ds-surface-soft: #232326;
          --ds-surface-raised: #2c2c2e;
          --ds-text: #f5f5f7;
          --ds-text-soft: #d1d1d6;
          --ds-text-muted: #8e8e93;
          --ds-primary: #0a84ff;
          --ds-primary-strong: #0071e3;
          --ds-primary-soft: rgba(10, 132, 255, 0.14);
          --ds-accent: #bf5af2;
          --ds-success: #30d158;
          --ds-success-soft: rgba(48, 209, 88, 0.13);
          --ds-warning: #ff9f0a;
          --ds-warning-soft: rgba(255, 159, 10, 0.13);
          --ds-danger: #ff453a;
          --ds-danger-soft: rgba(255, 69, 58, 0.13);
          --ds-info: #64d2ff;
          --ds-info-soft: rgba(100, 210, 255, 0.12);
          --ds-border: rgba(255, 255, 255, 0.10);
          --ds-border-strong: rgba(255, 255, 255, 0.16);
          --ds-focus: rgba(10, 132, 255, 0.28);
          --ds-chart-1: #0a84ff;
          --ds-chart-2: #bf5af2;
          --ds-chart-3: #30d158;
          --ds-sidebar: rgba(20, 20, 22, 0.72);
          --ds-overlay: rgba(0, 0, 0, 0.68);
          --ds-shadow-sm: 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 32px rgba(0, 0, 0, 0.18);
          --ds-shadow-md: 0 24px 64px rgba(0, 0, 0, 0.34);
          color-scheme: dark;
        }

        html, body, [class*="css"] {
          font-family: var(--ds-font);
        }

        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
          background:
            radial-gradient(circle at 74% -8%, rgba(10, 132, 255, 0.10) 0, transparent 30rem),
            radial-gradient(circle at 102% 28%, rgba(191, 90, 242, 0.05) 0, transparent 26rem),
            var(--ds-bg);
          color: var(--ds-text);
        }

        [data-testid="stMainBlockContainer"] {
          max-width: 1280px;
          padding: 2rem 2.4rem 4rem;
        }

        [data-testid="stHeader"] {
          background: color-mix(in srgb, var(--ds-bg) 76%, transparent);
          backdrop-filter: blur(16px);
          border-bottom: 1px solid color-mix(in srgb, var(--ds-border) 74%, transparent);
        }

        #MainMenu, footer, [data-testid="stDecoration"] {
          display: none !important;
        }

        [data-testid="stToolbar"],
        [data-testid="stStatusWidget"],
        [data-testid="stAppDeployButton"] {
          display: none !important;
        }

        /* Streamlit renders the expand-sidebar button inside stToolbar when
           the sidebar is collapsed. Keep that one toolbar visible as a small
           floating control so a collapsed sidebar can always be reopened. */
        [data-testid="stToolbar"]:has([data-testid="stExpandSidebarButton"]) {
          display: flex !important;
          position: fixed;
          top: 0.85rem;
          left: 0.85rem;
          z-index: 999998;
          height: auto;
          background: var(--ds-surface-raised);
          border: 1px solid var(--ds-border);
          border-radius: 11px;
          box-shadow: var(--ds-shadow-md);
        }
        [data-testid="stToolbar"]:has([data-testid="stExpandSidebarButton"])
          [data-testid="stStatusWidget"],
        [data-testid="stToolbar"]:has([data-testid="stExpandSidebarButton"])
          [data-testid="stAppDeployButton"] {
          display: none !important;
        }

        [data-testid="stSidebar"] {
          background: var(--ds-sidebar);
          border-right: 1px solid var(--ds-border);
          box-shadow: 18px 0 44px rgba(0, 0, 0, 0.12);
          backdrop-filter: saturate(150%) blur(28px);
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
          margin: 0.35rem 0.25rem 1.5rem;
          padding: 0.6rem 0.4rem;
        }

        .ds-brand-mark {
          position: relative;
          width: 34px;
          height: 34px;
          flex: 0 0 34px;
          border-radius: 11px;
          background: linear-gradient(145deg, #2997ff, #0066cc 62%, #5856d6);
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
          font-size: 0.94rem;
          font-weight: 680;
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
          min-height: 44px;
          padding: 0.58rem 0.78rem;
          margin: 3px 0;
          border: 1px solid transparent;
          border-radius: 11px;
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
          color: #ffffff;
          background: rgba(255, 255, 255, 0.10);
          border-color: color-mix(in srgb, var(--ds-primary) 17%, transparent);
          font-weight: 650;
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
          margin: 0 0 1.4rem;
          min-height: 72px;
        }

        .ds-page-kicker {
          color: var(--ds-text-muted);
          font-size: 0.72rem;
          font-weight: 600;
          letter-spacing: 0.01em;
          margin-bottom: 0.5rem;
        }

        .ds-page-title {
          color: var(--ds-text);
          font-size: clamp(1.9rem, 3vw, 2.65rem);
          font-weight: 690;
          line-height: 1.15;
          letter-spacing: -0.045em;
          margin: 0;
        }

        .ds-page-description {
          color: var(--ds-text-muted);
          font-size: 0.9rem;
          line-height: 1.6;
          margin-top: 0.65rem;
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
          font-size: 1.08rem;
          font-weight: 650;
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
          min-height: 118px;
          padding: 1.15rem 1.2rem;
          border: 1px solid var(--ds-border);
          border-radius: var(--ds-radius-lg);
          background: var(--ds-surface);
          box-shadow: var(--ds-shadow-sm);
          backdrop-filter: blur(24px);
        }

        .ds-metric-label {
          color: var(--ds-text-muted);
          font-size: 0.72rem;
          font-weight: 600;
        }

        .ds-metric-value {
          color: var(--ds-text);
          font-size: 1.9rem;
          font-weight: 680;
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

        .ds-live-task {
          position: relative;
          overflow: hidden;
          display: grid;
          grid-template-columns: 42px minmax(0, 1fr) auto;
          align-items: center;
          gap: 0.9rem;
          padding: 1rem 1.05rem;
          border: 1px solid color-mix(in srgb, var(--ds-primary) 28%, var(--ds-border));
          border-radius: var(--ds-radius-lg);
          background:
            radial-gradient(circle at 96% 4%, rgba(100, 210, 255, 0.11), transparent 38%),
            color-mix(in srgb, var(--ds-primary-soft) 62%, var(--ds-surface));
          box-shadow: 0 12px 34px rgba(0, 0, 0, 0.16);
        }

        .ds-live-task::before {
          position: absolute;
          inset: 0;
          content: "";
          pointer-events: none;
          background: linear-gradient(
            105deg,
            transparent 22%,
            rgba(255, 255, 255, 0.055) 46%,
            transparent 70%
          );
          transform: translateX(-105%);
        }

        .ds-live-task.active::before { animation: ds-card-sheen 2.8s ease-in-out infinite; }

        .ds-live-orbit {
          position: relative;
          display: grid;
          place-items: center;
          width: 38px;
          height: 38px;
          border: 2px solid color-mix(in srgb, var(--ds-primary) 18%, transparent);
          border-radius: 50%;
        }

        .ds-live-orbit::before {
          position: absolute;
          inset: -2px;
          content: "";
          border: 2px solid transparent;
          border-top-color: var(--ds-primary);
          border-right-color: color-mix(in srgb, var(--ds-primary) 38%, transparent);
          border-radius: 50%;
        }

        .ds-live-task.active .ds-live-orbit::before { animation: ds-orbit 1.05s linear infinite; }

        .ds-live-core {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--ds-primary);
          box-shadow: 0 0 0 5px color-mix(in srgb, var(--ds-primary) 14%, transparent);
        }

        .ds-live-task.active .ds-live-core { animation: ds-core-pulse 1.45s ease-in-out infinite; }
        .ds-live-content { min-width: 0; }
        .ds-live-title { color: var(--ds-text); font-size: 0.82rem; font-weight: 700; }
        .ds-live-detail {
          overflow: hidden;
          margin-top: 0.22rem;
          color: var(--ds-text-soft);
          font-size: 0.72rem;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .ds-live-meta {
          margin-top: 0.38rem;
          color: var(--ds-text-muted);
          font-size: 0.63rem;
        }

        .ds-live-percent {
          min-width: 3.2rem;
          color: var(--ds-primary);
          font-size: 0.84rem;
          font-variant-numeric: tabular-nums;
          font-weight: 720;
          text-align: right;
        }

        .ds-live-track {
          grid-column: 2 / 4;
          position: relative;
          overflow: hidden;
          height: 7px;
          border-radius: 999px;
          background: color-mix(in srgb, var(--ds-surface-soft) 78%, transparent);
        }

        .ds-live-track > span {
          position: relative;
          display: block;
          height: 100%;
          min-width: 5px;
          overflow: hidden;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--ds-primary), #64d2ff);
          transition: width 420ms ease;
        }

        .ds-live-task.active .ds-live-track > span::after {
          position: absolute;
          inset: 0;
          content: "";
          background: linear-gradient(90deg, transparent, rgba(255,255,255,0.62), transparent);
          transform: translateX(-100%);
          animation: ds-progress-sheen 1.65s ease-in-out infinite;
        }

        .ds-live-track.indeterminate > span {
          width: 34% !important;
          animation: ds-indeterminate 1.55s ease-in-out infinite;
        }

        @keyframes ds-orbit { to { transform: rotate(360deg); } }
        @keyframes ds-core-pulse {
          0%, 100% { opacity: 0.72; transform: scale(0.82); }
          50% { opacity: 1; transform: scale(1); }
        }
        @keyframes ds-card-sheen {
          0%, 18% { transform: translateX(-105%); }
          72%, 100% { transform: translateX(105%); }
        }
        @keyframes ds-progress-sheen {
          0% { transform: translateX(-100%); }
          72%, 100% { transform: translateX(100%); }
        }
        @keyframes ds-indeterminate {
          0% { transform: translateX(-105%); }
          55% { transform: translateX(155%); }
          100% { transform: translateX(310%); }
        }

        @media (prefers-reduced-motion: reduce) {
          .ds-live-task.active::before,
          .ds-live-task.active .ds-live-orbit::before,
          .ds-live-task.active .ds-live-core,
          .ds-live-task.active .ds-live-track > span::after,
          .ds-live-track.indeterminate > span { animation: none !important; }
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
          backdrop-filter: blur(24px);
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
          min-height: 44px;
          border: 1px solid var(--ds-border-strong);
          border-radius: 11px;
          background: var(--ds-surface);
          color: var(--ds-text-soft);
          font-weight: 600;
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
          background: var(--ds-primary-strong);
          box-shadow: 0 8px 20px color-mix(in srgb, var(--ds-primary) 20%, transparent);
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

        [data-baseweb="tab-highlight"] {
          background-color: var(--ds-primary) !important;
        }

        [data-testid="stForm"] {
          border: 0;
          padding: 0;
        }

        [data-testid="stIFrame"] {
          min-height: 0 !important;
        }

        .ds-workspace-card {
          margin: 1.25rem 0.15rem 0;
          padding: 0.85rem 0.9rem;
          border: 1px solid var(--ds-border);
          border-radius: 13px;
          background: rgba(255, 255, 255, 0.035);
        }

        .ds-workspace-label {
          color: var(--ds-text-muted);
          font-size: 0.64rem;
          font-weight: 600;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }

        .ds-workspace-name {
          overflow: hidden;
          color: var(--ds-text-soft);
          font-size: 0.73rem;
          font-weight: 620;
          margin-top: 0.38rem;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .ds-local-badge {
          display: inline-flex;
          align-items: center;
          gap: 0.42rem;
          margin-top: 0.7rem;
          color: var(--ds-text-muted);
          font-size: 0.66rem;
        }

        .ds-hero {
          position: relative;
          overflow: hidden;
          padding: clamp(1.4rem, 3vw, 2.2rem);
          border: 1px solid rgba(255, 255, 255, 0.12);
          border-radius: 22px;
          background:
            radial-gradient(circle at 88% 18%, rgba(100, 210, 255, 0.20), transparent 25%),
            linear-gradient(135deg, rgba(10, 132, 255, 0.17), rgba(28, 28, 30, 0.76) 58%);
          box-shadow: var(--ds-shadow-md);
          backdrop-filter: saturate(145%) blur(28px);
        }

        .ds-hero-eyebrow {
          color: #64d2ff;
          font-size: 0.72rem;
          font-weight: 650;
          letter-spacing: 0.02em;
        }

        .ds-hero-title {
          max-width: 720px;
          color: var(--ds-text);
          font-size: clamp(1.45rem, 2.8vw, 2.25rem);
          font-weight: 680;
          line-height: 1.18;
          letter-spacing: -0.035em;
          margin-top: 0.55rem;
        }

        .ds-hero-copy {
          max-width: 680px;
          color: var(--ds-text-soft);
          font-size: 0.86rem;
          line-height: 1.65;
          margin-top: 0.72rem;
        }

        .ds-hero-meta {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
          margin-top: 1.15rem;
        }

        .ds-hero-meta span {
          padding: 0.3rem 0.62rem;
          border: 1px solid rgba(255, 255, 255, 0.10);
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.06);
          color: var(--ds-text-soft);
          font-size: 0.66rem;
          font-weight: 580;
        }

        .ds-runtime-strip {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          padding: 0.8rem 0.95rem;
          border: 1px solid var(--ds-border);
          border-radius: 13px;
          background: rgba(255, 255, 255, 0.035);
          color: var(--ds-text-muted);
          font-size: 0.7rem;
        }

        .ds-form-intro {
          padding: 1rem 1.05rem;
          border: 1px solid rgba(10, 132, 255, 0.22);
          border-radius: 14px;
          background: rgba(10, 132, 255, 0.08);
          color: var(--ds-text-soft);
          font-size: 0.78rem;
          line-height: 1.6;
          margin-bottom: 1rem;
        }

        .ds-mobile-nav {
          display: none;
        }

        .ds-build-mark {
          margin: 0.6rem 0.25rem;
          padding: 0.35rem 0.5rem;
          border-radius: 8px;
          background: rgba(127, 127, 255, 0.08);
          color: var(--ds-text-muted);
          font-size: 0.62rem;
          font-weight: 600;
          letter-spacing: 0.02em;
        }

        @media (max-width: 980px) {
          [data-testid="stMainBlockContainer"] { padding: 1rem 1rem 3rem; }
          .ds-stepper { grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 1rem; }
          .ds-step:nth-child(2)::after { display: none; }
          .ds-task-row { grid-template-columns: minmax(0, 1fr) 86px; }
          .ds-task-row > :nth-child(2) { display: none; }
        }

        @media (max-width: 640px) {
          [data-testid="stMainBlockContainer"] { padding: 4.25rem 0.8rem 3rem; }
          .ds-page-header { display: block; }
          .ds-page-description { max-width: none; }
          .ds-stepper { grid-template-columns: 1fr; }
          .ds-step::after { display: none !important; }
          .ds-hero { border-radius: 18px; }

          .ds-mobile-nav {
            position: fixed;
            z-index: 999999;
            right: 10px;
            bottom: 10px;
            left: 10px;
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 4px;
            padding: 6px 7px calc(6px + env(safe-area-inset-bottom));
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 18px;
            background: rgba(28, 28, 30, 0.82);
            box-shadow: 0 14px 44px rgba(0, 0, 0, 0.42);
            backdrop-filter: saturate(170%) blur(28px);
          }

          .ds-mobile-nav a {
            display: grid;
            place-items: center;
            min-height: 42px;
            border-radius: 12px;
            color: var(--ds-text-muted);
            font-size: 0.69rem;
            font-weight: 590;
            text-decoration: none;
          }

          .ds-mobile-nav a.active {
            background: var(--ds-primary-soft);
            color: var(--ds-primary);
          }

          [data-testid="stMain"] { padding-bottom: 5.5rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _inject_theme_bridge(theme)


def _render_sidebar(current_page: str) -> tuple[str, str]:
    if (
        "global_api_url" not in st.session_state
        or not str(st.session_state.get("global_api_url") or "").strip()
    ):
        st.session_state["global_api_url"] = str(
            st.session_state.get("api_url") or _default_api_url()
        ).rstrip("/")
    if (
        "global_project_path" not in st.session_state
        or not str(st.session_state.get("global_project_path") or "").strip()
    ):
        st.session_state["global_project_path"] = str(
            st.session_state.get("project_path") or _default_project_path()
        )

    api_value = str(st.session_state["global_api_url"]).rstrip("/")
    project_value = str(st.session_state["global_project_path"]).strip()
    st.session_state["api_url"] = api_value
    st.session_state["project_path"] = project_value
    if api_value and project_value:
        web_state.set_state(api_url=api_value, project_path=project_value)

    try:
        api_ready = requests.get(f"{api_value}/api/health", timeout=1.5).ok
    except requests.RequestException:
        api_ready = False
    project_name = Path(project_value).name if project_value else "未选择工作区"

    with st.sidebar:
        st.markdown(
            """
            <div class="ds-brand">
              <div class="ds-brand-mark"></div>
              <div>
                <div class="ds-brand-name">Distiller</div>
                <div class="ds-brand-subtitle">账号内容智能</div>
              </div>
            </div>
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

        st.markdown(
            f"""
            <div class="ds-workspace-card">
              <div class="ds-workspace-label">当前工作区</div>
              <div class="ds-workspace-name" title="{html.escape(project_value)}">
                {html.escape(project_name)}
              </div>
              <div class="ds-local-badge">
                <i class="ds-dot {"success" if api_ready else "warning"}"></i>
                {"本地服务已连接" if api_ready else "本地服务未连接"}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div id="ds-sidebar-diag" class="ds-build-mark">诊断载入中…</div>',
            unsafe_allow_html=True,
        )

    mobile_items = (
        ("dashboard", "/", "概览"),
        ("collect", "/quick_collect", "蒸馏"),
        ("reports", "/reports", "报告"),
        ("settings", "/settings", "设置"),
    )
    mobile_links = "".join(
        (
            f'<a class="{"active" if page_key == current_page else ""}" '
            f'href="{path}" target="_self">{label}</a>'
        )
        for page_key, path, label in mobile_items
    )
    st.markdown(
        f'<nav class="ds-mobile-nav" aria-label="移动端主导航">{mobile_links}</nav>',
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
    del page_key, theme
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
    return "dark"


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
    _inject_sidebar_diagnostics()
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


def task_progress_card(
    title: str,
    detail: str,
    *,
    progress: float,
    status: str,
    meta: str = "每 2 秒自动刷新 · 可安全离开本页",
) -> None:
    """Render a prominent live task card with determinate or pending progress."""

    st.markdown(
        task_progress_markup(
            title,
            detail,
            progress=progress,
            status=status,
            meta=meta,
        ),
        unsafe_allow_html=True,
    )
