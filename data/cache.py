"""
Disk Cache Module
==================
K 线数据本地缓存：命中缓存时不再请求任何 API，
免费 Key（限速 8 次/分钟）也能流畅地反复分析。

TTL：日K 1 小时；周K / 月K 24 小时。
写入采用「临时文件 + 原子替换」，避免并发读写损坏。
"""

import json
import os
import time

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache")
TTL = {"1day": 3600, "1week": 86400, "1month": 86400}


def _cache_path(ticker: str, interval: str, period_days: int) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = "".join(c for c in ticker.upper() if c.isalnum()) or "TICKER"
    return os.path.join(CACHE_DIR, f"{safe}_{interval}_{period_days}.json")


def get_cached_time_series(ticker: str, interval: str, period_days: int) -> list:
    """读取未过期的缓存 K 线；无缓存或过期返回 None"""
    try:
        with open(_cache_path(ticker, interval, period_days)) as f:
            data = json.load(f)
        age = time.time() - data.get("ts", 0)
        if age > TTL.get(interval, 3600):
            return None
        return data.get("rows")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def set_cached_time_series(ticker: str, interval: str, period_days: int,
                           rows: list) -> None:
    """写入缓存（原子替换）"""
    if not rows:
        return
    path = _cache_path(ticker, interval, period_days)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"ts": time.time(), "rows": rows}, f)
        os.replace(tmp, path)
    except OSError:
        pass
