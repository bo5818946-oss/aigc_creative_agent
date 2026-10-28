"""Shared visual system for the Streamlit workbench.

Design language: soft "aurora glass" on a light canvas.

* layered radial gradients instead of a flat grey background;
* frosted glass surfaces (blur + translucency + hairline highlight);
* one gradient accent used for primary actions and active states;
* 18-22px radii, layered diffuse shadows, generous vertical rhythm;
* a visible "Agent thinking" surface so model reasoning is inspectable.

Everything is expressed through the project's own ``app-*`` classes plus a few
stable Streamlit ``data-testid`` hooks, so a Streamlit upgrade degrades
gracefully instead of breaking the layout.
"""

from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

_STATUS_KIND = {
    "completed": "success",
    "success": "success",
    "validation_failed": "error",
    "failed": "error",
    "error": "error",
    "running": "info",
    "pending": "muted",
    "skipped": "muted",
    "not_implemented": "muted",
    "warning": "warning",
    "guiding": "info",
    "ready": "warning",
    "idle": "muted",
}

_STATUS_LABEL = {
    "completed": "已完成",
    "success": "成功",
    "validation_failed": "校验未通过",
    "failed": "失败",
    "error": "错误",
    "running": "运行中",
    "pending": "等待中",
    "skipped": "跳过",
    "not_implemented": "未实现",
    "warning": "警告",
    "guiding": "引导中",
    "ready": "待确认",
    "idle": "未开始",
}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --ink: #0B1020;
    --ink-2: #2A3352;
    --muted: #667089;
    --line: rgba(15, 23, 42, .08);
    --line-strong: rgba(15, 23, 42, .14);
    --violet: #6D5EF8;
    --indigo: #4F46E5;
    --cyan: #22D3EE;
    --pink: #F472B6;
    --grad: linear-gradient(135deg, #6D5EF8 0%, #8B5CF6 46%, #22D3EE 100%);
    --grad-soft: linear-gradient(135deg, rgba(109,94,248,.12), rgba(34,211,238,.10));
    --glass: rgba(255, 255, 255, .72);
    --glass-strong: rgba(255, 255, 255, .88);
    --shadow-sm: 0 2px 6px rgba(24, 30, 66, .05);
    --shadow-md: 0 12px 30px -18px rgba(24, 30, 66, .35);
    --shadow-lg: 0 30px 60px -34px rgba(24, 30, 66, .45);
    --radius: 20px;
    --radius-sm: 14px;
}

html, body, .stApp, [class*="css"] {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI",
        "Noto Sans SC", "Microsoft YaHei", sans-serif;
    color: var(--ink);
    -webkit-font-smoothing: antialiased;
}

/* ---------- canvas: aurora wash ---------- */
.stApp {
    background:
        radial-gradient(1100px 620px at 8% -8%, rgba(109, 94, 248, .20), transparent 60%),
        radial-gradient(900px 540px at 92% 2%, rgba(34, 211, 238, .16), transparent 62%),
        radial-gradient(760px 520px at 50% 110%, rgba(244, 114, 182, .12), transparent 60%),
        linear-gradient(180deg, #FBFBFE 0%, #F4F6FC 55%, #EEF1F9 100%);
    background-attachment: fixed;
}
.stApp > header { background: transparent; }
[data-testid="stAppViewContainer"] > .main { background: transparent; }
.block-container {
    padding-top: 2.4rem !important;
    padding-bottom: 5rem !important;
    max-width: 1220px;
}
[data-testid="stHeader"] { background: transparent; }

h1, h2, h3, h4 {
    letter-spacing: -.025em;
    color: var(--ink);
}
h1 { font-size: 2.15rem !important; font-weight: 800 !important; }
h2 { font-size: 1.32rem !important; font-weight: 700 !important; }
h3 { font-size: 1.04rem !important; font-weight: 700 !important; }

/* ---------- page header ---------- */
.app-page-head { margin: 0 0 1.5rem 0; }
.app-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: .45rem;
    font-size: .70rem;
    font-weight: 700;
    letter-spacing: .18em;
    text-transform: uppercase;
    color: var(--violet);
    margin-bottom: .55rem;
    padding: .3rem .7rem;
    border-radius: 999px;
    background: var(--grad-soft);
    border: 1px solid rgba(109, 94, 248, .18);
}
.app-page-title-row {
    display: flex;
    align-items: center;
    gap: .75rem;
    flex-wrap: wrap;
}
.app-page-title {
    font-size: 2.35rem;
    line-height: 1.12;
    font-weight: 800;
    letter-spacing: -.045em;
    margin: 0;
    background: linear-gradient(180deg, #101524 20%, #3B3F63 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}
.app-subtitle {
    color: var(--muted);
    font-size: .97rem;
    line-height: 1.7;
    max-width: 820px;
    margin: .6rem 0 0 0;
}
.app-section-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: .75rem;
    margin: .1rem 0 .85rem 0;
    flex-wrap: wrap;
}
.app-section-title { font-size: 1.02rem; font-weight: 700; color: var(--ink); letter-spacing: -.02em; }
.app-section-desc { color: var(--muted); font-size: .82rem; }

/* ---------- badges ---------- */
.app-badge {
    display: inline-flex;
    align-items: center;
    gap: .32rem;
    padding: .22rem .62rem;
    border-radius: 999px;
    border: 1px solid transparent;
    font-size: .73rem;
    font-weight: 650;
    line-height: 1.35;
    white-space: nowrap;
    backdrop-filter: blur(8px);
}
.app-badge::before {
    content: "";
    width: .38rem;
    height: .38rem;
    border-radius: 50%;
    background: currentColor;
    opacity: .85;
}
.app-badge-success { color: #0F7B4F; background: rgba(16, 185, 129, .11); border-color: rgba(16, 185, 129, .24); }
.app-badge-error { color: #B42318; background: rgba(239, 68, 68, .10); border-color: rgba(239, 68, 68, .24); }
.app-badge-warning { color: #9A5B12; background: rgba(245, 158, 11, .13); border-color: rgba(245, 158, 11, .26); }
.app-badge-info { color: #3B38B8; background: rgba(109, 94, 248, .12); border-color: rgba(109, 94, 248, .24); }
.app-badge-muted { color: #4B5563; background: rgba(148, 163, 184, .14); border-color: rgba(148, 163, 184, .26); }

/* ---------- glass surfaces ---------- */
.app-stat, .app-empty, .app-steps, .app-callout,
[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {
    background: var(--glass);
    backdrop-filter: blur(18px) saturate(150%);
    border: 1px solid rgba(255, 255, 255, .7) !important;
    box-shadow: var(--shadow-md), inset 0 1px 0 rgba(255, 255, 255, .85);
    border-radius: var(--radius) !important;
}

.app-stat {
    position: relative;
    padding: 18px 18px 16px 18px;
    min-height: 92px;
    overflow: hidden;
}
.app-stat::after {
    content: "";
    position: absolute;
    inset: 0 auto 0 0;
    width: 3px;
    background: var(--grad);
    border-radius: 3px;
}
.app-stat-label {
    font-size: .71rem;
    font-weight: 700;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--muted);
}
.app-stat-value {
    font-size: 1.55rem;
    font-weight: 750;
    color: var(--ink);
    margin-top: .3rem;
    line-height: 1.15;
    letter-spacing: -.03em;
}
.app-stat-hint { font-size: .76rem; color: var(--muted); margin-top: .28rem; }

.app-empty {
    padding: 2.8rem 1.6rem;
    text-align: center;
}
.app-empty-title { font-size: 1.04rem; font-weight: 700; color: var(--ink-2); }
.app-empty-desc { color: var(--muted); font-size: .87rem; margin-top: .4rem; }

.app-mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .82em;
}
.app-muted { color: var(--muted); }
.app-tiny { font-size: .76rem; }
.app-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--line-strong), transparent);
    margin: 1.3rem 0;
}

/* ---------- step strip ---------- */
.app-steps {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    overflow: hidden;
    margin: 0 0 1.1rem 0;
}
.app-step {
    display: flex;
    align-items: flex-start;
    gap: .7rem;
    padding: .95rem 1.05rem;
    border-right: 1px solid var(--line);
}
.app-step:last-child { border-right: 0; }
.app-step-num {
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 10px;
    background: rgba(15, 23, 42, .05);
    color: var(--muted);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: .74rem;
    font-weight: 750;
    flex: 0 0 auto;
}
.app-step-active .app-step-num {
    background: var(--grad);
    color: #FFFFFF;
    box-shadow: 0 6px 14px -6px rgba(109, 94, 248, .8);
}
.app-step-title { font-size: .87rem; font-weight: 700; color: var(--ink); line-height: 1.35; }
.app-step-desc { font-size: .74rem; color: var(--muted); margin-top: .14rem; line-height: 1.45; }

/* ---------- callouts ---------- */
.app-callout {
    display: flex;
    align-items: center;
    gap: .55rem;
    flex-wrap: wrap;
    padding: .8rem .95rem;
    margin: 0 0 .95rem 0;
    font-size: .85rem;
    color: var(--ink-2);
}
.app-callout code { font-size: .8em; }
.app-callout-success { border-color: rgba(16, 185, 129, .3) !important; background: rgba(236, 253, 245, .8); }
.app-callout-warning { border-color: rgba(245, 158, 11, .3) !important; background: rgba(255, 251, 235, .8); }

/* ---------- events ---------- */
.app-event {
    border-left: 2px solid var(--line-strong);
    padding: .4rem 0 .4rem .75rem;
    margin: .35rem 0;
}
.app-event-success { border-left-color: #10B981; }
.app-event-error { border-left-color: #EF4444; }
.app-event-info { border-left-color: var(--violet); }
.app-event-muted { border-left-color: #CBD5E1; }
.app-event-title { font-size: .82rem; font-weight: 650; color: var(--ink); }
.app-event-meta { font-size: .74rem; color: var(--muted); margin-top: .12rem; }

/* ---------- chat ---------- */
.app-chat-row {
    display: flex;
    align-items: flex-start;
    gap: .6rem;
    margin: .6rem 0;
    animation: app-rise .32s cubic-bezier(.22, .8, .3, 1) both;
}
.app-chat-row-user { justify-content: flex-end; }
.app-chat-avatar {
    width: 2rem;
    height: 2rem;
    border-radius: 12px;
    background: var(--grad);
    color: #FFFFFF;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: .62rem;
    font-weight: 800;
    letter-spacing: .04em;
    flex: 0 0 auto;
    box-shadow: 0 8px 18px -8px rgba(109, 94, 248, .9);
}
.app-chat-bubble {
    max-width: 86%;
    background: var(--glass-strong);
    backdrop-filter: blur(16px) saturate(150%);
    border: 1px solid rgba(255, 255, 255, .8);
    border-radius: 18px 18px 18px 6px;
    padding: .72rem .9rem;
    font-size: .9rem;
    line-height: 1.65;
    color: var(--ink-2);
    box-shadow: var(--shadow-md), inset 0 1px 0 rgba(255, 255, 255, .9);
    overflow-wrap: anywhere;
}
.app-chat-bubble-user {
    background: var(--grad);
    border: 1px solid rgba(255, 255, 255, .35);
    border-radius: 18px 18px 6px 18px;
    color: #FFFFFF;
    box-shadow: 0 16px 30px -18px rgba(79, 70, 229, .9);
}

/* ---------- agent reasoning ---------- */
.app-think {
    margin: .35rem 0 .1rem 2.6rem;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(109, 94, 248, .18);
    background: linear-gradient(135deg, rgba(109, 94, 248, .07), rgba(34, 211, 238, .05));
    backdrop-filter: blur(12px);
    overflow: hidden;
}
.app-think-head {
    display: flex;
    align-items: center;
    gap: .5rem;
    padding: .5rem .8rem;
    font-size: .72rem;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: #4C42C8;
    border-bottom: 1px dashed rgba(109, 94, 248, .22);
}
.app-think-dot {
    width: .48rem;
    height: .48rem;
    border-radius: 50%;
    background: var(--grad);
    box-shadow: 0 0 0 3px rgba(109, 94, 248, .16);
    animation: app-pulse 1.6s ease-in-out infinite;
}
.app-think-model {
    margin-left: auto;
    font-size: .66rem;
    font-weight: 600;
    letter-spacing: .02em;
    text-transform: none;
    color: var(--muted);
}
.app-think-body {
    padding: .72rem .85rem;
    font-size: .85rem;
    line-height: 1.68;
    color: var(--ink-2);
    white-space: pre-wrap;
}
.app-think-tag {
    display: inline-block;
    margin-top: .55rem;
    font-size: .7rem;
    font-weight: 650;
    color: #4C42C8;
    background: rgba(109, 94, 248, .12);
    border-radius: 999px;
    padding: .12rem .5rem;
}

/* ---------- recommendation ---------- */
.app-recommendation {
    position: relative;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(109, 94, 248, .18);
    background: linear-gradient(135deg, rgba(109, 94, 248, .08), rgba(34, 211, 238, .06));
    padding: .75rem .9rem;
    margin: .8rem 0 .95rem 0;
    font-size: .85rem;
    line-height: 1.6;
    color: var(--ink-2);
    box-shadow: var(--shadow-sm);
}
.app-recommendation-label {
    font-size: .71rem;
    font-weight: 750;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: #4C42C8;
    margin-bottom: .25rem;
}

/* ---------- option cards ---------- */
.app-option {
    border-radius: var(--radius-sm);
    border: 1px solid rgba(255, 255, 255, .75);
    background: var(--glass-strong);
    backdrop-filter: blur(14px);
    box-shadow: var(--shadow-sm);
    padding: .8rem .9rem .55rem .9rem;
    margin-bottom: .55rem;
    transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.app-option:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
    border-color: rgba(109, 94, 248, .3);
}
.app-option-recommended {
    border-color: rgba(109, 94, 248, .42);
    background: linear-gradient(160deg, rgba(109, 94, 248, .10), rgba(255, 255, 255, .9));
    box-shadow: 0 18px 34px -24px rgba(109, 94, 248, .8);
}
.app-option-title { font-size: .92rem; font-weight: 700; color: var(--ink); }
.app-option-meta { font-size: .76rem; color: var(--muted); margin-top: .2rem; line-height: 1.55; }

/* ---------- production parameters ---------- */
.app-technique {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .73rem;
    line-height: 1.55;
    color: #4C42C8;
    background: rgba(109, 94, 248, .08);
    border: 1px solid rgba(109, 94, 248, .16);
    border-radius: 9px;
    padding: .3rem .55rem;
    margin: .35rem 0 .4rem 0;
    overflow-wrap: anywhere;
}
.app-reference {
    font-size: .73rem;
    color: var(--muted);
    margin-top: .12rem;
    line-height: 1.5;
}

/* ---------- stage rail ---------- */
.app-stage-rail {
    border-left: 2px solid var(--line);
    margin: .4rem 0 .9rem .35rem;
    padding-left: .8rem;
}
.app-stage-row {
    display: flex;
    align-items: center;
    gap: .45rem;
    color: #A3ADC2;
    font-size: .78rem;
    line-height: 2;
}
.app-stage-dot {
    width: .46rem;
    height: .46rem;
    border-radius: 50%;
    background: #CBD5E1;
    margin-left: -1.02rem;
}
.app-stage-row.done { color: var(--muted); }
.app-stage-row.done .app-stage-dot { background: #94A3B8; }
.app-stage-row.active { color: var(--ink); font-weight: 650; }
.app-stage-row.active .app-stage-dot {
    background: var(--violet);
    box-shadow: 0 0 0 4px rgba(109, 94, 248, .16);
}

/* ---------- hero / landing ---------- */
.app-hero {
    position: relative;
    overflow: hidden;
    border-radius: 28px;
    padding: 3.2rem 2.6rem 2.8rem 2.6rem;
    margin: 0 0 1.6rem 0;
    background:
        radial-gradient(900px 420px at 12% -20%, rgba(109, 94, 248, .28), transparent 60%),
        radial-gradient(700px 380px at 88% 0%, rgba(34, 211, 238, .22), transparent 62%),
        linear-gradient(160deg, rgba(255, 255, 255, .9), rgba(246, 247, 253, .72));
    border: 1px solid rgba(255, 255, 255, .8);
    box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(255, 255, 255, .95);
}
.app-hero::before {
    content: "";
    position: absolute;
    width: 460px;
    height: 460px;
    right: -140px;
    top: -220px;
    background: conic-gradient(from 200deg, rgba(109, 94, 248, .35), rgba(34, 211, 238, .28), rgba(244, 114, 182, .28), rgba(109, 94, 248, .35));
    filter: blur(60px);
    opacity: .55;
    border-radius: 50%;
    pointer-events: none;
}
.app-hero-title {
    position: relative;
    font-size: 2.9rem;
    line-height: 1.08;
    font-weight: 800;
    letter-spacing: -.05em;
    margin: 0 0 .7rem 0;
    background: linear-gradient(120deg, #11162B 20%, #4F46E5 70%, #22A8C4 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}
.app-hero-desc {
    position: relative;
    color: var(--ink-2);
    font-size: 1rem;
    line-height: 1.75;
    max-width: 660px;
    margin: 0;
}
.app-hero-chips { position: relative; display: flex; gap: .45rem; flex-wrap: wrap; margin-top: 1.2rem; }
.app-chip {
    font-size: .76rem;
    font-weight: 600;
    color: var(--ink-2);
    padding: .34rem .7rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, .72);
    border: 1px solid rgba(255, 255, 255, .9);
    box-shadow: var(--shadow-sm);
}

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] {
    background:
        radial-gradient(600px 400px at 20% 0%, rgba(109, 94, 248, .38), transparent 62%),
        linear-gradient(180deg, #0A0E1F 0%, #11152D 60%, #0B0F22 100%);
    border-right: 1px solid rgba(255, 255, 255, .06);
}
[data-testid="stSidebar"] * { color: #E7EAF5; }
[data-testid="stSidebar"] .stRadio label { border-radius: 12px; }
[data-testid="stSidebar"] .stRadio [role="radiogroup"] { gap: .15rem; }
.app-sidebar-brand { padding: .5rem 0 .7rem 0; }
.app-brand-name {
    font-size: 1.12rem;
    font-weight: 800;
    letter-spacing: -.02em;
    background: linear-gradient(120deg, #FFFFFF, #B9AFFF 60%, #7DE7F7 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}
.app-brand-sub {
    font-size: .68rem;
    color: #8C96B8;
    letter-spacing: .16em;
    text-transform: uppercase;
    margin-top: .22rem;
}
.app-sidebar-project {
    border: 1px solid rgba(255, 255, 255, .1);
    border-radius: var(--radius-sm);
    padding: .7rem .75rem;
    background: rgba(255, 255, 255, .05);
    backdrop-filter: blur(10px);
    margin-top: .6rem;
}
.app-sidebar-project-name {
    font-size: .82rem;
    font-weight: 650;
    color: #FFFFFF;
    overflow-wrap: anywhere;
}
.app-sidebar-footer {
    color: #7C87A8;
    font-size: .7rem;
    margin-top: 1.6rem;
    line-height: 1.7;
}
.app-sidebar-mono { color: #8C96B8; }

/* ---------- streamlit controls ---------- */
.stButton > button, .stFormSubmitButton > button {
    border-radius: 12px !important;
    border: 1px solid rgba(15, 23, 42, .1) !important;
    background: rgba(255, 255, 255, .85) !important;
    color: var(--ink) !important;
    font-weight: 600 !important;
    padding: .5rem .9rem !important;
    box-shadow: var(--shadow-sm) !important;
    transition: transform .16s ease, box-shadow .16s ease !important;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-md) !important;
    border-color: rgba(109, 94, 248, .35) !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
    background: var(--grad) !important;
    border: 1px solid rgba(255, 255, 255, .28) !important;
    color: #FFFFFF !important;
    box-shadow: 0 14px 30px -16px rgba(79, 70, 229, .9) !important;
}
.stButton > button:disabled {
    opacity: .45 !important;
    box-shadow: none !important;
    transform: none !important;
}
[data-testid="stChatInput"] {
    border-radius: 18px !important;
    border: 1px solid rgba(255, 255, 255, .9) !important;
    background: rgba(255, 255, 255, .92) !important;
    backdrop-filter: blur(16px);
    box-shadow: var(--shadow-lg) !important;
}
[data-testid="stChatInput"] textarea { font-size: .92rem; }
[data-testid="stExpander"] {
    border-radius: var(--radius-sm) !important;
    border: 1px solid rgba(255, 255, 255, .8) !important;
    background: rgba(255, 255, 255, .6) !important;
    backdrop-filter: blur(12px);
    box-shadow: var(--shadow-sm) !important;
}
[data-testid="stExpander"] summary { font-weight: 650; }
[data-testid="stMetric"] {
    background: var(--glass);
    border: 1px solid rgba(255, 255, 255, .8);
    border-radius: var(--radius-sm);
    padding: .8rem .9rem;
    box-shadow: var(--shadow-sm);
}
.stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div,
.stTextArea textarea {
    border-radius: 12px !important;
    background: rgba(255, 255, 255, .9) !important;
    border-color: rgba(15, 23, 42, .1) !important;
}
.stProgress > div > div > div > div { background: var(--grad) !important; }
hr { border-color: var(--line); }

@keyframes app-rise {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes app-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: .55; transform: scale(.82); }
}

@media (max-width: 760px) {
    .app-steps { grid-template-columns: 1fr; }
    .app-step { border-right: 0; border-bottom: 1px solid var(--line); }
    .app-step:last-child { border-bottom: 0; }
    .app-page-title { font-size: 1.85rem; }
    .app-hero-title { font-size: 2.05rem; }
    .app-hero { padding: 2rem 1.4rem; }
    .app-chat-bubble { max-width: 92%; }
}
</style>
"""


def apply_theme() -> None:
    st.set_page_config(
        page_title="AIGC Studio",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def badge(text: object, kind: str = "muted") -> str:
    safe_kind = kind if kind in {
        "success",
        "error",
        "warning",
        "info",
        "muted",
    } else "muted"
    return (
        f'<span class="app-badge app-badge-{safe_kind}">'
        f"{escape(text)}</span>"
    )


def status_kind(status: object) -> str:
    return _STATUS_KIND.get(str(status), "muted")


def status_label(status: object) -> str:
    return _STATUS_LABEL.get(str(status), str(status))


def status_badge(status: object) -> str:
    return badge(status_label(status), status_kind(status))


def page_header(
    eyebrow: str,
    title: str,
    description: str,
    badge_html: str | None = None,
) -> None:
    badge_part = f" {badge_html}" if badge_html else ""
    st.markdown(
        f"""
        <div class="app-page-head">
          <div class="app-eyebrow">{escape(eyebrow)}</div>
          <div class="app-page-title-row">
            <h1 class="app-page-title">{escape(title)}</h1>{badge_part}
          </div>
          <p class="app-subtitle">{escape(description)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def hero(
    eyebrow: str,
    title: str,
    description: str,
    chips: list[str] | None = None,
) -> None:
    chip_html = "".join(
        f'<span class="app-chip">{escape(chip)}</span>' for chip in (chips or [])
    )
    st.markdown(
        f"""
        <div class="app-hero">
          <div class="app-eyebrow">{escape(eyebrow)}</div>
          <div class="app-hero-title">{escape(title)}</div>
          <p class="app-hero-desc">{escape(description)}</p>
          <div class="app-hero-chips">{chip_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(
    title: str,
    description: str | None = None,
    badge_html: str | None = None,
) -> None:
    desc = (
        f'<span class="app-section-desc">{escape(description)}</span>'
        if description
        else ""
    )
    badge_part = f" {badge_html}" if badge_html else ""
    st.markdown(
        f"""
        <div class="app-section-head">
          <div>
            <span class="app-section-title">{escape(title)}</span>
            {badge_part}
          </div>
          {desc}
        </div>
        """,
        unsafe_allow_html=True,
    )


def reasoning_block(
    reasoning: str,
    *,
    model: str = "",
    action_label: str = "",
    source: str = "llm",
) -> str:
    """Render the model's own justification, or an honest rules-only notice.

    ``source="rules"`` deliberately shows a different label: the deterministic
    policy has no reasoning to display and must not borrow the visual language
    of model thought.
    """

    if source != "llm":
        return ""
    model_html = (
        f'<span class="app-think-model">{escape(model)}</span>' if model else ""
    )
    tag = (
        f'<span class="app-think-tag">{escape(action_label)}</span>'
        if action_label
        else ""
    )
    body = escape(reasoning).replace("\n", "<br/>")
    return (
        '<div class="app-think">'
        '<div class="app-think-head">'
        '<span class="app-think-dot"></span>'
        "<span>Agent 思考过程</span>"
        f"{model_html}"
        "</div>"
        f'<div class="app-think-body">{body}{tag}</div>'
        "</div>"
    )


def empty_state(title: str, description: str) -> None:
    st.markdown(
        f"""
        <div class="app-empty">
          <div class="app-empty-title">{escape(title)}</div>
          <div class="app-empty-desc">{escape(description)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def stat_card(label: str, value: object, hint: str = "") -> None:
    hint_html = (
        f'<div class="app-stat-hint">{escape(hint)}</div>'
        if hint
        else ""
    )
    st.markdown(
        f"""
        <div class="app-stat">
          <div class="app-stat-label">{escape(label)}</div>
          <div class="app-stat-value">{escape(value)}</div>
          {hint_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def divider() -> None:
    st.markdown('<div class="app-divider"></div>', unsafe_allow_html=True)


def format_timestamp(value: object) -> str:
    if not value:
        return "—"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def format_duration(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:g} 秒"


def truncate(value: object, length: int = 120) -> str:
    text = str(value or "")
    return text if len(text) <= length else text[: length - 1] + "…"
