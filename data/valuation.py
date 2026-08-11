"""
Valuation Module (V3.4.3)
=========================
估值相对位置：判断一只股票「贵不贵」，给出有依据的结论。

实现两个免费数据能力：
1. 自身估值：当前价、PE、市值、52 周高低（腾讯报价 → stockanalysis 兜底）
2. 同行对比：按行业/板块关键词映射出同行大盘股，拉取同行 PE/市值，
   计算行业中位数 PE，得到「PE 相对行业中位数溢价」

设计原则（沿用项目哲学）：
- 接口失败静默降级，字段允许 None，不编造
- 历史 PE 分位（52 周 PE 区间）免费源拿不到 → 用「52 周价格位置 + 同行 PE 中位数」
  两个可验证维度替代，并在 notes 里如实说明
- 同行映射是静态字典（覆盖主流行业），匹配不到的行业如实返回空 peers
"""

import statistics as _stat

from utils import safe_float
from services.stock_service import _quote_with_fallback
from data.fundamentals import _from_stockanalysis_profile

# ─── 行业 → 同行大盘股映射 ───────────────────────────────
# 顺序敏感：先命中先使用（semiconductor 必须排在 technology 之前）。
# 每行业 6-8 只，市值靠前、数据可得性高。目标股票自身会被自动剔除。

SECTOR_PEERS = [
    (("semiconductor", "chip", "semis"),
     ["NVDA", "AMD", "INTC", "QCOM", "AVGO", "TSM", "MU", "AMAT"]),
    (("software", "internet", "technology", "consumer electronics",
      "communication equipment", "information technology"),
     ["MSFT", "GOOGL", "AMZN", "META", "AAPL", "ORCL", "CRM", "ADBE"]),
    (("banks", "banking", "asset management", "capital markets", "financial"),
     ["JPM", "BAC", "WFC", "C", "GS", "MS", "UBS", "HSBC"]),
    (("insurance", "reinsurance"),
     ["PGR", "ALL", "MET", "PRU", "AIG", "CB", "TRV", "ACGL"]),
    (("pharmaceutical", "biotechnology", "biotech", "drug manufacturers"),
     ["JNJ", "PFE", "MRK", "ABBV", "LLY", "AMGN", "GILD", "BMY"]),
    (("healthcare plans", "medical care", "healthcare services", "health care"),
     ["UNH", "CVS", "HUM", "CI", "ELV", "CNC", "MOH"]),
    (("oil & gas", "petroleum", "energy", "exploration", "refining"),
     ["XOM", "CVX", "SHEL", "BP", "TTE", "COP", "EQT", "SLB"]),
    (("retail", "discount stores", "specialty retail", "apparel", "footwear"),
     ["WMT", "COST", "TGT", "HD", "LOW", "TJX", "NKE", "LULU"]),
    (("packaged foods", "beverages", "household", "consumer staples",
      "personal care"),
     ["KO", "PEP", "PG", "PM", "MO", "CL", "GIS", "KMB"]),
    (("auto manufacturers", "automobiles", "automotive", "auto"),
     ["TSLA", "TM", "VWAGY", "BMWYY", "F", "GM", "HMC", "STLA"]),
    (("telecom", "wireless", "communication services"),
     ["T", "VZ", "TMUS", "CMCSA", "CHTR", "AMX"]),
    (("entertainment", "media", "content"),
     ["DIS", "NFLX", "WBD", "PARA", "LYV", "SPOT", "FOXA"]),
    (("airlines", "airline"),
     ["DAL", "UAL", "AAL", "LUV", "ALK", "CPA"]),
    (("aerospace", "defense"),
     ["BA", "LMT", "RTX", "NOC", "GD", "GE", "HON", "TXT"]),
    (("industrial", "machinery", "manufacturing", "conglomerate"),
     ["GE", "HON", "CAT", "DE", "EMR", "ETN", "ITW", "MMM"]),
    (("utilities", "electric", "gas utility", "regulated"),
     ["NEE", "DUK", "SO", "AEP", "D", "EXC", "SRE", "ED"]),
    (("reit", "real estate"),
     ["PLD", "AMT", "EQIX", "SPG", "O", "PSA", "WELL", "DLR"]),
    (("metals", "mining", "steel", "gold"),
     ["BHP", "RIO", "VALE", "FCX", "NEM", "NUE", "CLF", "AA"]),
    (("restaurants", "food service", "dining"),
     ["MCD", "SBUX", "CMG", "YUM", "QSR", "DRI"]),
    (("alcoholic", "tobacco", "consumer packaged goods", "beverages - non"),
     ["KO", "PEP", "STZ", "DEO", "BTI", "MO"]),
]

MAX_PEERS = 6      # 最多纳入对比的同行数量
PEER_PE_HI = 300   # 排除异常 PE（数据错乱 / 微利股），避免污染中位数


def _match_peers(sector: str, industry: str) -> list:
    """按行业/板块关键词匹配同行列表；匹配不到返回空列表"""
    hay = f"{sector or ''} {industry or ''}".lower()
    for keywords, peers in SECTOR_PEERS:
        if any(k in hay for k in keywords):
            return list(peers)
    return []


def _median_positive_pe(values: list):
    """同行 PE 中位数：只统计正 PE（负值=亏损股会扭曲中位数）"""
    pos = [v for v in values if v is not None and v > 0 and v <= PEER_PE_HI]
    if not pos:
        return None
    return round(_stat.median(pos), 2)


def _f52(d: dict):
    """提取 52 周高低（quote 里的 fifty_two_week 可能是 dict）"""
    r = d.get("fifty_two_week") or {}
    if isinstance(r, dict):
        return safe_float(r.get("high")), safe_float(r.get("low"))
    return None, None


def _price_position(price, h52, l52) -> float:
    """当前价在 52 周高低区间中的位置（0-100%）"""
    if price is None or h52 is None or l52 is None or h52 <= l52:
        return None
    return round((price - l52) / (h52 - l52) * 100, 1)


def _peer_row(p: str) -> dict:
    """拉取单只同行的 PE/市值（stockanalysis，24h 缓存）。

    只保留正 PE 的同行：亏损股 / PE 缺失股会污染估值对比口径。
    """
    try:
        ps = _from_stockanalysis_profile(p)
    except Exception:
        return None
    ppe = safe_float(ps.get("pe_ratio"))
    pmc = safe_float(ps.get("market_cap"))
    if ppe is None or ppe <= 0:
        return None
    return {"symbol": p, "pe_ratio": ppe, "market_cap": pmc}


def get_valuation(ticker: str) -> dict:
    """
    估值相对位置：自身估值 + 52 周价格位置 + 同行 PE 对比。
    永不抛异常；字段缺失返回 None，notes 说明原因。
    """
    tk = str(ticker).upper()

    # 1) 自身报价（腾讯 → Twelve Data；52 周高低来自 K 线或接口）
    quote, qsrc = {}, None
    try:
        quote, qsrc = _quote_with_fallback(tk)
    except Exception:
        pass

    # 2) stockanalysis 概况：行业/板块/市值/PE（免费无 Key，24h 缓存）
    sa = {}
    try:
        sa = _from_stockanalysis_profile(tk)
    except Exception:
        pass

    price = safe_float(quote.get("close"))
    h52, l52 = _f52(quote)
    pe = safe_float(quote.get("pe_ratio"))
    if pe is None:
        pe = safe_float(sa.get("pe_ratio"))
    mcap = safe_float(quote.get("market_cap"))
    if mcap is None:
        mcap = safe_float(sa.get("market_cap"))
    name = quote.get("name") or sa.get("name") or tk

    sector = sa.get("sector")
    industry = sa.get("industry")

    # 3) 同行对比
    peers = [p for p in _match_peers(sector, industry) if p != tk]
    peer_rows, peer_pes = [], []
    for p in peers[:MAX_PEERS + 2]:          # 多取两个留冗余
        row = _peer_row(p)
        if row is None:
            continue
        peer_rows.append(row)
        if row["pe_ratio"] is not None and row["pe_ratio"] > 0:
            peer_pes.append(row["pe_ratio"])
        if len(peer_rows) >= MAX_PEERS:
            break
    peer_rows = peer_rows[:MAX_PEERS]

    median_pe = _median_positive_pe(peer_pes)
    pe_premium = None
    if pe is not None and pe > 0 and median_pe:
        pe_premium = round((pe / median_pe - 1) * 100, 1)

    notes = []
    if not peers:
        notes.append("industry not matched in peer mapping; peer comparison unavailable")
    elif not peer_rows:
        notes.append("peer valuation data unavailable (free source limits)")
    if pe is None:
        notes.append("P/E unavailable from current free sources")
    if h52 is None or l52 is None:
        notes.append("52-week range unavailable; price position not computed")
    notes.append("historical P/E percentile is not available on free sources; "
                 "use P/E vs industry median plus 52-week price position as proxies")

    sources = [s for s in (qsrc, "stockanalysis", "computed-locally") if s]
    return {
        "symbol": tk,
        "name": name,
        "sector": sector,
        "industry": industry,
        "current_price": price,
        "pe_ratio": pe,
        "market_cap": mcap,
        "fifty_two_week_high": h52,
        "fifty_two_week_low": l52,
        "price_position_52w_pct": _price_position(price, h52, l52),
        "industry_median_pe": median_pe,
        "pe_premium_vs_industry_pct": pe_premium,
        "peers": peer_rows,
        "source": ", ".join(sources),
        "notes": notes,
    }
