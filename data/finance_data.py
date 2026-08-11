"""
Financial Data Module
=====================
数据层：封装 Twelve Data API 调用。
免费注册: https://twelvedata.com/apikey (800 calls/day)
"""

import urllib.request
import urllib.error
import json as _json

API_KEY = "demo"
BASE_URL = "https://api.twelvedata.com"


def set_api_key(key: str):
    """全局设置 API Key"""
    global API_KEY
    API_KEY = key


def _request(endpoint: str, params: dict = None) -> dict:
    """发送 API 请求并解析 JSON 响应"""
    if params is None:
        params = {}
    params["apikey"] = API_KEY
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE_URL}/{endpoint}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return _json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        msg = ""
        try:
            j = _json.loads(body)
            msg = j.get("message", "")
        except Exception:
            msg = body[:150]
        if msg:
            raise Exception(f"Error {e.code}: {msg}")
        else:
            raise Exception(f"Error {e.code}")
    except urllib.error.URLError as e:
        raise Exception("Network Error")


def get_quote(ticker: str) -> dict:
    """获取实时报价（股价、涨跌幅、52周高低等）"""
    data = _request("quote", {"symbol": ticker})
    if "code" in data and data["code"] != ticker:
        raise Exception(data.get("message", "Unknown error"))
    return data


def get_statistics(ticker: str) -> dict:
    """获取财务指标（市值、PE、营收等，需 Pro 套餐）"""
    data = _request("statistics", {"symbol": ticker})
    if "code" in data and data["code"] != ticker:
        raise Exception(data.get("message", "Unknown error"))
    return data.get("statistics", {})



def get_batch_quotes(tickers: list) -> dict:
    """
    批量获取多只股票报价，返回 {symbol: quote_dict}。

    真实 API Key 支持一次请求多只（省调用次数）；
    demo Key 不支持批量时自动降级为逐个查询。
    """
    if not tickers:
        return {}
    try:
        data = _request("quote", {"symbol": ",".join(tickers)})
    except Exception:
        data = {"status": "error"}

    if data.get("status") == "ok" and "data" in data:
        return data["data"]

    # 降级：逐个查询（demo Key 场景）
    result = {}
    for tk in tickers:
        try:
            result[tk] = get_quote(tk)
        except Exception:
            pass
    return result

def get_profile(ticker: str) -> dict:
    """获取公司基本面（简介、行业、CEO、员工数等）"""
    data = _request("profile", {"symbol": ticker})
    if "code" in data and data["code"] != ticker:
        raise Exception(data.get("message", "Unknown error"))
    return data


def get_time_series(ticker: str, days: int = 365, interval: str = "1day") -> list:
    """获取历史股价数据（OHLCV），返回 values 列表。

    interval 支持: "1day" / "1week" / "1month"
    """
    data = _request("time_series", {
        "symbol": ticker,
        "interval": interval,
        "outputsize": days,
    })
    if "code" in data and data["code"] != ticker:
        if isinstance(data["code"], int):
            raise Exception(data.get("message", "Unknown error"))
        else:
            raise Exception(data.get("message", "No data found"))
    if "values" not in data:
        raise Exception(f"No time series data found for {ticker}")
    return data["values"]
