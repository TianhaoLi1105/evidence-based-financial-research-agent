"""
Stock Service
==============
业务逻辑层：组合主数据源（Twelve Data）+ 备用数据源（腾讯财经）
+ 本地磁盘缓存 + 本地指标计算，返回分析所需的完整数据。

数据流（降级顺序）：
    K 线   缓存 → Twelve Data → 腾讯备用源
    报价   Twelve Data → 腾讯备用源
    指标   本地计算（不消耗 API）
    统计/概况  Twelve Data，失败时静默降级为空
"""

from data.finance_data import (
    get_quote, get_statistics, get_time_series, get_profile,
    get_batch_quotes,
)
from data.fallback_data import (
    get_fallback_time_series, get_fallback_quote, get_fallback_indices,
)
from data.cache import get_cached_time_series, set_cached_time_series
from data.fundamentals import _from_stockanalysis_profile, get_fundamentals
from data.indicators import compute_indicators


def _outputsize_for_interval(days: int, interval: str) -> int:
    """根据时间范围与 K 线周期换算 API 返回条数"""
    if interval == "1week":
        return max(60, days // 7 + 10)
    if interval == "1month":
        return max(24, days // 30 + 6)
    return days


def _ensure_ascending(rows: list) -> list:
    """
    统一 K 线为时间升序。

    Twelve Data 返回倒序（最新在前），腾讯备用源为正序；
    指标计算、52 周高低价、CSV 导出都依赖升序数据。
    """
    try:
        return sorted(rows, key=lambda r: str(r.get("datetime", "")))
    except Exception:
        return rows


def _time_series_with_fallback(ticker: str, outputsize: int,
                               interval: str = "1day"):
    """
    获取历史 K 线：缓存优先 → Twelve Data → 腾讯备用源。

    返回 (rows, source)，source ∈ {"cache", "twelvedata", "tencent"}
    """
    cached = get_cached_time_series(ticker, interval, outputsize)
    if cached:
        return _ensure_ascending(cached), "cache"

    try:
        rows = get_time_series(ticker, days=outputsize, interval=interval)
        source = "twelvedata"
    except Exception:
        rows = get_fallback_time_series(ticker, outputsize, interval)
        source = "tencent"

    rows = _ensure_ascending(rows)
    set_cached_time_series(ticker, interval, outputsize, rows)
    return rows, source


def _quote_with_fallback(ticker: str, hist: list = None):
    """
    实时报价：Twelve Data → 腾讯备用源。

    返回 (quote, source)，source ∈ {"twelvedata", "tencent"}
    """
    try:
        return get_quote(ticker), "twelvedata"
    except Exception:
        return get_fallback_quote(ticker, hist), "tencent"


def _fallback_stats(quote: dict) -> dict:
    """从备用报价构建估值数据（免费 Key 无法获取 statistics 时使用）"""
    return {
        "valuations_metrics": {
            "market_capitalization": quote.get("market_cap"),
            "trailing_pe": quote.get("pe_ratio"),
        },
        "dividends_and_splits": {},
        "quote_fallback": {
            "fifty_two_week": quote.get("fifty_two_week"),
            "amount": quote.get("amount"),
            "turnover": quote.get("turnover"),
        },
    }


def profile_with_fallback(ticker: str) -> dict:
    """
    公司概况：Twelve Data /profile → stockanalysis 免费兜底。

    免费 Key 无 /profile 权限（403）时，用 stockanalysis 补齐
    简介 / 行业 / 板块 / 员工 / 官网 / 交易所。永不抛异常。
    """
    p = {}
    try:
        p = get_profile(ticker) or {}
    except Exception:
        p = {}
    if not p.get("description") and not p.get("industry"):
        try:
            sa = _from_stockanalysis_profile(ticker)
            q, _ = _quote_with_fallback(ticker)
            p = {
                "name": (q or {}).get("name") or sa.get("name") or ticker,
                "exchange": sa.get("exchange") or (q or {}).get("exchange"),
                "industry": sa.get("industry"),
                "sector": sa.get("sector"),
                "ceo": sa.get("ceo"),
                "employees": sa.get("employees"),
                "website": sa.get("website"),
                "description": sa.get("description"),
                "source": "stockanalysis",
            }
        except Exception:
            p = p or {}
    return p


def fetch_data(ticker: str, period_days: int, interval: str = "1day"):
    """
    获取单只股票的完整分析数据。

    返回 (quote, stats, hist, profile, indicators, hist_source, quote_source)：
    - quote:        实时报价
    - stats:        财务统计（免费 Key 时降级为备用估值数据）
    - hist:         历史 K 线列表（按 interval 周期）
    - profile:      公司基本面（简介/行业/CEO 等）
    - indicators:   {"ma20", "ma60", "ema12", "ema26", "rsi14", "macd", "boll"}
    - hist_source:  K 线数据来源标识（cache / twelvedata / tencent）
    - quote_source: 报价数据来源标识（twelvedata / tencent）
    """
    outputsize = _outputsize_for_interval(period_days, interval)

    # K 线优先（命中缓存可跳过 API；同时为备用报价提供 52 周数据）
    hist, hist_source = _time_series_with_fallback(ticker, outputsize, interval)
    quote, quote_source = _quote_with_fallback(ticker, hist)

    stats = {}
    try:
        stats = get_statistics(ticker)
    except Exception:
        pass  # statistics 接口需要 Pro 套餐，失败时优雅降级

    # statistics 不可用时，用备用源报价补全估值指标（市值/PE/52周高低）
    if not stats:
        if quote.get("pe_ratio") is not None or quote.get("market_cap") is not None:
            stats = _fallback_stats(quote)
        else:
            try:
                fbq = get_fallback_quote(ticker, hist)
                if fbq.get("pe_ratio") is not None or fbq.get("market_cap") is not None:
                    stats = _fallback_stats(fbq)
            except Exception:
                pass

    profile = profile_with_fallback(ticker)

    # V3.4.5：四源财务深度（Twelve Data → stockanalysis → yfinance → 新浪），
    # 免费 Key 下页面「财务数据」也能展示营收/净利/负债率等完整字段
    try:
        stats["deep_fundamentals"] = get_fundamentals(ticker)
    except Exception:
        pass

    # 技术指标本地计算，不再调用 API
    indicators = compute_indicators(hist)

    return quote, stats, hist, profile, indicators, hist_source, quote_source


def fetch_compare_data(tickers: list, period_days: int, interval: str = "1day"):
    """
    获取多只股票的对比数据。

    返回 (quotes, histories, sources)：
    - quotes:    {symbol: quote_dict}，批量接口优先，失败降级逐个查询
    - histories: {symbol: hist_list}
    - sources:   {symbol: K线来源标识}
    """
    quotes = get_batch_quotes(tickers)

    histories = {}
    sources = {}
    for tk in tickers:
        try:
            hist, src = _time_series_with_fallback(tk, period_days, interval)
            histories[tk], sources[tk] = hist, src
        except Exception:
            histories[tk], sources[tk] = [], "none"  # 单只失败不影响整体对比

        # 批量报价缺失时逐个补备用报价
        if tk not in quotes or not quotes.get(tk):
            try:
                quotes[tk] = get_fallback_quote(tk, histories.get(tk))
            except Exception:
                pass

    return quotes, histories, sources


def fetch_indices() -> list:
    """
    三大美股指数报价（道指 / 纳指 / 标普500，备用源免 Key）。
    """
    return get_fallback_indices()
