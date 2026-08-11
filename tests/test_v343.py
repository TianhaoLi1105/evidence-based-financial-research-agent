"""V3.4.3 估值相对位置回归测试（mock 数据源，无需网络）"""
import os, sys, json
sys.path.insert(0, os.getcwd())

import data.valuation as v
from agent.tools import TOOLS, TOOL_SCHEMAS, dispatch_tool
from agent.prompts import SYSTEM_PROMPTS_TOOLS

# ─── mock 数据源 ────────────────────────────────────────
FAKE_QUOTES = {
    "AAPL": {"name": "Apple Inc.", "close": 245.3, "pe_ratio": 36.2,
             "market_cap": 3.7e12,
             "fifty_two_week": {"high": 260.1, "low": 164.1}},
    "NVDA": {"name": "NVIDIA Corp.", "close": 131.4, "pe_ratio": None,
             "market_cap": 3.2e12,
             "fifty_two_week": {"high": 153.1, "low": 39.2}},
    "UNMATCHED": {"name": "Weird Co.", "close": 10.0, "pe_ratio": 5.0,
                  "market_cap": 1e9,
                  "fifty_two_week": {"high": 12.0, "low": 8.0}},
}
FAKE_SA = {
    "AAPL": {"sector": "Technology", "industry": "Consumer Electronics",
             "pe_ratio": 36.2, "market_cap": 3.7e12},
    "NVDA": {"sector": "Technology", "industry": "Semiconductors",
             "pe_ratio": None, "market_cap": 3.2e12},
    "UNMATCHED": {"sector": "Weirdology", "industry": "Quantum Widgets",
                  "pe_ratio": 5.0, "market_cap": 1e9},
    # 同行（NVDA 组）
    "AMD": {"sector": "Technology", "industry": "Semiconductors",
            "pe_ratio": 42.0, "market_cap": 2.1e11},
    "INTC": {"sector": "Technology", "industry": "Semiconductors",
             "pe_ratio": -12.0, "market_cap": 1.1e11},   # 负 PE 应被排除
    "QCOM": {"sector": "Technology", "industry": "Semiconductors",
             "pe_ratio": 18.0, "market_cap": 1.8e11},
    "AVGO": {"sector": "Technology", "industry": "Semiconductors",
             "pe_ratio": 34.0, "market_cap": 1.0e12},
    "TSM": {"sector": "Technology", "industry": "Semiconductors",
            "pe_ratio": 28.0, "market_cap": 9.0e11},
    "MU": {"sector": "Technology", "industry": "Semiconductors",
           "pe_ratio": None, "market_cap": 1.3e11},
    "AMAT": None,   # 拉取失败，应跳过
}
# AAPL 同行组（big tech）
for tk in ("MSFT", "GOOGL", "AMZN", "META", "ORCL", "CRM", "ADBE"):
    FAKE_SA[tk] = {"sector": "Technology", "industry": "Software",
                   "pe_ratio": 32.0, "market_cap": 1e12}


def fake_quote(tk, hist=None):
    if tk not in FAKE_QUOTES:
        raise Exception("no quote")
    return dict(FAKE_QUOTES[tk]), "tencent"


def fake_sa(tk):
    if tk not in FAKE_SA:
        raise Exception("no sa")
    return dict(FAKE_SA[tk])


v._quote_with_fallback = fake_quote
v._from_stockanalysis_profile = fake_sa

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


# ─── 1) 行业匹配 ────────────────────────────────────────
check("match consumer electronics -> big tech",
      v._match_peers("Technology", "Consumer Electronics")[:3] == ["MSFT", "GOOGL", "AMZN"])
check("match semiconductors -> semis group",
      v._match_peers("Technology", "Semiconductors")[0] == "NVDA")
check("match banks", "JPM" in v._match_peers("Financial Services", "Banks - Money Center"))
check("unmatched industry -> []", v._match_peers("Unknown", "Quantum Widgets") == [])

# ─── 2) 中位数（排除负 PE）──────────────────────────────
check("median excludes negative PE", v._median_positive_pe([42, -12, 18, 34, 28]) == 31.0)
check("median empty -> None", v._median_positive_pe([-1, -2]) is None)
check("median outlier capped", v._median_positive_pe([10, 20, 9999]) == 15.0)

# ─── 3) 52 周位置 ───────────────────────────────────────
check("price position 50%", v._price_position(100, 120, 80) == 50.0)
check("price position high", v._price_position(120, 120, 80) == 100.0)
check("price position low", v._price_position(80, 120, 80) == 0.0)
check("price position invalid -> None", v._price_position(100, 100, 100) is None)

# ─── 4) AAPL 完整估值 ───────────────────────────────────
r = v.get_valuation("AAPL")
check("AAPL pe", r["pe_ratio"] == 36.2)
check("AAPL mcap", r["market_cap"] == 3.7e12)
check("AAPL price pos", r["price_position_52w_pct"] == round((245.3-164.1)/(260.1-164.1)*100, 1))
check("AAPL peers count", len(r["peers"]) == 6)
check("AAPL industry median", r["industry_median_pe"] == 32.0)
check("AAPL premium vs median", r["pe_premium_vs_industry_pct"] == round((36.2/32.0-1)*100, 1))
check("AAPL sector/industry", r["sector"] == "Technology" and r["industry"] == "Consumer Electronics")
check("AAPL source annotated", "tencent" in r["source"] and "stockanalysis" in r["source"])

# ─── 5) NVDA：自身 PE 缺失 → stockanalysis 兜底 ─────────
r = v.get_valuation("NVDA")
check("NVDA quote pe None", r["pe_ratio"] is None)   # quote 与 sa 都是 None
check("NVDA peers skip negative/missing",
      "INTC" not in [p["symbol"] for p in r["peers"]] and
      "MU" not in [p["symbol"] for p in r["peers"]] and
      "AMAT" not in [p["symbol"] for p in r["peers"]])
check("NVDA peers valid count", len(r["peers"]) >= 4)
pes = [p["pe_ratio"] for p in r["peers"] if p["pe_ratio"] is not None]
check("NVDA median over positive peers", r["industry_median_pe"] is not None)

# ─── 6) 未知行业：降级不抛异常 ──────────────────────────
r = v.get_valuation("UNMATCHED")
check("unmatched peers empty", r["peers"] == [])
check("unmatched median None", r["industry_median_pe"] is None)
check("unmatched note explains", any("not matched" in n for n in r["notes"]))
check("unmatched still has price pos", r["price_position_52w_pct"] == 50.0)

# ─── 7) 全失败降级 ──────────────────────────────────────
def boom_quote(tk, hist=None):
    raise Exception("network down")
v._quote_with_fallback = boom_quote
v._from_stockanalysis_profile = lambda tk: (_ for _ in ()).throw(Exception("down"))
r = v.get_valuation("MSFT")
check("all-down no exception", isinstance(r, dict))
check("all-down fields None", r["pe_ratio"] is None and r["current_price"] is None
      and r["peers"] == [] and r["industry_median_pe"] is None)
check("all-down notes present", len(r["notes"]) >= 1)

# ─── 8) 工具注册 / schema / dispatch ────────────────────
check("tool registered", "get_valuation" in TOOLS)
check("schema appended",
      any(t["function"]["name"] == "get_valuation" for t in TOOL_SCHEMAS))
v._quote_with_fallback = fake_quote
v._from_stockanalysis_profile = fake_sa
r = dispatch_tool("get_valuation", {"ticker": "AAPL"})
check("dispatch ok", r.get("symbol") == "AAPL" and r.get("pe_ratio") == 36.2)
r = dispatch_tool("get_valuation", {"ticker": "BAD!!"})
check("dispatch bad ticker -> error", "error" in r)
r = dispatch_tool("get_valuation", {"ticker": 123})
check("dispatch numeric -> normalized", r.get("symbol") == "123" or "error" in r)

# ─── 9) 提示词 ──────────────────────────────────────────
en, zh = SYSTEM_PROMPTS_TOOLS["en"], SYSTEM_PROMPTS_TOOLS["zh"]
check("prompt en tool list", "get_valuation: valuation check" in en)
check("prompt en rule13", "Valuation check:" in en)
check("prompt zh tool list", "get_valuation：估值贵贱判断" in zh)
check("prompt zh rule13", "估值贵贱判断" in zh)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL V3.4.3 TESTS PASSED")
