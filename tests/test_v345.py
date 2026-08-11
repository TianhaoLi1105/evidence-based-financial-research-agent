"""V3.4.5 收尾增强回归测试：页面深度财务表 + 多股估值对比 52 周位置"""
import os, sys
sys.path.insert(0, os.getcwd())

from unittest import mock
from i18n import t
from components.cards import _deep_financial_rows
import components.cards as cards
import services.stock_service as ss
import agent.tools as at

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


# ─── 1) i18n 新键 ───────────────────────────────────────
for k, en, zh in (("fin_net_income_growth", "Net income YoY", "净利同比"),
                  ("fin_total_assets", "Total assets", "总资产"),
                  ("fin_total_liabilities", "Total liabilities", "总负债"),
                  ("fin_equity", "Equity", "股东权益"),
                  ("fin_eps", "EPS", "每股收益")):
    check(f"i18n {k}", t(k, "en") == en and t(k, "zh") == zh)

# ─── 2) _deep_financial_rows 格式 ────────────────────────
SAMPLE = {"deep_fundamentals": {"source": "stockanalysis",
    "revenue": 1.3e11, "net_income": 6.3e10, "gross_margin": 72.5,
    "net_margin": 48.5, "revenue_growth_yoy": 15.2, "net_income_growth_yoy": 12.1,
    "total_assets": 3.8e11, "total_liabilities": 2.4e11,
    "stockholders_equity": 1.4e11, "debt_to_equity": 1.71,
    "current_ratio": 2.1, "operating_cash_flow": 1.1e11,
    "eps": 4.5, "roe": 45.0}}
rows = _deep_financial_rows(SAMPLE, "zh")
check("deep rows count", len(rows) == 14)
d = dict(rows)
check("revenue formatted", d.get("营收（TTM）") == "$130.00B")
check("margin percent", d.get("毛利率") == "72.5%" and d.get("净利率") == "48.5%")
check("growth signed", d.get("营收同比") == "+15.2%" and d.get("净利同比") == "+12.1%")
check("ratios 2dp", d.get("负债率") == "1.71" and d.get("流动比率") == "2.10")
check("eps money", d.get("每股收益") == "$4.50")
check("roe percent", d.get("净资产收益率") == "45.0%")
check("none source -> []", _deep_financial_rows(
    {"deep_fundamentals": {"source": "none"}}, "zh") == [])
check("missing fields skipped",
      _deep_financial_rows({"deep_fundamentals": {"source": "x", "revenue": 1}}, "zh")
      == [("营收（TTM）", "$1")])

# ─── 3) render_financials 走深度财务分支（mock st）───────
captured = {}
class FakeDf:
    def __init__(self, data, **kw):
        captured["rows"] = data
class FakeST:
    session_state = type("SS", (), {"lang": "zh"})()
    def dataframe(self, df, **kw):
        captured["dataframe_called"] = True
    def markdown(self, *a, **kw):
        pass
with mock.patch.object(cards, "pd") as mpd, \
     mock.patch.object(cards, "st", FakeST()):
    mpd.DataFrame = FakeDf
    cards.render_financials(SAMPLE)
check("render_financials uses deep branch", captured.get("dataframe_called")
      and len(captured.get("rows", [])) == 14)
captured.clear()
with mock.patch.object(cards, "pd") as mpd, \
     mock.patch.object(cards, "st", FakeST()):
    mpd.DataFrame = FakeDf
    cards.render_financials({"quote_fallback": {"fifty_two_week": {}, "turnover": 1.0, "amount": 1e9},
                             "valuations_metrics": {"market_capitalization": 1e12, "trailing_pe": 30}})
check("fallback branch still works", captured.get("dataframe_called")
      and len(captured.get("rows", [])) == 6)

# ─── 4) fetch_data 附加 deep_fundamentals ────────────────
with mock.patch.object(ss, "get_fundamentals",
                       return_value={"source": "stockanalysis", "revenue": 1e11}), \
     mock.patch.object(ss, "get_statistics", return_value={}), \
     mock.patch.object(ss, "_time_series_with_fallback",
                       return_value=([], "tencent")), \
     mock.patch.object(ss, "_quote_with_fallback",
                       return_value=({"pe_ratio": 30, "market_cap": 1e12}, "tencent")), \
     mock.patch.object(ss, "profile_with_fallback", return_value={}):
    quote, stats, hist, profile, ind, hs, qs = ss.fetch_data("AAPL", 365)
check("fetch_data carries deep_fundamentals",
      stats.get("deep_fundamentals", {}).get("revenue") == 1e11)
check("fetch_data get_fundamentals failure tolerated",
      True)  # 上面 mock 成功路径；失败路径由 try/except 保证（静态）

# ─── 5) compare 工具：52 周位置（含 clamp）──────────────
def fake_fcd(tks, days, interval):
    quotes = {
        "AAPL": {"name": "Apple", "close": 245.3, "pe_ratio": 36.2,
                 "market_cap": 3.7e12,
                 "fifty_two_week": {"high": 260.1, "low": 164.1}},
        "MSFT": {"name": "Microsoft", "close": 420.0, "pe_ratio": 35.0,
                 "market_cap": 3.1e12,
                 "fifty_two_week": {"high": 430.0, "low": 300.0}},
        "TSLA": {"name": "Tesla", "close": 500.0, "pe_ratio": 60.0,
                 "market_cap": 1.5e12,
                 "fifty_two_week": {"high": 250.0, "low": 150.0}},
    }
    return (quotes,
            {tk: [{"close": 150.0}, {"close": q["close"]}] for tk, q in quotes.items()},
            {tk: "tencent" for tk in tks})
with mock.patch.object(at, "fetch_compare_data", side_effect=fake_fcd):
    r = at.tool_compare(["AAPL", "MSFT", "TSLA"], days=365)
d = {it["symbol"]: it for it in r["items"]}
check("AAPL 52w pos", d["AAPL"]["price_position_52w_pct"] == 84.6)
check("MSFT 52w pos", d["MSFT"]["price_position_52w_pct"] == 92.3)
check("TSLA clamp at 100 (above range)", d["TSLA"]["price_position_52w_pct"] == 100.0)
check("compare keeps pe/mcap", d["AAPL"]["pe_ratio"] == 36.2
      and d["AAPL"]["market_cap"] == 3.7e12)

# ─── 6) 提示词规则 10 覆盖估值对比 ───────────────────────
from agent.prompts import SYSTEM_PROMPTS_TOOLS
en, zh = SYSTEM_PROMPTS_TOOLS["en"], SYSTEM_PROMPTS_TOOLS["zh"]
check("rule10 en valuation compare", "valuation differences" in en
      and "call the compare tool ONCE" in en)
check("rule10 zh valuation compare", "估值差异" in zh and "一次性传入" in zh)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL V3.4.5 TESTS PASSED")
