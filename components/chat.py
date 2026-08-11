"""
Chat Component (V3.2.3)
=======================
右下角悬浮 AI 助手：交互 UI（悬浮按钮、抽屉、输入框）由官方组件 iframe 承载
（HTML/CSS/JS 完全可控、定位可靠），消息区由 Python 渲染为固定浮层，
两者用组件返回值（Streamlit.setComponentValue）通信。

- 消息历史存 session_state，支持多轮追问
- 消息区独立滚动容器（column-reverse：新增内容自动锚定底部）
- 流式输出（打字机效果）
"""

import base64
import html as _html
import os
import re
import time

import streamlit as st
import streamlit.components.v1 as components

from i18n import t
from services.app_state import C
from data import chat_store
from data.storage import get_llm_profiles, get_active_llm_profile_id, load_config
from data.preferences import (record_stock, record_question, top_stocks,
                              top_topics, get_deep_review)
from agent.llm_client import stream_chat
from agent.prompts import build_messages
from agent.executor import run_agent, run_review, MAX_ROUNDS
from agent.tools import _extract_financials, tool_plot_chart
from utils import safe_float

MAX_HISTORY = 30  # 保留最近 N 条消息，控制上下文长度
_DEEP_ROUNDS = 4  # 深度分析允许的 LLM 往返轮数（普通对话 3 轮）
_PAINT_GAP = 0.4  # 流式重绘节流（秒）：大 HTML 全量重绘间隔，避免 iframe 渲染空白/闪烁

QUICK_KEYS = ("rsi", "pe", "macd", "indices")

# 深度分析意图识别（命中后走完整工具链 + 研报输出 + 下载入口）
_DEEP_RE = re.compile(
    r"(深度分析|深度研究|研报|研究报告|完整分析|全面分析"
    r"|deep\s*analysis|deep\s*dive|research\s*report"
    r"|in[- ]depth\s*analysis|comprehensive\s*analysis)",
    re.I)

# 画图意图识别（V3.3.2）：命中后注入 plot_chart 指令，避免模型只回文字不调工具
_CHART_RE = re.compile(
    r"(画图|画个图|画一下|画一张|画张|画幅|图表|K线|蜡烛图|折线图|走势图|趋势图|价格图|对比图"
    r"|draw\s+a|draw\s+the|plot\s+a|plot\s+the|chart|candlestick|k[- ]?line|price\s+trend|graph)",
    re.I)

# 自定义组件：AI 助手交互 UI（悬浮按钮 + 抽屉），index.html 承载
AI_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_frontend")
ai_panel = components.declare_component("ai_panel", path=AI_FRONTEND_DIR)

# 抽屉/浮层几何参数（与 components/ai_frontend/index.html 的 G 保持一致）
DRAWER_RIGHT, DRAWER_WIDTH, DRAWER_BOTTOM = 24, 460, 56
DRAWER_H_MAX = 640  # 抽屉打开时的最大高度
MSG_PAD = 16            # 抽屉内边距
TOP_BAR_H, INPUT_BAR_H = 62, 62  # 顶栏 / 输入条占高
FAB_SIZE = 56
FAB_EDGE = 8          # AI 球距视口边缘的最小间距
MINI_H = 48           # 最小化后抽屉的高度（只保留顶栏）


# ─── 轻量 markdown → HTML（聊天消息用，支持常用语法）──────

def _esc(s: str) -> str:
    return _html.escape(s, quote=False)


def _strip_bullet(l: str) -> str:
    return re.sub(r"^\s*[-*]\s+", "", l)


def _strip_num(l: str) -> str:
    return re.sub(r"^\s*\d+[.)]\s+", "", l)


def _safe_href(m: re.Match) -> str:
    """链接只允许 http/https/mailto，其余协议不生成可点击链接"""
    url = m.group(2)
    if url.lower().startswith(("http://", "https://", "mailto:")):
        return (f'<a href="{url}" target="_blank" rel="noopener noreferrer">'
                f'{m.group(1)}</a>')
    return m.group(1)


def _inline(s: str) -> str:
    """行内语法：行内代码 / 加粗 / 斜体 / 链接（先转义再套标签）"""
    s = _esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _safe_href, s)
    # V3.4.4：数据来源逐条标注 → 灰色小标签
    s = re.sub(r"（来源：([^）]+)）", r'<span class="src-tag">来源：\1</span>', s)
    s = re.sub(r"\(Source: ([^)]+)\)", r'<span class="src-tag">Source: \1</span>', s)
    return s


def _md_to_html(text: str) -> str:
    """把 AI/用户消息的 markdown 转成 HTML 气泡内容（代码块/标题/列表/引用/段落）"""
    text = (text or "").replace("\r\n", "\n")
    parts = re.split(r"(```[\w+-]*\n.*?```)", text, flags=re.S)
    out = []
    for part in parts:
        if part.startswith("```"):
            inner = part.strip()[3:]
            if inner.endswith("```"):
                inner = inner[:-3]
            lines = inner.strip("\n").split("\n")
            if lines and re.match(r"^[a-zA-Z0-9_+-]{1,20}$", lines[0].strip()):
                lines = lines[1:]
            out.append(f"<pre><code>{_esc(chr(10).join(lines))}</code></pre>")
            continue
        for block in part.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            lines = block.split("\n")
            # 表格：| a | b |（第二行为分隔行 |---| 时跳过）
            if len(lines) >= 2 and all(re.match(r"^\s*\|.*\|\s*$", l)
                                       for l in lines if l.strip()):
                raw_rows = [l.strip().strip("|").split("|") for l in lines if l.strip()]
                rows = [r for r in raw_rows
                        if not all(re.match(r"^\s*:?-+:?\s*$", c.strip()) for c in r)]
                if rows:
                    head = rows[0]
                    # 内联样式保证横排：单元格不换行（nowrap），表格按内容撑开，
                    # 超宽时整体横向滚动，杜绝窄列里中文逐字竖排
                    td_style = ("padding:6px 10px;border-bottom:1px solid rgba(255,255,255,.08);"
                                "text-align:left;white-space:nowrap;word-break:normal")
                    th_style = (td_style + ";background:rgba(255,255,255,.06);"
                                "font-weight:600;color:#f5f5f7")
                    trows = "".join(
                        "<tr>" + "".join(
                            f"<td style=\"{td_style}\">{_inline(c.strip())}</td>"
                            for c in r)
                        + "</tr>" for r in rows[1:])
                    thead = "".join(
                        f"<th style=\"{th_style}\">{_inline(c.strip())}</th>"
                        for c in head)
                    out.append(
                        '<div style="overflow-x:auto;max-width:100%;margin:6px 0 8px">'
                        '<table style="border-collapse:collapse;font-size:.75rem;'
                        'line-height:1.5;white-space:nowrap;width:max-content">'
                        f"<thead><tr>{thead}</tr></thead><tbody>{trows}</tbody></table>"
                        "</div>")
                    continue
            if all(re.match(r"^\s*[-*]\s+", l) or not l.strip() for l in lines):
                items = "".join(
                    f"<li>{_inline(_strip_bullet(l))}</li>"
                    for l in lines if l.strip())
                out.append(f"<ul>{items}</ul>")
                continue
            if all(re.match(r"^\s*\d+[.)]\s+", l) or not l.strip() for l in lines):
                items = "".join(
                    f"<li>{_inline(_strip_num(l))}</li>"
                    for l in lines if l.strip())
                out.append(f"<ol>{items}</ol>")
                continue
            m = re.match(r"^(#{1,4})\s+(.+)$", lines[0].strip())
            if m and len(lines) == 1:
                lvl = min(len(m.group(1)) + 1, 4)
                out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
                continue
            if lines[0].strip().startswith(">"):
                q = " ".join(l.lstrip("> ").strip() for l in lines if l.strip())
                out.append(f"<blockquote>{_inline(q)}</blockquote>")
                continue
            para = "<br>".join(_inline(l) for l in lines if l.strip())
            out.append(f"<p>{para}</p>")
    return "".join(out)


# ─── 消息渲染 ───────────────────────────────────────────

def _bubble(role: str, content_html: str) -> str:
    return f'<div class="chat-bubble chat-bubble-{role}">{content_html}</div>'


def _messages_html(messages: list, lang: str, hint=None,
                   report_download: str = "", pending_charts=None) -> str:
    """渲染整个消息区（column-reverse：DOM 最新在前 = 视觉底部最新）。

    hint:            工具调用轨迹（str 或 str 列表，逐行显示“正在查询…”）
    report_download: 深度分析研报下载入口的 HTML（由 _report_download_html 生成）
    pending_charts:  工具刚生成的图表 HTML（流式阶段先显示，不等回答文本完成）
    对话内图表：最终存放在 assistant 消息的 "charts" 字段里（V3.3.2），
    随聊天记录一起持久化，刷新页面后仍然显示。
    """
    disclaimer = f'<div class="chat-disclaimer">{t("chat_ai_disclaimer", lang)}</div>'
    if not messages:
        p = _active_profile(get_llm_profiles())
        cfg_hint = ""
        if not (p.get("api_key") and p.get("model")):
            cfg_hint = f'<p class="chat-welcome-hint">{t("chat_configure_hint", lang)}</p>'
        welcome = (
            f'<div class="chat-welcome">'
            f'<h4>{t("chat_welcome_title", lang)}</h4>'
            f'<p>{t("chat_welcome_hint", lang)}</p>'
            f'<p class="chat-welcome-model">{_active_model_text(lang)}</p>'
            f'{cfg_hint}'
            f'</div>'
        )
        return f'<div id="chat-msgs">{welcome}{disclaimer}</div>'
    # 布局（column-reverse：DOM 靠前 = 视觉靠下，最新消息贴近视口底部）：
    # disclaimer → 工具轨迹 → 消息气泡；下载入口跟随最新一条 AI 回答，
    # 保证生成过程与下载按钮都在用户当前视口内，无需往上翻。
    extra = ""
    if hint:
        steps = (hint if isinstance(hint, (list, tuple)) else [hint])
        rows = "".join(f'<div class="chat-tool-step">{_esc(s)}</div>'
                       for s in steps if s)
        extra = f'<div class="chat-tool-hint">{rows}</div>'
    if pending_charts:
        # 流式阶段：图表生成后立即展示，不等最终回答（最终渲染会收进消息气泡）
        rows = "".join(f'<div class="chat-chart">{c}</div>' for c in pending_charts)
        extra += f'<div class="chat-pending-charts">{rows}</div>'
    bubbles = []
    for i, m in enumerate(reversed(messages)):
        content_html = _md_to_html(m.get("content", ""))
        # 对话内出图（V3.3.2）：图表内嵌在消息里，随历史刷新后仍显示
        if m.get("charts") and m.get("role") == "assistant":
            content_html += "".join(
                f'<div class="chat-chart">{c}</div>' for c in m["charts"])
        if report_download and i == 0 and m.get("role") == "assistant":
            # 下载入口嵌入最新一条 AI 回答气泡底部
            content_html += report_download
        bubbles.append(_bubble(m.get("role", "assistant"), content_html))
    return f'<div id="chat-msgs">{disclaimer}{extra}{"".join(bubbles)}</div>'


# ─── 深度分析（V3.2.3）─────────────────────────────────

def _is_deep_request(text: str) -> bool:
    """判断用户消息是否为「深度分析/研报」请求（命中后走完整工具链）"""
    return bool(text and _DEEP_RE.search(text))


def _is_chart_request(text: str) -> bool:
    """判断用户消息是否为「画图」请求（命中后注入 plot_chart 指令）"""
    return bool(text and _CHART_RE.search(text))


# 兜底出图的判定更严格：必须有明确的画图动作词（避免「解释什么是K线」误触发）
_FALLBACK_CHART_RE = re.compile(
    r"(画[图张一下]|图表|走势图|趋势图|价格图|对比图|蜡烛图"
    r"|plot|draw|chart|graph|candlestick|k[- ]?line|k线图)", re.I)
_TICKER_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.\-]{1,5}")


def _extract_tickers(text: str) -> list:
    """从消息里提取股票代码（去重、校验；只认 2 位以上的字母代码）"""
    out = []
    for tok in _TICKER_TOKEN_RE.findall(str(text or "")):
        tok = tok.upper().rstrip(".")
        if tok not in out and len(tok) >= 2:
            try:
                from agent.tools import clean_ticker
                clean_ticker(tok)
                out.append(tok)
            except ValueError:
                continue
    return out


def _server_chart_fallback(text: str, lang: str) -> list:
    """服务端兜底出图（V3.3.2）：模型漏调 plot_chart 时，系统直接生成图表。

    只对明确画图请求生效：消息里有股票代码优先用它，否则用当前页面股票；
    消息提到 K 线/蜡烛 → candlestick，否则 line；多只 → 对比折线图。
    失败静默返回空（不影响对话），避免打断回答。
    """
    if not _FALLBACK_CHART_RE.search(text or ""):
        return []
    tickers = _extract_tickers(text)
    if not tickers:
        page = _page_state()
        if page.get("mode") == "compare":
            tickers = [x for x in (page.get("tickers") or []) if x][:5]
        elif page.get("ticker"):
            tickers = [str(page["ticker"]).upper()]
    if not tickers:
        return []
    if len(tickers) > 5:
        tickers = tickers[:5]
    chart_type = ("candlestick" if re.search(r"K线|蜡烛|candlestick|k[- ]?line", text, re.I)
                  else "line")
    try:
        out = tool_plot_chart(tickers, days=365, interval="1day",
                              chart_type=chart_type)
        html = out.get("_chart_html") or ""
        return [html] if html else []
    except Exception:
        return []


def _report_download_html(lang: str, text: str) -> str:
    """研报下载入口：HTML 精美报告（主推）+ Markdown 原文（可编辑），
    均为 data URI 下载链接，嵌入 AI 回答气泡底部"""
    if not text or not text.strip():
        return ""
    html_text = _report_html(text, lang)
    html_data = base64.b64encode(html_text.encode("utf-8")).decode("ascii")
    md_data = base64.b64encode(text.encode("utf-8")).decode("ascii")
    html_label = t("deep_report_download_html", lang)
    md_label = t("deep_report_download_md", lang)
    return (f'<div class="chat-report-downloads">'
            f'<a class="chat-report-download" '
            f'href="data:text/html;base64,{html_data}" '
            f'download="research_report.html">{_esc(html_label)}</a>'
            f'<a class="chat-report-download" '
            f'href="data:text/markdown;base64,{md_data}" '
            f'download="research_report.md">{_esc(md_label)}</a>'
            f'</div>')


_REPORT_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#1c1c1e;color:#d1d1d6;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text",
  "Helvetica Neue",Arial,sans-serif;line-height:1.75;padding:48px 24px}
.report{max-width:820px;margin:0 auto}
header{padding-bottom:24px;margin-bottom:36px;border-bottom:1px solid #38383a}
h1{font-size:28px;font-weight:700;color:#f5f5f7;margin:0 0 10px;
  letter-spacing:-.02em}
.meta{color:#98989d;font-size:13px}
main h2{font-size:20px;color:#f5f5f7;margin:36px 0 14px;padding-left:12px;
  border-left:3px solid #0a84ff}
main h3{font-size:16px;color:#f5f5f7;margin:24px 0 8px}
main h4{font-size:14px;color:#f5f5f7;margin:20px 0 6px}
main p{margin:10px 0}
strong{color:#f5f5f7}
code{background:#2c2c2e;border:1px solid #38383a;border-radius:6px;
  padding:1px 6px;font-size:13px;color:#409cff}
pre{background:#2c2c2e;border:1px solid #38383a;border-radius:12px;
  padding:14px 16px;overflow-x:auto}
pre code{background:none;border:none;padding:0;color:#f5f5f7}
table{border-collapse:collapse;width:100%;margin:16px 0;font-size:14px}
th,td{border:1px solid #38383a;padding:8px 12px;text-align:left;vertical-align:top}
th{background:#2c2c2e;color:#f5f5f7;font-weight:600}
tr:nth-child(even) td{background:rgba(255,255,255,.02)}
blockquote{border-left:3px solid #0a84ff;margin:14px 0;padding:6px 16px;
  color:#98989d;background:rgba(10,132,255,.05);border-radius:0 12px 12px 0}
ul,ol{padding-left:22px;margin:12px 0}
li{margin:5px 0}
footer{margin-top:44px;padding-top:18px;border-top:1px solid #38383a;
  color:#6e6e73;font-size:12px}
"""


def _merge_review(text: str, review: str, lang: str) -> str:
    """V3.4.4：把风控审阅内容合并进研报。

    模型输出本身会带「风险复核意见」标题 → 已含标题时不重复添加。
    """
    if not review or not review.strip():
        return text
    head = t("deep_review_heading", lang).strip()
    has_title = (review.lstrip().startswith(head)
                 or bool(re.match(r"^##\s+\S+", review.lstrip())))
    if not has_title:
        review = t("deep_review_heading", lang) + "\n\n" + review
    return text + "\n\n" + review


def _report_html(text: str, lang: str) -> str:
    """把研报 Markdown 套上 Apple 深色风格模板，生成可独立打开/打印的 HTML"""
    title = t("deep_report_title", lang)
    ts = time.strftime("%Y-%m-%d %H:%M")
    body = _md_to_html(text)
    footer = t("deep_report_footer", lang, ts=ts)
    return (f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_esc(title)}</title><style>{_REPORT_CSS}</style></head>'
            f'<body><div class="report"><header>'
            f'<h1>{_esc(title)}</h1>'
            f'<div class="meta">{_esc(ts)}</div>'
            f'</header><main>{body}</main>'
            f'<footer>{_esc(footer)}</footer></div></body></html>')


# ─── 模型状态 ───────────────────────────────────────────

def _active_profile(profiles: list) -> dict:
    """返回当前使用的模型配置（无配置时返回空 dict）"""
    if not profiles:
        return {}
    active_id = get_active_llm_profile_id()
    for p in profiles:
        if p.get("id") == active_id:
            return p
    return profiles[0]


def _active_model_text(lang: str) -> str:
    """抽屉顶栏显示的当前模型名（未配置时给提示文案）"""
    p = _active_profile(get_llm_profiles())
    if p.get("api_key") and p.get("model"):
        return f"{p.get('name', '')} · {p.get('model', '')}"
    return t("chat_no_model", lang)


def _append(message: dict, session_id: str = None, target: list = None) -> None:
    """追加一条消息（内存 + 磁盘持久化）。

    - target: 消息列表（默认当前会话列表）；流式回复时传入开始捕获的列表，
      避免中途切换话题把回复追加进错误的话题。
    - session_id: 持久化目标会话；流式回复时传入开始捕获的会话 id。
    """
    if target is None:
        target = st.session_state.chat_messages
    if st.session_state.chat_messages is target:
        target.append(message)
        if len(target) > MAX_HISTORY:
            st.session_state.chat_messages = target[-MAX_HISTORY:]
    sid = session_id or st.session_state.get("chat_session_id")
    if sid:
        chat_store.append_message(sid, message)


# ─── 会话持久化（V3.2.2a）───────────────────────────────

def _ensure_chat_session() -> None:
    """首次渲染时恢复上次的会话（含历史消息），没有则新建一个"""
    if st.session_state.get("chat_session_loaded"):
        return
    _activate_session(chat_store.get_active_session_id())
    st.session_state.chat_session_loaded = True


def _activate_session(sid) -> None:
    """切换到指定会话（不存在则新建），并加载其历史消息"""
    sess = chat_store.get_session(sid)
    if not sess:
        sess = chat_store.create_session()
    chat_store.set_active_session_id(sess["id"])
    st.session_state.chat_session_id = sess["id"]
    # 只加载最近 MAX_HISTORY 条，控制上下文长度（磁盘里保留更多）
    st.session_state.chat_messages = list((sess.get("messages") or [])[-MAX_HISTORY:])


def _rel_time(ts, lang: str) -> str:
    """把时间戳格式化为简短相对时间（刚刚 / N 分钟前 / N 小时前 / N 天前 / N 周前）"""
    if not ts:
        return t("time_just_now", lang)
    diff = time.time() - ts
    if diff < 60:
        return t("time_just_now", lang)
    if diff < 3600:
        return t("time_min_ago", lang, n=int(diff / 60))
    if diff < 86400:
        return t("time_hour_ago", lang, n=int(diff / 3600))
    if diff < 604800:
        return t("time_day_ago", lang, n=int(diff / 86400))
    return t("time_week_ago", lang, n=int(diff / 604800))


def _threads_payload(lang: str) -> list:
    """所有会话的列表（标题 + 主题股票 + 相对时间 + 消息数），供抽屉话题面板展示"""
    out = []
    for s in chat_store.list_sessions():
        ctx = s.get("context") or {}
        topic = ""
        if ctx.get("ticker"):
            topic = str(ctx["ticker"]).upper()
        elif ctx.get("tickers"):
            topic = ", ".join(str(x).upper() for x in ctx["tickers"])
        meta = (f"{_rel_time(s.get('updated_at'), lang)} · "
                f"{t('thread_msg_count', lang, n=s.get('message_count') or 0)}")
        if topic:
            meta = f"{topic} · {meta}"
        out.append({
            "id": s.get("id"),
            "title": s.get("title") or chat_store.DEFAULT_TITLE,
            "meta": meta,
        })
    return out


def _page_state() -> dict:
    """当前页面状态的结构化快照（供话题主题绑定与数据注入判断）"""
    state = {"mode": st.session_state.get("mode", "single"), "ts": time.time()}
    if state["mode"] == "compare":
        state["tickers"] = [x for x in (st.session_state.get("compare_tickers") or []) if x]
    else:
        cached = st.session_state.get("cached") or {}
        state["ticker"] = cached.get("ticker") or ""
        state["period_label"] = cached.get("period_label") or ""
        state["interval_label"] = cached.get("interval_label") or ""
    return state


def _fmt_num(v):
    """数字缩写：1234 → 1.2K，4.5e7 → 45M，3.5e12 → 3.50T"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if abs(v) >= 1e12:
        return f"{v / 1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"{v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:.2f}"


def _fmt_dec(v, n: int = 2) -> str:
    try:
        return f"{float(v):.{n}f}"
    except (TypeError, ValueError):
        return None


def _ind_latest(rows, key):
    """指标序列最新值（序列为升序 {datetime, value} 列表）"""
    if not rows:
        return None
    return safe_float(rows[-1].get(key))


def _topic_label(topic: dict, lang: str) -> str:
    """话题主题的人类可读标签（单股 / 多股对比）"""
    if topic.get("mode") == "compare":
        tks = topic.get("tickers") or []
        return t("ctx_mode_compare", lang, tickers=", ".join(tks) if tks else "-")
    tk = topic.get("ticker") or ""
    period = topic.get("period_label") or ""
    return t("ctx_mode_single", lang, ticker=tk, period=period)


def _quote_line(tk: str, q: dict) -> str:
    """对比数据里单只股票的报价行"""
    close = safe_float(q.get("close"))
    if close is None:
        return None
    name = q.get("name") or tk
    chg_pct = safe_float(q.get("percent_change"))
    line = f"- {name} ({tk}): {q.get('currency') or 'USD'} {close:,.2f}"
    if chg_pct is not None:
        line += f" ({chg_pct:+.2f}%)"
    return line


def _single_data_text(tk: str, cached: dict, lang: str) -> str:
    """单股页面数据摘要：报价 / 估值 / 指标（与页面显示一致，控制 token）"""
    quote = cached.get("quote") or {}
    name = quote.get("name") or tk
    currency = quote.get("currency") or "USD"
    lines = [t("ctx_data_single", lang, ticker=tk)]

    parts = [name]
    close = safe_float(quote.get("close"))
    if close is not None:
        chg_pct = safe_float(quote.get("percent_change"))
        chg = safe_float(quote.get("change"))
        s = f"{currency} {close:,.2f}"
        if chg_pct is not None:
            s += f" ({chg_pct:+.2f}%)"
        elif chg is not None:
            s += f" ({chg:+.2f})"
        parts.append(f"Price {s}")
    o, h, lo = (safe_float(quote.get("open")), safe_float(quote.get("high")),
                safe_float(quote.get("low")))
    if any(v is not None for v in (o, h, lo)):
        parts.append(f"Open/High/Low {_fmt_dec(o)}/{_fmt_dec(h)}/{_fmt_dec(lo)}")
    vol = safe_float(quote.get("volume"))
    if vol:
        parts.append(f"Volume {_fmt_num(vol)}")
    lines.append(" · ".join(parts))

    fin = _extract_financials(tk, cached.get("stats") or {})
    fin_parts = []
    if fin.get("market_cap") is not None:
        fin_parts.append(f"Market cap {_fmt_num(fin['market_cap'])}")
    if fin.get("pe_ratio") is not None:
        fin_parts.append(f"P/E {_fmt_dec(fin['pe_ratio'])}")
    if fin.get("eps") is not None:
        fin_parts.append(f"EPS {_fmt_dec(fin['eps'])}")
    if fin.get("revenue") is not None:
        fin_parts.append(f"Revenue {_fmt_num(fin['revenue'])}")
    if fin_parts:
        lines.append("Valuation: " + " · ".join(fin_parts))

    ind = cached.get("indicators") or {}
    ind_parts = []
    rsi = _ind_latest(ind.get("rsi14"), "rsi14")
    if rsi is not None:
        ind_parts.append(f"RSI(14) {rsi:.1f}")
    macd = ind.get("macd") or {}
    dif = _ind_latest(macd.get("dif"), "dif")
    dea = _ind_latest(macd.get("dea"), "dea")
    hist = _ind_latest(macd.get("hist"), "hist")
    if dif is not None:
        ind_parts.append(f"MACD {_fmt_dec(dif, 3)}/{_fmt_dec(dea, 3)}/{_fmt_dec(hist, 3)} (DIF/DEA/hist)")
    ma20 = _ind_latest(ind.get("ma20"), "ma20")
    ma60 = _ind_latest(ind.get("ma60"), "ma60")
    if ma20 is not None:
        ind_parts.append(f"MA20 {_fmt_dec(ma20)}")
    if ma60 is not None:
        ind_parts.append(f"MA60 {_fmt_dec(ma60)}")
    boll = ind.get("boll") or {}
    bu = _ind_latest(boll.get("upper"), "upper")
    bm = _ind_latest(boll.get("middle"), "middle")
    bl = _ind_latest(boll.get("lower"), "lower")
    if bm is not None:
        ind_parts.append(f"Bollinger {_fmt_dec(bl)}/{_fmt_dec(bm)}/{_fmt_dec(bu)} (lower/mid/upper)")
    if ind_parts:
        lines.append("Indicators: " + " · ".join(ind_parts))

    return "\n".join(lines)


def _page_data_text(lang: str, page: dict, topic: dict) -> str:
    """页面实时数据摘要；话题主题与页面不一致时不注入（避免给过期数据）"""
    if page.get("mode") == "compare":
        cached = st.session_state.get("compare_cached") or {}
        quotes = cached.get("quotes") or {}
        if not quotes:
            return ""
        topic_tks = set(topic.get("tickers") or []) if topic else set()
        if topic and topic_tks and topic_tks != set(page.get("tickers") or []):
            return ""
        qmap = {str(k).upper(): v for k, v in quotes.items()}
        parts = [t("ctx_data_compare", lang)]
        for tk in page.get("tickers") or []:
            line = _quote_line(tk, qmap.get(str(tk).upper()) or {})
            if line:
                parts.append(line)
        return "\n".join(parts) if len(parts) > 1 else ""

    cached = st.session_state.get("cached") or {}
    quote = cached.get("quote") or {}
    if not quote:
        return ""
    if topic and topic.get("ticker") and str(topic["ticker"]).upper() != str(page.get("ticker") or "").upper():
        return ""
    tk = page.get("ticker") or quote.get("symbol") or ""
    return _single_data_text(tk, cached, lang)


def _context_text(lang: str) -> str:
    """组装注入模型的上下文：话题主题 + 页面状态 + 页面实时数据 + 使用规则"""
    page = _page_state()
    topic = chat_store.get_session_context(st.session_state.get("chat_session_id"))
    lines = [t("ctx_page_title", lang)]

    if topic and (topic.get("ticker") or topic.get("tickers")):
        lines.append(t("ctx_thread_topic", lang, topic=_topic_label(topic, lang)))

    mode = page.get("mode", "single")
    if mode == "compare":
        tks = page.get("tickers") or []
        lines.append(t("ctx_mode_compare", lang, tickers=", ".join(tks) if tks else "-"))
    elif page.get("ticker"):
        lines.append(t("ctx_mode_single", lang, ticker=page["ticker"],
                       period=page.get("period_label") or ""))
    else:
        lines.append(t("ctx_mode_idle", lang))

    data = _page_data_text(lang, page, topic)
    if data:
        lines.append(data)
    lines.append(t("ctx_data_rules", lang))
    # 自选股（手动维护，跨会话注入）
    wl = load_config().get("watchlist", [])
    if wl:
        lines.append(t("ctx_watchlist", lang,
                       tickers="、".join(str(x).upper() for x in wl)))
    # V3.3.3 个性化档案（行为隐式学习）：常看股票 + 关注维度
    stocks = top_stocks(3)
    topics = [t(f"topic_{tp}", lang) for tp in top_topics(2)]
    if stocks or topics:
        lines.append(t("ctx_profile", lang,
                       stocks="、".join(stocks) if stocks else "-",
                       topics="、".join(topics) if topics else "-"))
    return "\n".join(lines)


# ─── 组件交互：动作处理 ─────────────────────────────────

def handle_ai_action(val, lang: str) -> None:
    """处理组件 iframe 传来的动作（toggle / close / clear / send）"""
    if not isinstance(val, dict):
        return
    action = val.get("action")
    if action == "toggle":
        st.session_state.show_chat = not st.session_state.show_chat
        if not st.session_state.show_chat:
            st.session_state.show_mini = False
    elif action == "close":
        st.session_state.show_chat = False
        st.session_state.show_mini = False
    elif action == "clear":
        st.session_state.chat_messages = []
        chat_store.clear_session(st.session_state.get("chat_session_id"))
    elif action == "toggle_threads":
        st.session_state.show_threads = not st.session_state.get("show_threads", False)
    elif action == "mini":
        # 最小化/展开：收起为一条窄栏（背景页面完全不受影响）
        st.session_state.show_mini = not st.session_state.get("show_mini", False)
        if st.session_state.show_mini:
            st.session_state.show_threads = False
    elif action == "new_chat":
        _activate_session(chat_store.create_session()["id"])
        st.session_state.show_threads = False
    elif action == "switch_session":
        sid = str(val.get("session_id") or "")
        if chat_store.get_session(sid):
            _activate_session(sid)
        st.session_state.show_threads = False
    elif action == "delete_session":
        sid = str(val.get("session_id") or "")
        if chat_store.delete_session(sid):
            if sid == st.session_state.get("chat_session_id"):
                _activate_session(chat_store.get_active_session_id())
    elif action == "send":
        text = str(val.get("text") or "").strip()
        if text:
            # V3.3.3 个性化记忆：记录提问话题与涉及的股票（隐式学习）
            record_question(text)
            for tk in _extract_tickers(text):
                record_stock(tk)
            # V3.2.2c：记录该话题在讨论什么（页面模式/股票/周期快照）
            chat_store.set_session_context(
                st.session_state.get("chat_session_id"), _page_state())
            _append({"role": "user", "content": text})
# ─── 组件调用（fab + 抽屉 UI 在 index.html 中，参数经 RENDER 消息下发）──

def _panel_args(lang: str, show: bool) -> dict:
    """传给组件前端的文案与状态参数（含话题列表，V3.2.2b）"""
    show_threads = st.session_state.get("show_threads", False)
    # 深度分析快捷按钮：优先带当前页面股票（"深度分析 AAPL"），无则裸提示
    deep_label = t("chat_q_deep", lang)
    _st = _page_state()
    _tk = _st.get("ticker") or (_st.get("tickers") or [None])[0] or ""
    if _tk:
        deep_label = f"{deep_label} {str(_tk).upper()}"
    quick_labels = [deep_label] + [t(f"chat_q_{k}", lang) for k in QUICK_KEYS]
    return {
        "title": t("threads_title", lang) if show_threads
                 else t("chat_drawer_title", lang),
        "model": "" if show_threads else _active_model_text(lang),
        "placeholder": t("chat_input_placeholder", lang),
        "send_label": t("chat_send", lang),
        "clear_label": t("chat_clear", lang),
        "show": show,
        "show_threads": show_threads,
        "show_mini": st.session_state.get("show_mini", False),
        "mini_label": t("chat_mini", lang),
        "restore_label": t("chat_restore", lang),
        "threads": _threads_payload(lang),
        "active_thread": st.session_state.get("chat_session_id"),
        "new_label": t("thread_new", lang),
        "delete_label": t("thread_delete", lang),
        "delete_confirm_label": t("thread_delete_confirm", lang),
        "empty_label": t("thread_empty", lang),
        "show_quick": not st.session_state.chat_messages,
        "quick_labels": quick_labels,
        "deep_quick_label": deep_label,
    }


def _panel_css(show: bool, show_mini: bool = False, show_quick: bool = True) -> str:
    """注入组件 iframe 与消息区浮层的兜底样式（默认右下角，V3.2.2d 起无遮罩）。

    定位的权威在 iframe 内 JS（components/ai_frontend/index.html 的 layout()）：
    开/关抽屉、最小化、窗口缩放都由 JS 用「内联 !important」直接设置 iframe 与
    #chat-msgs 的位置/尺寸。这里只保留 JS 生效前的右下角兜底，避免 Python CSS 与
    JS 内联样式互相覆盖，导致 iframe 缩回 56px（“半个输入框”）或两框错位。

    V3.2.2d：不再渲染全屏遮罩（背景页面保持清晰、可滚动、可交互），
    抽屉与页面平级共存；阴影加在 iframe 本身（父页面绘制，不被 iframe 裁剪）。
    """
    msgs_base = (f'position:fixed!important;z-index:9600!important;'
                 f'background:{C["bg"]}!important;'
                 f'border:1px solid {C["border"]}!important;border-radius:14px!important;'
                 f'padding:12px 8px 12px 0!important;overflow-y:auto!important;'
                 f'display:flex!important;flex-direction:column-reverse!important;'
                 f'gap:2px!important;scrollbar-width:thin!important;'
                 f'scrollbar-color:{C["border"]} transparent!important')
    extra_common = (f'#chat-msgs::-webkit-scrollbar{{width:6px!important}} '
                    f'#chat-msgs::-webkit-scrollbar-thumb{{background:{C["border"]}!important;'
                    f'border-radius:3px!important}} '
                    f'#chat-msgs .chat-disclaimer{{margin:10px 4px 4px;padding-top:10px;'
                    f'border-top:1px solid {C["border"]};font-size:.625rem;'
                    f'color:{C["text3"]};line-height:1.5;flex-shrink:0}} '
                    f'#chat-msgs .chat-welcome-hint{{margin:6px 0 0;font-size:.6875rem;'
                    f'color:{C["accent"]}}} '
                    f'#chat-msgs .chat-tool-hint{{margin:10px 4px 4px;padding:8px 12px;'
                    f'background:rgba(10,132,255,.07);border:1px solid rgba(10,132,255,.22);'
                    f'border-radius:12px;font-size:.6875rem;color:#409cff;'
                    f'line-height:1.7;flex-shrink:0}} '
                    f'#chat-msgs .chat-tool-step{{padding:1px 0}} '
                    f'#chat-msgs .chat-chart{{margin:10px 4px 4px;flex-shrink:0}} '
                    f'#chat-msgs .chat-pending-charts{{flex-shrink:0}} '
                    f'#chat-msgs .chat-report-download{{display:inline-block;'
                    f'margin:10px 4px 4px;padding:8px 14px;border-radius:12px;'
                    f'background:rgba(10,132,255,.12);border:1px solid rgba(10,132,255,.4);'
                    f'color:{C["accent"]};font-size:.75rem;font-weight:600;'
                    f'text-decoration:none;flex-shrink:0}} '
                    f'#chat-msgs .chat-report-download:hover{{'
                    f'background:rgba(10,132,255,.24)}}')

    if show:
        # 打开时给 iframe 自身加投影（在父页面绘制，视觉上抽屉“立”在页面上方）
        if show_mini:
            h_expr = f"{MINI_H}px"
        else:
            h_expr = f'min({DRAWER_H_MAX}px, calc(100vh - {2 * DRAWER_BOTTOM}px))'
        iframe_css = (f'position:fixed!important;right:{DRAWER_RIGHT}px!important;'
                      f'bottom:{DRAWER_BOTTOM}px!important;width:{DRAWER_WIDTH}px!important;'
                      f'height:{h_expr}!important;z-index:9500!important;'
                      f'border-radius:18px!important;'
                      f'box-shadow:0 24px 80px rgba(0,0,0,.5)!important')
        if not show_mini:
            # 消息区底部让位给快捷按钮区（深度分析常驻，概念按钮仅空会话显示）
            quick_h = 112 if show_quick else 32
            msgs_css = (f'right:{DRAWER_RIGHT + MSG_PAD}px!important;'
                        f'width:{DRAWER_WIDTH - 2 * MSG_PAD}px!important;'
                        f'top:calc(100vh - {DRAWER_BOTTOM}px - {h_expr} + {TOP_BAR_H}px)!important;'
                        f'bottom:{DRAWER_BOTTOM + INPUT_BAR_H + 12 + quick_h + 4}px!important')
            extra = f'#chat-msgs{{{msgs_base}{msgs_css}}} {extra_common}'
        else:
            extra = ""
    else:
        iframe_css = (f'position:fixed!important;right:{DRAWER_RIGHT}px!important;'
                      f'bottom:{DRAWER_BOTTOM}px!important;width:{FAB_SIZE}px!important;'
                      f'height:{FAB_SIZE}px!important;z-index:9500!important;'
                      f'border-radius:28px!important')
        extra = ""
    return f'<style>iframe[title*="ai_panel"]{{{iframe_css}}} {extra}</style>'


def render_ai_panel() -> None:
    """渲染 AI 助手整体：组件 iframe（先处理交互）→ 定位 CSS/遮罩 → 消息区浮层"""
    _ensure_chat_session()
    lang = st.session_state.lang
    panel_key = f"ai_panel_{lang}"

    # 1) 组件 iframe（fab + 抽屉 UI）；返回值即交互动作。
    #    必须先调用并处理动作：toggle/close 会改变 show_chat，
    #    后续 CSS 尺寸与消息浮层必须用处理后的最新值，否则同一轮渲染仍是旧尺寸
    #    （点 AI 球后 iframe 不扩容，抽屉在 56px 里展开 → “半个输入框”）。
    val = ai_panel(**_panel_args(lang, st.session_state.show_chat),
                   height=FAB_SIZE, width=FAB_SIZE, key=panel_key)

    # 语言切换 → key 变化 → iframe 重挂载 → 旧组件返回值作废，需重置
    if st.session_state.get("ai_panel_key") != panel_key:
        st.session_state.ai_panel_key = panel_key
        st.session_state.ai_panel_value = None

    prev = st.session_state.get("ai_panel_value", None)
    if val is not None and val != prev:
        st.session_state.ai_panel_value = val
        handle_ai_action(val, lang)

    # 2) 定位样式（用处理动作后的最新状态；V3.2.2d 起无遮罩，背景页面始终可交互）
    show = st.session_state.show_chat
    st.markdown(_panel_css(show, st.session_state.get("show_mini", False),
                           not st.session_state.chat_messages),
                unsafe_allow_html=True)

    # 3) 消息区浮层（Python 渲染；流式输出实时更新）
    box = st.empty()
    _render_messages(box, lang)


def _render_messages(box, lang: str) -> None:
    """渲染消息区；若最后一条是用户消息则调用模型流式回复"""
    current = st.session_state.chat_messages
    if not st.session_state.show_chat:
        # 显式清空：防止抽屉关闭后旧浮层残留（st.empty 内容跨 rerun 保留）
        box.empty()
        return
    # 话题列表 / 最小化时隐藏消息区（消息区浮层与抽屉面板互斥）
    if st.session_state.get("show_threads") or st.session_state.get("show_mini"):
        # 显式清空：防止旧消息浮层盖在话题面板上（“影子”）或残留在迷你条外
        box.empty()
        return
    # 渲染前清空容器：清除旧节点（含 JS 乐观隐藏时残留的 display:none）
    box.empty()
    if current and current[-1]["role"] == "user":
        sid = st.session_state.get("chat_session_id")
        profile = _active_profile(get_llm_profiles())
        if not profile.get("api_key") or not profile.get("model"):
            err = t("llm_error_not_configured", lang)
            box.markdown(
                _messages_html(current + [{"role": "assistant", "content": err}], lang),
                unsafe_allow_html=True,
            )
            _append({"role": "assistant", "content": err}, session_id=sid, target=current)
            return

        box.markdown(_messages_html(current, lang), unsafe_allow_html=True)
        deep = _is_deep_request(current[-1].get("content", ""))
        chart_req = _is_chart_request(current[-1].get("content", ""))
        text = ""
        hints = []
        charts = []
        _last_paint = time.time()   # 流式重绘节流时间戳
        ctx = _context_text(lang)
        if deep:
            # 深度分析：追加专门的工作流指令（双保险：系统提示词 + 上下文注入）
            deep_ctx = t("deep_analysis_instructions", lang)
            ctx = f"{ctx}\n\n{deep_ctx}" if ctx else deep_ctx
        elif chart_req:
            # 画图请求：注入 plot_chart 指令，防止模型只回文字不调工具
            chart_ctx = t("chart_plot_instructions", lang)
            ctx = f"{ctx}\n\n{chart_ctx}" if ctx else chart_ctx
        for ev in run_agent(
                profile, build_messages(lang, current, context=ctx), lang,
                max_rounds=_DEEP_ROUNDS if deep else MAX_ROUNDS):
            if ev.get("t") == "tool":
                c = ev.get("c", "")
                if c and c not in hints:
                    hints.append(c)
                html = ev.get("html") or ""
                if html:
                    charts.append(html)
                # 工具执行中：显示过程提示轨迹 + 已生成的图表（不等回答文本）
                msgs_html = _messages_html(
                    current + [{"role": "assistant", "content": text + "▍"}]
                    if text else current,
                    lang, hint=hints, pending_charts=charts)
                box.markdown(msgs_html, unsafe_allow_html=True)
            else:
                text += ev.get("c", "")
                now = time.time()
                if now - _last_paint >= _PAINT_GAP:
                    _last_paint = now
                    box.markdown(
                        _messages_html(
                            current + [{"role": "assistant", "content": text + "▍"}],
                            lang, hint=hints),
                        unsafe_allow_html=True,
                    )
        if not text:
            text = t("llm_error_empty", lang)
        # V3.4.4：分析师→风控二次审阅（可选开关；研报生成成功后才触发）
        if deep and text and get_deep_review():
            hints.append(t("deep_review_running", lang))
            box.markdown(
                _messages_html(
                    current + [{"role": "assistant", "content": text + "▍"}],
                    lang, hint=hints),
                unsafe_allow_html=True,
            )
            review = ""
            for ev in run_review(profile, text, lang):
                review += ev.get("c", "")
                now = time.time()
                if now - _last_paint >= _PAINT_GAP:
                    _last_paint = now
                    body = text + ("\n\n" + review if review else "") + "▍"
                    box.markdown(
                        _messages_html(
                            current + [{"role": "assistant", "content": body}],
                            lang, hint=hints),
                        unsafe_allow_html=True,
                    )
            text = _merge_review(text, review, lang)
        # 兜底出图（V3.3.2）：模型漏调 plot_chart 时系统直接生成，
        # 保证「画图」请求一定有图，不再依赖模型自觉
        if chart_req and not charts:
            charts = _server_chart_fallback(current[-1].get("content", ""), lang)
        # 图表随回答一起存入消息（V3.3.2）：磁盘持久化，刷新后仍显示
        assistant_msg = {"role": "assistant", "content": text}
        if charts:
            assistant_msg["charts"] = charts
        # 最终渲染：工具轨迹是过程提示，生成完成后不再显示
        box.markdown(
            _messages_html(
                current + [assistant_msg], lang,
                report_download=(_report_download_html(lang, text) if deep else "")),
            unsafe_allow_html=True,
        )
        _append(assistant_msg, session_id=sid, target=current)
    else:
        box.markdown(_messages_html(current, lang), unsafe_allow_html=True)
