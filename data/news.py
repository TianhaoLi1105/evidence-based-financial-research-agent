"""
News Module (V3.4.2)
====================
公司新闻：东财新闻搜索（免费、国内可达）→ Google News RSS 兜底（海外可用）。
缓存 1 小时。返回 [{title, date, source, url, snippet}]。

设计原则（沿用项目哲学）：
- 接口失败静默降级，不抛异常（返回空列表 + source="none"）
- 情绪打分由 LLM 完成（工具只提供标题/日期/来源/摘要，不编造观点）
"""

import json as _json
import os
import time
import urllib.parse
import urllib.request

HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36")}
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         ".cache")
CACHE_TTL = 3600          # 新闻缓存 1 小时（时效性高于财务数据）

EM_URL = ("https://search-api-web.eastmoney.com/search/jsonp"
          "?cb=cb&param={param}")
GOOGLE_URL = ("https://news.google.com/rss/search"
              "?q={query}&hl=en-US&gl=US&ceid=US:en")


def _norm_time(s: str) -> str:
    """统一时间格式为 YYYY-MM-DD HH:MM"""
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt is None:
            return str(s)[:16]
        return dt.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError):
        return str(s)[:16]


def _em_request(ticker: str, limit: int) -> list:
    """东财新闻搜索（关键词=股票代码）"""
    param = {"uid": "", "keyword": ticker, "type": ["cmsArticleWebOld"],
             "client": "web", "clientType": "web", "clientVersion": "curr",
             "param": {"cmsArticleWebOld": {
                 "searchScope": "default", "sort": "default",
                 "pageIndex": 1, "pageSize": min(limit, 20),
                 "preTag": "", "postTag": ""}}}
    url = EM_URL.format(param=urllib.parse.quote(
        _json.dumps(param, ensure_ascii=False)))
    req = urllib.request.Request(url, headers={**HEADERS,
                                               "Referer": "https://so.eastmoney.com/"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    body = raw[raw.find("(") + 1: raw.rfind(")")] if raw.startswith("cb(") else raw
    data = _json.loads(body)
    items = (data.get("result") or {}).get("cmsArticleWebOld") or []
    out = []
    for it in items[:limit]:
        out.append({
            "title": (it.get("title") or "").strip() or None,
            "date": _norm_time(it.get("date")),
            "source": it.get("mediaName"),
            "url": it.get("url"),
            "snippet": (it.get("content") or "").strip()[:200] or None,
        })
    return [x for x in out if x["title"]]


def _google_request(ticker: str, limit: int) -> list:
    """Google News RSS（英文新闻，海外可用；国内可能超时自动跳过）"""
    import xml.etree.ElementTree as ET
    query = urllib.parse.quote(f"{ticker} stock")
    url = GOOGLE_URL.format(query=query)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    root = ET.fromstring(raw)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        src_el = item.find("source")
        src = (src_el.text or "").strip() if src_el is not None else None
        if src and title.endswith(f" - {src}"):
            title = title[: -(len(src) + 3)]
        out.append({
            "title": title or None,
            "date": _norm_time(item.findtext("pubDate")),
            "source": src,
            "url": item.findtext("link"),
            "snippet": None,
        })
        if len(out) >= limit:
            break
    return [x for x in out if x["title"]]


def _cache_path(ticker: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = "".join(c for c in str(ticker).upper() if c.isalnum()) or "TICKER"
    return os.path.join(CACHE_DIR, f"news_{safe}.json")


def _cache_get(ticker: str):
    try:
        with open(_cache_path(ticker)) as f:
            d = _json.load(f)
        if time.time() - d.get("ts", 0) <= CACHE_TTL and isinstance(d.get("value"), dict):
            return d["value"]
    except (FileNotFoundError, OSError, ValueError):
        pass
    return None


def _cache_set(ticker: str, value: dict) -> None:
    try:
        path = _cache_path(ticker)
        with open(f"{path}.tmp", "w") as f:
            _json.dump({"ts": time.time(), "value": value}, f)
        os.replace(f"{path}.tmp", path)
    except OSError:
        pass


def get_news(ticker: str, limit: int = 8) -> dict:
    """获取公司新闻（缓存 → 东财 → Google News → 空），永不抛异常"""
    tk = str(ticker).upper()
    cached = _cache_get(tk)
    if cached is not None:
        return cached

    for fetcher, source in ((_em_request, "eastmoney"),
                            (_google_request, "google-news")):
        try:
            items = fetcher(tk, limit)
        except Exception:
            continue
        if items:
            result = {"symbol": tk, "count": len(items), "source": source,
                      "items": items}
            _cache_set(tk, result)
            return result
    return {"symbol": tk, "count": 0, "source": "none", "items": []}
