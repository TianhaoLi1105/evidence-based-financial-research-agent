"""
User Preference Memory (V3.3.3)
================================
个性化记忆：隐式学习用户行为，建立轻量档案，注入 AI 上下文。

档案内容（全部本地存储，不联网）：
- stocks：分析过 / 对比过 / 在 AI 里问过的股票 → 频率 + 最近时间
- topics：提问话题分类（技术面 / 基本面 / 行情速览）→ 各维度计数

设计要点：
- 计数封顶（单只股票最多 999 次），避免长期使用后数值膨胀
- 写 .agent_config.json 的 preferences 字段（复用 storage 原子合并写入）
- 分类可多标签命中（如「RSI 和 PE 哪个更有用」同时记技术面 + 基本面）
"""

import re
import time

from data.storage import load_config, save_config

MAX_COUNT = 999       # 单只股票计数上限（防止膨胀）
TOP_N = 5             # 注入/展示时取最常看的股票数
KEY = "preferences"   # .agent_config.json 里的字段名

# ─── 话题分类规则（可多标签命中）──────────────────────────
_TECH_RE = re.compile(
    r"(rsi|macd|kdj|boll|布林|均线|ma\d|ema|技术|k线|k线图|蜡烛|指标|超买|超卖"
    r"|金叉|死叉|成交量|volume|trend|momentum|支撑|压力|背离|形态)",
    re.I)
_FUND_RE = re.compile(
    r"(pe|市盈|估值|营收|利润|eps|roe|负债|现金流|毛利|净利|margin|财务|基本面"
    r"|dividend|股息|beta|市值|market cap|revenue|earnings|资产|净资产收益率)",
    re.I)
_PRICE_RE = re.compile(
    r"(价格|行情|股价|涨跌|走势|现价|quote|price|涨了|跌了|多少钱|成本|高点|低点)",
    re.I)

TOPICS = ("technical", "fundamental", "price")


def _topics_of(text: str) -> list:
    """把一句话分类到 0~3 个话题维度"""
    out = []
    if _TECH_RE.search(text or ""):
        out.append("technical")
    if _FUND_RE.search(text or ""):
        out.append("fundamental")
    if _PRICE_RE.search(text or ""):
        out.append("price")
    return out


def _prefs() -> dict:
    p = load_config().get(KEY) or {}
    if not isinstance(p, dict):
        p = {}
    p.setdefault("stocks", {})
    p.setdefault("topics", {})
    p.setdefault("updated_at", 0)
    return p


def record_stock(ticker: str) -> None:
    """记录一次股票活动（分析 / 对比 / AI 提问）"""
    tk = str(ticker or "").strip().upper()
    if not tk:
        return
    p = _prefs()
    cur = p["stocks"].get(tk) or {}
    p["stocks"][tk] = {
        "n": min(int(cur.get("n", 0)) + 1, MAX_COUNT),
        "last": time.time(),
    }
    p["updated_at"] = time.time()
    save_config({KEY: p})


def record_question(text: str) -> None:
    """记录一次 AI 提问的话题分类（可多标签）"""
    if not text or not text.strip():
        return
    p = _prefs()
    for topic in _topics_of(text):
        p["topics"][topic] = min(int(p["topics"].get(topic, 0)) + 1, MAX_COUNT)
    p["updated_at"] = time.time()
    save_config({KEY: p})


def top_stocks(n: int = TOP_N) -> list:
    """按「频率 + 最近活跃」排序返回最常看的股票（频率优先，其次最近时间）"""
    stocks = _prefs()["stocks"]
    items = [(tk, d.get("n", 0), d.get("last", 0)) for tk, d in stocks.items()]
    items.sort(key=lambda x: (-x[1], -x[2]))
    return [tk for tk, _, _ in items[:n]]


def topic_counts() -> dict:
    """返回各话题维度计数（0 也包含，便于展示）"""
    counts = dict(_prefs()["topics"])
    for tp in TOPICS:
        counts.setdefault(tp, 0)
    return counts


def top_topics(n: int = 2) -> list:
    """按计数排序返回前 n 个话题维度"""
    counts = sorted(topic_counts().items(), key=lambda x: -x[1])
    return [tp for tp, c in counts if c > 0][:n]


def get_deep_review() -> bool:
    """分析师→风控二次审阅开关（V3.4.4）"""
    return bool(_prefs().get("deep_review", False))


def set_deep_review(v: bool) -> None:
    """写入开关（本地记忆）"""
    p = _prefs()
    p["deep_review"] = bool(v)
    p["updated_at"] = time.time()
    save_config({KEY: p})


def has_profile() -> bool:
    p = _prefs()
    return bool(p["stocks"]) or any(v > 0 for v in p["topics"].values())


def clear() -> None:
    """清空个性化档案（设置弹窗里的一键清除）"""
    save_config({KEY: {"stocks": {}, "topics": {}, "updated_at": time.time()}})
