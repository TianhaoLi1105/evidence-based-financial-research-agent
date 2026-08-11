"""
Agent Tools (V3.2.1)
====================
金融数据工具层：把本应用已有的数据能力封装成 LLM 可调用的 Function Tools。

每个工具返回「精简后的结构化 dict」（序列化 JSON 回传给模型）：
- 只保留关键字段，控制 token 消耗
- 所有字段允许为 None（数据缺失时不编造）
- 参数校验失败 / 数据源失败时返回 {"error": ...}，不抛异常，
  由模型决定如何向用户说明

数据源全部复用现有 stock_service 的降级链路（缓存 → Twelve Data → 腾讯备用源），
不新增 API Key、不增加额外 API 消耗。
"""

import json
import re

from services.stock_service import (
    _time_series_with_fallback, _quote_with_fallback, _fallback_stats,
    _outputsize_for_interval, fetch_compare_data, profile_with_fallback,
)
from data.finance_data import get_statistics, get_profile
from data.fundamentals import (
    get_fundamentals, valuation_fallback, _from_stockanalysis_profile,
)
from data.news import get_news
from data.valuation import get_valuation
from data.indicators import compute_indicators
from components.chart_svg import price_line_svg, candlestick_svg, multi_line_svg
from utils import safe_float

# ─── 常量 ────────────────────────────────────────────────
MAX_TICKERS = 5       # compare 工具最多同时比较的股票数
MAX_RESULT_CHARS = 4000   # 单个工具结果回传给模型的字符上限
RECENT_BARS = 5       # K 线工具返回给模型的最近 K 线条数

_VALID_INTERVALS = ("1day", "1week", "1month")
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


# ─── 通用校验 / 数值工具 ─────────────────────────────────

def clean_ticker(value) -> str:
    """校验并规范化股票代码（如 ' aapl ' → 'AAPL'）"""
    tk = str(value or "").strip().upper()
    if not _TICKER_RE.fullmatch(tk):
        raise ValueError(f"invalid ticker: {value!r}")
    return tk


def clean_interval(value) -> str:
    iv = str(value or "").strip().lower()
    return iv if iv in _VALID_INTERVALS else "1day"


def clean_days(value, default: int = 365, lo: int = 30, hi: int = 3650) -> int:
    try:
        d = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, d))


def _last(rows: list, key: str):
    """取升序列表最后一条的字段值（最新值）"""
    if not rows:
        return None
    return safe_float(rows[-1].get(key))


def _pick(d: dict, *keys):
    """多候选键名提取（兼容 Twelve Data / 备用源字段差异）"""
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def _f52(d: dict):
    """提取 52 周高低（quote 里的 fifty_two_week 可能是 dict）"""
    r = d.get("fifty_two_week") or {}
    if isinstance(r, dict):
        return safe_float(r.get("high")), safe_float(r.get("low"))
    return None, None


# ─── 工具 1：实时报价 ────────────────────────────────────

def tool_get_quote(ticker: str) -> dict:
    tk = clean_ticker(ticker)
    quote, source = _quote_with_fallback(tk)
    h52, l52 = _f52(quote)
    return {
        "symbol": tk,
        "name": quote.get("name") or tk,
        "exchange": quote.get("exchange"),
        "currency": quote.get("currency"),
        "close": safe_float(quote.get("close")),
        "change": safe_float(quote.get("change")),
        "percent_change": safe_float(quote.get("percent_change")),
        "open": safe_float(quote.get("open")),
        "high": safe_float(quote.get("high")),
        "low": safe_float(quote.get("low")),
        "volume": safe_float(quote.get("volume")),
        "fifty_two_week_high": h52,
        "fifty_two_week_low": l52,
        "pe_ratio": safe_float(quote.get("pe_ratio")),
        "market_cap": safe_float(quote.get("market_cap")),
        "source": source,
    }


# ─── 工具 2：历史 K 线（摘要）────────────────────────────

def tool_get_time_series(ticker: str, days: int = 365,
                         interval: str = "1day") -> dict:
    tk = clean_ticker(ticker)
    days = clean_days(days)
    interval = clean_interval(interval)
    rows, source = _time_series_with_fallback(
        tk, _outputsize_for_interval(days, interval), interval)

    if not rows:
        return {"symbol": tk, "error": "no price history available"}

    first_close = safe_float(rows[0].get("close"))
    last_close = safe_float(rows[-1].get("close"))
    highs = [safe_float(r.get("high")) for r in rows]
    lows = [safe_float(r.get("low")) for r in rows]
    vols = [safe_float(r.get("volume")) for r in rows]

    recent = [{
        "datetime": r.get("datetime"),
        "open": safe_float(r.get("open")),
        "high": safe_float(r.get("high")),
        "low": safe_float(r.get("low")),
        "close": safe_float(r.get("close")),
        "volume": safe_float(r.get("volume")),
    } for r in rows[-RECENT_BARS:]]

    return {
        "symbol": tk,
        "interval": interval,
        "requested_days": days,
        "bars": len(rows),
        "first_datetime": rows[0].get("datetime"),
        "last_datetime": rows[-1].get("datetime"),
        "first_close": first_close,
        "last_close": last_close,
        "period_change_pct": ((last_close / first_close - 1) * 100
                              if first_close else None),
        "period_high": max((h for h in highs if h is not None), default=None),
        "period_low": min((l for l in lows if l is not None), default=None),
        "avg_volume": (int(sum(v for v in vols if v is not None) / len(rows))
                       if rows else None),
        "recent": recent,
        "source": source,
    }


# ─── 工具 3：财务数据 ────────────────────────────────────

def tool_get_financials(ticker: str) -> dict:
    """核心财务数据：三大报表关键项 + 估值指标（双源降级，字段可空）"""
    tk = clean_ticker(ticker)
    stats = {}
    try:
        stats = get_statistics(tk) or {}
    except Exception:
        stats = {}

    # 免费 Key 拿不到 statistics 时，用备用报价补估值字段
    if not stats:
        try:
            q, _ = _quote_with_fallback(tk)
        except Exception:
            q = {}
        if q.get("pe_ratio") is not None or q.get("market_cap") is not None:
            stats = _fallback_stats(q)

    out = _extract_financials(tk, stats)

    # V3.4.2：免费 Key 的 /quote 不含 PE/市值 → 腾讯备用报价 / stockanalysis 补齐
    if out.get("market_cap") is None or out.get("pe_ratio") is None:
        try:
            val = valuation_fallback(tk)
            if out.get("market_cap") is None and val.get("market_cap") is not None:
                out["market_cap"] = val["market_cap"]
            if out.get("pe_ratio") is None and val.get("pe_ratio") is not None:
                out["pe_ratio"] = val["pe_ratio"]
        except Exception:
            pass

    # V3.4.1：财务深度（利润表/资产负债表/现金流 + 趋势）
    f = get_fundamentals(tk)
    for k in ("revenue", "net_income", "gross_profit", "gross_margin",
              "net_margin", "revenue_growth_yoy", "net_income_growth_yoy",
              "revenue_trend", "net_income_trend", "total_assets",
              "total_liabilities", "stockholders_equity", "debt_to_equity",
              "current_ratio", "operating_cash_flow", "investing_cash_flow",
              "financing_cash_flow", "eps", "roe"):
        v = f.get(k)
        if v not in (None, [], ""):
            out[k] = v
    if f.get("source") and f["source"] != "none":
        out["source"] = f["source"]
    return out


def _extract_financials(tk: str, stats: dict) -> dict:
    """从 Twelve Data statistics / 备用 stats 中提取核心财务指标"""
    valuations = stats.get("valuations_metrics") or {}
    quote_fb = stats.get("quote_fallback") or {}

    def pick(*keys):
        return (_pick(stats, *keys) or _pick(valuations, *keys)
                or _pick(quote_fb, *keys))

    return {
        "symbol": tk,
        "market_cap": safe_float(pick("market_capitalization", "market_cap",
                                       "marketCapitalization")),
        "pe_ratio": safe_float(pick("pe_ratio", "trailing_pe", "pe")),
        "eps": safe_float(pick("eps", "earnings_per_share")),
        "revenue": safe_float(pick("revenue", "total_revenue")),
        "net_income": safe_float(pick("net_income", "netIncome")),
        "gross_margin": safe_float(pick("gross_margin", "grossMargin")),
        "operating_margin": safe_float(pick("operating_margin", "operatingMargin")),
        "return_on_equity": safe_float(pick("return_on_equity", "returnOnEquity")),
        "debt_to_equity": safe_float(pick("debt_to_equity", "debtToEquity")),
        "dividend_yield": safe_float(pick("dividend_yield", "dividendYield")),
        "beta": safe_float(pick("beta")),
        "shares_outstanding": safe_float(pick("shares_outstanding")),
        "fifty_two_week_high": safe_float(
            pick("fifty_two_week_high", "52_week_high")
            or _f52(quote_fb)[0]),
        "fifty_two_week_low": safe_float(
            pick("fifty_two_week_low", "52_week_low")
            or _f52(quote_fb)[1]),
        "source": "twelvedata" if stats.get("valuations_metrics") is not None
                  else "tencent-fallback",
    }


# ─── 工具 4：公司概况 ────────────────────────────────────

def tool_get_profile(ticker: str) -> dict:
    tk = clean_ticker(ticker)
    p = profile_with_fallback(tk) or {}

    return {
        "symbol": tk,
        "name": p.get("name") or tk,
        "exchange": p.get("exchange"),
        "industry": p.get("industry"),
        "sector": p.get("sector"),
        "ceo": p.get("ceo"),
        "employees": safe_float(p.get("employees")),
        "website": p.get("website"),
        "description": (str(p.get("description") or "")[:600]) or None,
        "source": p.get("source") or "twelvedata",
    }


# ─── 工具 5：技术指标快照 ────────────────────────────────

def tool_get_indicators(ticker: str, days: int = 365,
                        interval: str = "1day") -> dict:
    tk = clean_ticker(ticker)
    days = clean_days(days)
    interval = clean_interval(interval)
    rows, source = _time_series_with_fallback(
        tk, _outputsize_for_interval(days, interval), interval)
    if not rows:
        return {"symbol": tk, "error": "no price history available"}

    ind = compute_indicators(rows)
    macd = ind.get("macd") or {}
    boll = ind.get("boll") or {}

    def latest(rows_list, key):
        return _last(rows_list, key)

    return {
        "symbol": tk,
        "interval": interval,
        "last_close": safe_float(rows[-1].get("close")),
        "ma20": latest(ind.get("ma20", []), "ma20"),
        "ma60": latest(ind.get("ma60", []), "ma60"),
        "ema12": latest(ind.get("ema12", []), "ema12"),
        "ema26": latest(ind.get("ema26", []), "ema26"),
        "rsi14": latest(ind.get("rsi14", []), "rsi14"),
        "macd_dif": latest(macd.get("dif", []), "dif"),
        "macd_dea": latest(macd.get("dea", []), "dea"),
        "macd_hist": latest(macd.get("hist", []), "hist"),
        "boll_upper": latest(boll.get("upper", []), "upper"),
        "boll_middle": latest(boll.get("middle", []), "middle"),
        "boll_lower": latest(boll.get("lower", []), "lower"),
        "source": "computed-locally",
    }


# ─── 工具 6：多股对比 ────────────────────────────────────

def tool_compare(tickers: list, days: int = 365,
                 interval: str = "1day") -> dict:
    if not tickers:
        raise ValueError("tickers is required")
    tks = [clean_ticker(t) for t in tickers][:MAX_TICKERS]
    if len(tks) < 2:
        raise ValueError("need at least 2 tickers to compare")
    days = clean_days(days)
    interval = clean_interval(interval)

    quotes, histories, sources = fetch_compare_data(tks, days, interval)
    items = []
    for tk in tks:
        rows = histories.get(tk) or []
        q = quotes.get(tk) or {}
        first_close = safe_float(rows[0].get("close")) if rows else None
        last_close = safe_float(rows[-1].get("close")) if rows else None
        # V3.4.5：估值对比补充「52 周价格位置」（免费源可算，增强估值口径）
        h52, l52 = _f52(q)
        pos52 = None
        if last_close is not None and h52 and l52 and h52 > l52:
            pos52 = max(0.0, min(100.0,
                                 (last_close - l52) / (h52 - l52) * 100))
            pos52 = round(pos52, 1)
        items.append({
            "symbol": tk,
            "name": q.get("name") or tk,
            "close": safe_float(q.get("close")),
            "percent_change": safe_float(q.get("percent_change")),
            "pe_ratio": safe_float(q.get("pe_ratio")),
            "market_cap": safe_float(q.get("market_cap")),
            "price_position_52w_pct": pos52,
            "period_change_pct": ((last_close / first_close - 1) * 100
                                  if first_close else None),
            "last_close": last_close,
            "source": sources.get(tk),
        })
    return {"tickers": tks, "interval": interval, "days": days, "items": items}


# ─── 工具 7：对话内出图（V3.3.2）─────────────────────────

def _window_fallbacks(days: int) -> list:
    """出图窗口降级序列：优先请求的窗口，失败时依次退到更短窗口，
    尽量命中本地缓存或更小请求（数据源限流/失败时也能出图）"""
    windows = [days]
    for d in (180, 90, 30):
        if d < days and d not in windows:
            windows.append(d)
    return windows


def tool_plot_chart(tickers: list, days: int = 365, interval: str = "1day",
                    chart_type: str = "line") -> dict:
    """生成价格图表：单股折线/蜡烛，多股归一化对比折线。

    返回 dict 内含 _chart_html（SVG 图表，由 executor 提取后只进 UI、
    不随结果发给模型）；模型侧只收到元数据确认。
    数据获取失败时自动降级到更短窗口（365→180→90→30），保证尽量出图。
    """
    if not tickers:
        raise ValueError("tickers is required")
    tks = [clean_ticker(t) for t in tickers][:MAX_TICKERS]
    if not tks:
        raise ValueError("invalid ticker")
    days = clean_days(days)
    interval = clean_interval(interval)
    chart_type = str(chart_type or "line").strip().lower()
    if chart_type not in ("line", "candlestick"):
        chart_type = "line"

    if len(tks) == 1:
        tk = tks[0]
        rows, source, used_days = None, None, days
        for d in _window_fallbacks(days):
            try:
                rows, source = _time_series_with_fallback(
                    tk, _outputsize_for_interval(d, interval), interval)
            except Exception:
                rows, source = None, None
            if rows:
                used_days = d
                break
        if not rows:
            return {"error": "no price history available", "symbol": tk}
        html = (candlestick_svg(rows) if chart_type == "candlestick"
                else price_line_svg(rows, ticker=tk))
        return {"symbol": tk, "bars": len(rows), "days": used_days,
                "chart_type": chart_type, "source": source,
                "message": "chart generated", "_chart_html": html}

    try:
        quotes, histories, sources = fetch_compare_data(tks, days, interval)
    except Exception:
        quotes, histories, sources = {}, {}, {}
    data = {tk: rows for tk, rows in histories.items() if rows}
    if not data:
        return {"error": "no price history available", "tickers": tks}
    html = multi_line_svg(data)
    return {"tickers": tks, "bars": {tk: len(rows) for tk, rows in data.items()},
            "chart_type": "line", "source": "mixed",
            "message": "chart generated", "_chart_html": html}


# ─── 工具注册与统一分发 ──────────────────────────────────

# ─── 工具 8：公司新闻（V3.4.2）──────────────────────────

def tool_get_news(ticker: str, limit: int = 8) -> dict:
    """最近公司新闻（东财 → Google News 兜底，1h 缓存）"""
    tk = clean_ticker(ticker)
    try:
        lim = max(1, min(int(limit), 15))
    except (TypeError, ValueError):
        lim = 8
    return get_news(tk, limit=lim)



def tool_get_valuation(ticker: str) -> dict:
    """估值相对位置：PE vs 行业同行中位数 + 52 周价格位置（V3.4.3）"""
    tk = clean_ticker(ticker)
    return get_valuation(tk)


TOOLS = {
    "get_quote": tool_get_quote,
    "get_time_series": tool_get_time_series,
    "get_financials": tool_get_financials,
    "get_profile": tool_get_profile,
    "get_indicators": tool_get_indicators,
    "compare": tool_compare,
    "plot_chart": tool_plot_chart,
    "get_news": tool_get_news,
    "get_valuation": tool_get_valuation,
}


def dispatch_tool(name: str, args) -> dict:
    """统一执行入口：校验 → 调用 → 异常包装为 {"error": ...}"""
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {"error": f"tool args must be a JSON object, got {type(args).__name__}"}
    try:
        return fn(**args)
    except Exception as e:
        return {"error": f"{name} failed: {str(e)[:200]}"}


def result_to_json(result) -> str:
    """工具结果序列化（截断超长输出，控制 token）"""
    try:
        s = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        s = '{"error": "failed to serialize tool result"}'
    if len(s) > MAX_RESULT_CHARS:
        s = s[:MAX_RESULT_CHARS] + "…(truncated)"
    return s

# ─── LLM 工具 Schema（OpenAI function calling 格式）───────

TOOL_SCHEMAS = [{'type': 'function', 'function': {'name': 'get_quote', 'description': "Get a real-time stock quote: price, change, volume, 52-week range, P/E ratio and market cap. Use for questions about a stock's current price or today's move.", 'parameters': {'type': 'object', 'properties': {'ticker': {'type': 'string', 'description': 'Stock ticker symbol, e.g. AAPL'}}, 'required': ['ticker']}}}, {'type': 'function', 'function': {'name': 'get_time_series', 'description': "Get historical price data (OHLCV) for a stock, with a summary of the period's change, high, low and the most recent bars. Use for trend/performance questions over a time range.", 'parameters': {'type': 'object', 'properties': {'ticker': {'type': 'string', 'description': 'Stock ticker symbol, e.g. AAPL'}, 'days': {'type': 'integer', 'description': 'Lookback window in days (30-3650). Default 365.', 'minimum': 30, 'maximum': 3650}, 'interval': {'type': 'string', 'enum': ['1day', '1week', '1month'], 'description': 'Bar interval. Default 1day.'}}, 'required': ['ticker']}}}, {'type': 'function', 'function': {'name': 'get_financials', 'description': 'Get core financials for a stock: income statement (revenue, net income, margins, YoY growth, quarterly trends), balance sheet (total assets, liabilities, equity, debt/equity, current ratio), cash flow, plus valuation (market cap, P/E, EPS, ROE, dividend yield, beta). Use for valuation, fundamentals and financial health questions.', 'parameters': {'type': 'object', 'properties': {'ticker': {'type': 'string', 'description': 'Stock ticker symbol, e.g. AAPL'}}, 'required': ['ticker']}}}, {'type': 'function', 'function': {'name': 'get_profile', 'description': 'Get company overview: name, exchange, industry, sector, CEO, employees, website and business description. Use for questions about what a company does.', 'parameters': {'type': 'object', 'properties': {'ticker': {'type': 'string', 'description': 'Stock ticker symbol, e.g. AAPL'}}, 'required': ['ticker']}}}, {'type': 'function', 'function': {'name': 'get_indicators', 'description': 'Get the latest technical indicator values for a stock: MA20/MA60, EMA12/EMA26, RSI14, MACD (DIF/DEA/histogram) and Bollinger Bands. Use for technical analysis questions.', 'parameters': {'type': 'object', 'properties': {'ticker': {'type': 'string', 'description': 'Stock ticker symbol, e.g. AAPL'}, 'days': {'type': 'integer', 'description': 'Lookback window in days. Default 365.', 'minimum': 30, 'maximum': 3650}, 'interval': {'type': 'string', 'enum': ['1day', '1week', '1month'], 'description': 'Bar interval. Default 1day.'}}, 'required': ['ticker']}}}, {'type': 'function', 'function': {'name': 'compare', 'description': 'Compare 2-5 stocks side by side: current price, daily change, P/E, market cap and period performance. Use for multi-stock comparison questions — call this ONCE with all tickers instead of calling get_quote for each stock individually.', 'parameters': {'type': 'object', 'properties': {'tickers': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 2, 'maxItems': 5, 'description': 'List of stock ticker symbols, e.g. [AAPL, MSFT]'}, 'days': {'type': 'integer', 'description': 'Lookback window in days. Default 365.', 'minimum': 30, 'maximum': 3650}, 'interval': {'type': 'string', 'enum': ['1day', '1week', '1month'], 'description': 'Bar interval. Default 1day.'}}, 'required': ['tickers']}}}]


# V3.4.2：公司新闻工具 schema（追加到 TOOL_SCHEMAS，供 Function Calling）
# V3.4.3：估值相对位置工具 schema（追加到 TOOL_SCHEMAS，供 Function Calling）
TOOL_SCHEMAS.append({'type': 'function', 'function': {
    'name': 'get_valuation',
    'description': 'Evaluate whether a stock is expensive or cheap relative to its industry peers: P/E ratio, industry median P/E, P/E premium vs peers, and the current price position within the 52-week range. Use for questions like "is AAPL expensive right now" or "how is NVDA valued".',
    'parameters': {'type': 'object', 'properties': {
        'ticker': {'type': 'string', 'description': 'Stock ticker symbol, e.g. AAPL'}},
        'required': ['ticker']}}})


TOOL_SCHEMAS.append({'type': 'function', 'function': {
    'name': 'get_news',
    'description': 'Get recent news headlines for a stock with dates, sources and links. Use for questions about recent news, events or market sentiment around a company.',
    'parameters': {'type': 'object', 'properties': {
        'ticker': {'type': 'string', 'description': 'Stock ticker symbol, e.g. NVDA'},
        'limit': {'type': 'integer', 'description': 'Max number of headlines (1-15). Default 8.'}},
        'required': ['ticker']}}})

# V3.3.2：对话内出图工具 schema（追加到 TOOL_SCHEMAS，供 Function Calling）
TOOL_SCHEMAS.append({'type': 'function', 'function': {
    'name': 'plot_chart',
    'description': 'Generate a price chart rendered inside the chat: line (price trend) or candlestick for one ticker, or a normalized multi-line comparison for 2-5 tickers. Use when the user asks to draw/plot/chart/show the K-line, trend or price chart of one or more stocks.',
    'parameters': {'type': 'object', 'properties': {
        'tickers': {'type': 'array', 'items': {'type': 'string'},
                    'minItems': 1, 'maxItems': 5,
                    'description': 'Stock ticker symbols, e.g. [AAPL] or [AAPL, MSFT]'},
        'days': {'type': 'integer', 'description': 'Lookback window in days (30-3650). Default 365.',
                 'minimum': 30, 'maximum': 3650},
        'interval': {'type': 'string', 'enum': ['1day', '1week', '1month'],
                     'description': 'Bar interval. Default 1day.'},
        'chart_type': {'type': 'string', 'enum': ['line', 'candlestick'],
                       'description': 'line = price trend (default); candlestick = OHLC candles.'}},
        'required': ['tickers']}}})
