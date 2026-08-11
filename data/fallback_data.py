"""
Fallback Data Module
=====================
备用数据源：腾讯财经（免 Key、国内直连稳定）。

- K 线（前复权，支持日/周/月）:
    GET https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get
    ?param=us{AAPL}.{OQ|N|A},{day|week|month},,,{count},qfq
- 实时报价:
    GET https://qt.gtimg.cn/q=usAAPL,usMCD （GBK 编码，~ 分隔）

仅在 Twelve Data 失败或限速时作为降级方案使用。
"""

import time
from datetime import datetime, timedelta

import requests

from utils import safe_float

KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get"
QUOTE_URL = "https://qt.gtimg.cn/q="
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": "https://gu.qq.com/",
}

KLT_MAP = {"1day": "day", "1week": "week", "1month": "month"}
SUFFIXES = (".OQ", ".N", ".A")  # 纳斯达克 / 纽交所 / 美交所
MAX_COUNT = 1000                # 接口 count 上限（1500 会报错）
EXCHANGE_MAP = {"OQ": "NASDAQ", "N": "NYSE", "A": "AMEX"}
INDEX_CODES = {"DJI": "usDJI", "IXIC": "usIXIC", "INX": "usINX"}  # 道指/纳指/标普500


def _tencent_symbol(ticker: str, suffix: str) -> str:
    return f"us{ticker.upper()}{suffix}"


def _output_count(days: int, interval: str) -> int:
    """根据时间范围换算请求条数（不超过接口上限）"""
    if interval == "1week":
        return min(MAX_COUNT, max(60, days // 7 + 10))
    if interval == "1month":
        return min(MAX_COUNT, max(24, days // 30 + 6))
    return min(MAX_COUNT, days)


def _request_kline(param: str, klt: str) -> list:
    """请求一次 K 线接口；网络抖动时最多重试 3 次"""
    for _ in range(3):
        try:
            resp = requests.get(KLINE_URL, params={"param": param},
                                headers=HEADERS, timeout=12)
            data = resp.json().get("data") or {}
            if not data:
                time.sleep(1)
                continue
            inner = data.get(list(data.keys())[0]) or {}
            bars = inner.get(f"qfq{klt}") or inner.get(klt) or []
            return _parse_bars(bars)
        except (requests.RequestException, ValueError):
            time.sleep(1)
    return []


def _parse_bars(bars: list) -> list:
    """腾讯 K 线字段顺序：日期,开,收,高,低,成交量,..."""
    out = []
    for b in bars or []:
        if len(b) < 6:
            continue
        out.append({
            "datetime": str(b[0]),
            "open": safe_float(b[1], 0),
            "close": safe_float(b[2], 0),
            "high": safe_float(b[3], 0),
            "low": safe_float(b[4], 0),
            "volume": safe_float(b[5], 0),
        })
    return out


def _fetch_with_suffix(ticker: str, klt: str, count: int, end: str = ""):
    """依次尝试 .OQ → .N → .A 后缀；返回 (suffix, rows)"""
    for suffix in SUFFIXES:
        param = f"{_tencent_symbol(ticker, suffix)},{klt},,,{count},qfq"
        if end:
            param = f"{_tencent_symbol(ticker, suffix)},{klt},,{end},{count},qfq"
        rows = _request_kline(param, klt)
        # 错误交易所后缀可能返回 1 根实时假数据，少于 5 根视为无效
        if len(rows) >= 5:
            return suffix, rows
        time.sleep(0.4)
    return None, []


def _extend_daily_history(ticker: str, klt: str, suffix: str, rows: list,
                          need: int) -> list:
    """
    日K 超过单次上限时补第二段更早的数据并合并（前复权基准一致）。
    """
    if len(rows) >= need or len(rows) < MAX_COUNT:
        return rows
    try:
        first = rows[0]["datetime"]
        end = (datetime.strptime(first, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
    except ValueError:
        return rows
    param = f"{_tencent_symbol(ticker, suffix)},{klt},,{end},{MAX_COUNT},qfq"
    older = _request_kline(param, klt)
    if not older:
        return rows
    merged = {r["datetime"]: r for r in older}
    merged.update({r["datetime"]: r for r in rows})  # 更新段覆盖旧段
    merged = [merged[k] for k in sorted(merged)]
    # 第二段可能补过头（单次上限 1000 根），只保留最近 need 根
    if len(merged) > need:
        merged = merged[-need:]
    return merged


def get_fallback_time_series(ticker: str, days: int = 365,
                             interval: str = "1day") -> list:
    """
    备用 K 线数据（前复权），返回：
    [{"datetime", "open", "high", "low", "close", "volume"}, ...]
    依次尝试 .OQ → .N → .A 交易所后缀；长周期日K 分两段合并补齐。
    """
    klt = KLT_MAP.get(interval, "day")
    count = _output_count(days, interval)
    suffix, rows = _fetch_with_suffix(ticker, klt, count)
    if not rows:
        raise Exception(f"No fallback data found for {ticker}")
    if interval == "1day" and days > MAX_COUNT:
        rows = _extend_daily_history(ticker, klt, suffix, rows, days)
    return rows


def get_fallback_indices() -> list:
    """
    三大美股指数报价（道琼斯 / 纳斯达克 / 标普500）：
    [{"code", "name", "close", "change", "percent_change"}, ...]
    """
    try:
        resp = requests.get(QUOTE_URL + ",".join(INDEX_CODES.values()),
                            headers=HEADERS, timeout=12)
        resp.encoding = "gbk"
    except requests.RequestException:
        return []
    out = []
    for line in resp.text.strip().split(";"):
        if "=" not in line:
            continue
        fields = line.split("=", 1)[1].strip('"').split("~")
        if len(fields) < 36:
            continue
        out.append({
            "code": fields[2],
            "name": fields[1],
            "close": safe_float(fields[3]),
            "change": safe_float(fields[31]),
            "percent_change": safe_float(fields[32]),
        })
    return out


def get_fallback_quote(ticker: str, hist: list = None) -> dict:
    """
    备用实时报价，返回与 Twelve Data quote 结构兼容的字典。

    hist 可选：用于补 52 周最高价（取最近约一年 K 线的最高价）。
    """
    try:
        resp = requests.get(QUOTE_URL + _tencent_symbol(ticker, ""),
                            headers=HEADERS, timeout=12)
        resp.encoding = "gbk"
        text = resp.text.strip()
        if "=" not in text:
            raise ValueError("empty quote response")
        fields = text.split("=", 1)[1].strip('"').split("~")
        if len(fields) < 36:
            raise ValueError("malformed quote response")
    except (requests.RequestException, ValueError) as e:
        raise Exception(f"No fallback quote for {ticker}: {e}")

    price = safe_float(fields[3])
    prev_close = safe_float(fields[4])
    change = safe_float(fields[31]) if len(fields) > 31 else None
    chg_pct = safe_float(fields[32]) if len(fields) > 32 else None
    if change is None and price is not None and prev_close:
        change = price - prev_close
    if chg_pct is None and prev_close:
        chg_pct = (price / prev_close - 1) * 100 if prev_close else 0

    code = fields[2]
    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    exchange = EXCHANGE_MAP.get(suffix, "US")

    # 估值字段（实测确认）：[39]=PE(TTM)、[44]=市值(亿)、[37]=成交额、[38]=换手率%
    pe = safe_float(fields[39]) if len(fields) > 39 else None
    market_cap = None
    if len(fields) > 44 and safe_float(fields[44]) is not None:
        market_cap = safe_float(fields[44]) * 1e8
    amount = safe_float(fields[37]) if len(fields) > 37 else None
    turnover = safe_float(fields[38]) if len(fields) > 38 else None

    high52 = low52 = None
    if hist:
        highs = [safe_float(h.get("high")) for h in hist if safe_float(h.get("high"))]
        lows = [safe_float(h.get("low")) for h in hist if safe_float(h.get("low"))]
        if highs:
            high52 = max(highs[-252:])
        if lows:
            low52 = min(lows[-252:])

    return {
        "symbol": ticker.upper(),
        "name": ticker.upper(),
        "exchange": exchange,
        "currency": fields[35] if len(fields) > 35 else "USD",
        "close": price,
        "change": change,
        "percent_change": chg_pct,
        "fifty_two_week": {"high": high52, "low": low52},
        "pe_ratio": pe,
        "market_cap": market_cap,
        "amount": amount,
        "turnover": turnover,
    }
