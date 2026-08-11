"""
Agent Executor (V3.2.1)
=======================
工具调用循环：让 LLM 通过 Function Calling 自主调用本地数据工具，
基于真实数据回答；最多执行 max_rounds 轮，防止失控。

对外接口：run_agent() 是一个生成器，逐段产出事件 dict：
    {"t": "text", "c": "文本片段"}    → 追加到回答的流式输出
    {"t": "tool", "c": "提示文案"}    → 显示一条“正在查询…”的过程提示

兼容性：
- 不支持 tools 的模型（如 deepseek-reasoner）自动降级为纯聊天，
  并切换为“无工具”系统提示词（诚实说明无法获取实时数据）。
- 带 tools 请求被 API 拒绝（400/参数不支持）时同样自动降级重试。
- 任何网络/鉴权错误都转成本地化提示文本，不中断界面。
"""

import json

import openai

from i18n import t
from agent.llm_client import stream_chat, _map_error, _error_text
from agent.prompts import build_messages
from agent.tools import TOOL_SCHEMAS, dispatch_tool, result_to_json

MAX_ROUNDS = 3  # 单次回答最多执行的 LLM 往返轮数


def _supports_tools(model: str) -> bool:
    """按模型名预判是否支持 function calling"""
    m = str(model or "").lower()
    return "reasoner" not in m


def _tools_rejected(e: Exception) -> bool:
    """判断 API 错误是否因 tools 参数不受支持（用于自动降级）"""
    msg = str(e).lower()
    if "tool" not in msg and "function" not in msg:
        return False
    return any(k in msg for k in (
        "support", "unsupported", "unknown", "invalid",
        "parameter", "not supported", "don't", "does not",
    ))


def _history_from(messages: list) -> list:
    """去掉开头的 system 消息，还原为会话历史（供降级时重建消息）"""
    h = list(messages)
    if h and h[0].get("role") == "system":
        h = h[1:]
    return h


def _fallback_chat(profile: dict, messages: list, lang: str):
    """降级：不带 tools 的纯流式聊天（使用“无工具”系统提示词）"""
    fallback_msgs = build_messages(lang, _history_from(messages), use_tools=False)
    for chunk in stream_chat(profile, fallback_msgs, lang):
        yield {"t": "text", "c": chunk}


# ─── 工具调用收集与执行 ──────────────────────────────────

def _collect_stream(resp) -> tuple:
    """收集流式响应：返回 (文本, 工具调用列表)"""
    text_parts = []
    calls = {}  # index -> {"id", "name", "arguments"}
    for chunk in resp:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if getattr(delta, "content", None):
            text_parts.append(delta.content)
        tcs = getattr(delta, "tool_calls", None)
        if not tcs:
            continue
        for tc in tcs:
            idx = getattr(tc, "index", 0) or 0
            entry = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            if getattr(tc, "id", None):
                entry["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    entry["name"] += fn.name
                if getattr(fn, "arguments", None):
                    entry["arguments"] += fn.arguments
    text = "".join(text_parts)
    call_list = [calls[i] for i in sorted(calls)]
    return text, [c for c in call_list if c["name"]]


def _tool_call_id(call: dict, index: int) -> str:
    return call.get("id") or f"call_{index}"


def _parse_args(raw: str) -> dict:
    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {}
    except Exception:
        return {}


_TOOL_LABELS = {
    "get_quote": {"en": "real-time quote", "zh": "实时行情"},
    "get_time_series": {"en": "price history", "zh": "历史K线"},
    "get_financials": {"en": "financial data", "zh": "财务数据"},
    "get_profile": {"en": "company profile", "zh": "公司概况"},
    "get_indicators": {"en": "technical indicators", "zh": "技术指标"},
    "compare": {"en": "comparison data", "zh": "多股对比数据"},
    "plot_chart": {"en": "price chart", "zh": "价格图表"},
}


def _query_hint(lang: str, name: str, args: dict) -> str:
    """生成“正在查询…”的过程提示文案"""
    label = _TOOL_LABELS.get(name, {}).get(lang) or name
    subject = ""
    tk = args.get("ticker")
    tks = args.get("tickers")
    if tk:
        subject = str(tk)
    elif tks:
        subject = "、".join(str(x) for x in tks)
    return t("agent_tool_querying", lang, tool=label, subject=subject)


def _run_tool(call: dict, index: int):
    """执行单个工具：返回 (工具名, 参数, 结果JSON字符串, 图表HTML)。

    图表工具（plot_chart）的 _chart_html 只用于 UI 渲染，
    从结果中取出，不随 JSON 发给模型（避免 token 浪费）。
    """
    name = call.get("name", "")
    args = _parse_args(call.get("arguments", ""))
    result = dispatch_tool(name, args)
    chart_html = ""
    if isinstance(result, dict) and result.get("_chart_html"):
        chart_html = result.pop("_chart_html")
    return name, args, result_to_json(result), chart_html


# ─── 主入口 ──────────────────────────────────────────────

def run_review(profile: dict, report_text: str, lang: str = "en"):
    """
    V3.4.4 风控复核（分析师→风控二次审阅的第二轮）。

    不调用任何数据工具：把分析师研报全文交给「风控复核员」角色，
    复核数据支撑、指出缺口与遗漏风险。流式产出文本片段；失败时
    产出本地化错误提示，绝不抛异常。

    yield {"t": "text", "c": str}
    """
    from agent.prompts import build_review_messages
    from agent.llm_client import stream_chat

    api_key = (profile or {}).get("api_key") or ""
    model = (profile or {}).get("model") or ""
    if not api_key or not model or not report_text:
        return

    try:
        msgs = build_review_messages(lang, report_text)
    except Exception:
        return

    for chunk in stream_chat(profile, msgs, lang, temperature=0.4):
        yield {"t": "text", "c": chunk}


def run_agent(profile: dict, messages: list, lang: str = "en",
              max_rounds: int = MAX_ROUNDS):
    """
    工具化对话主循环（生成器）。

    profile:  {"api_key", "base_url", "model", ...}
    messages: [{"role": "system"|"user"|"assistant", "content": str}, ...]
    lang:     界面语言（错误/提示文案）

    yield {"t": "text", "c": str} / {"t": "tool", "c": str}
    """
    api_key = (profile or {}).get("api_key") or ""
    base_url = (profile or {}).get("base_url") or ""
    model = (profile or {}).get("model") or ""

    if not api_key or not model:
        yield {"t": "text", "c": t("llm_error_not_configured", lang)}
        return

    if not _supports_tools(model):
        yield {"t": "tool", "c": t("agent_tools_unsupported", lang)}
        yield from _fallback_chat(profile, messages, lang)
        return

    try:
        client = openai.OpenAI(api_key=api_key, base_url=base_url or None, timeout=60)
    except Exception as e:
        yield {"t": "text", "c": _error_text(_map_error(e), lang)}
        return

    msgs = list(messages)
    for _round in range(max_rounds):
        try:
            resp = client.chat.completions.create(
                model=model, messages=msgs, tools=TOOL_SCHEMAS,
                tool_choice="auto", stream=True,
            )
        except Exception as e:
            if _tools_rejected(e):
                # 模型不支持 tools：降级为纯聊天（无工具提示词）
                yield {"t": "tool", "c": t("agent_tools_unsupported", lang)}
                yield from _fallback_chat(profile, messages, lang)
                return
            yield {"t": "text", "c": _error_text(_map_error(e), lang)}
            return

        text, calls = _collect_stream(resp)
        if calls:
            assistant_msg = {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {"id": _tool_call_id(c, i), "type": "function",
                     "function": {"name": c["name"], "arguments": c["arguments"]}}
                    for i, c in enumerate(calls)
                ],
            }
            msgs.append(assistant_msg)
            for i, c in enumerate(calls):
                name, args, result, chart_html = _run_tool(c, i)
                msgs.append({"role": "tool", "tool_call_id": _tool_call_id(c, i),
                             "content": result})
                yield {"t": "tool", "c": _query_hint(lang, name, args),
                       "html": chart_html or ""}
            continue

        if text:
            yield {"t": "text", "c": text}
        else:
            yield {"t": "text", "c": t("llm_error_empty", lang)}
        return

    yield {"t": "text", "c": t("agent_tool_limit", lang)}
