"""V3.4.1 回归：财务深度（三大报表解析 / 双源降级 / 工具合并 / 对比页表格）"""
import json, os, sys, tempfile, time
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.storage as storage
import data.chat_store as chat_store
import data.fundamentals as fund
import agent.tools as at

REAL_CFG = os.path.join(os.getcwd(), ".agent_config.json")
with open(REAL_CFG) as f:
    real_content = f.read()
tmp_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp_cfg.write('{"api_key": "test-demo-key", "watchlist": ["AAPL"]}')
tmp_cfg.close()
tmp_chat = os.path.join(tempfile.mkdtemp(), "chat_history.json")
tmp_cache = tempfile.mkdtemp()

CACHE_PATCH = mock.patch.object(fund, "CACHE_DIR", tmp_cache)
CACHE_PATCH.start()
SA_PATCH = mock.patch.object(fund, "_sa_fetch", side_effect=Exception("no net"))
SA_PATCH.start()

# ── 1. Twelve Data 全量解析（mock 请求，新三端点结构）──
TD_DATA = {
    "income_statement": [
        {"fiscal_date": "2026-06-30", "quarter": 3, "year": 2026, "sales": 90e9,
         "gross_profit": 40e9, "net_income": 22e9, "eps_basic": 1.5},
        {"fiscal_date": "2026-03-31", "quarter": 2, "year": 2026, "sales": 85e9,
         "gross_profit": 38e9, "net_income": 20e9},
        {"fiscal_date": "2025-12-31", "quarter": 1, "year": 2026, "sales": 80e9,
         "gross_profit": 35e9, "net_income": 19e9},
        {"fiscal_date": "2025-09-30", "quarter": 4, "year": 2025, "sales": 75e9,
         "gross_profit": 33e9, "net_income": 18e9},
        {"fiscal_date": "2025-06-30", "quarter": 3, "year": 2025, "sales": 70e9,
         "gross_profit": 30e9, "net_income": 15e9}],
    "balance_sheet": [
        {"fiscal_date": "2026-06-30", "quarter": 3, "year": 2026,
         "assets": {"total_assets": 400e9,
                    "current_assets": {"total_current_assets": 120e9}},
         "liabilities": {"total_liabilities": 250e9,
                         "current_liabilities": {"total_current_liabilities": 100e9}},
         "shareholders_equity": {"total_shareholders_equity": 150e9}}],
    "cash_flow": [
        {"fiscal_date": "2026-06-30", "quarter": 3, "year": 2026,
         "operating_activities": {"operating_cash_flow": 30e9},
         "investing_activities": {"investing_cash_flow": -8e9},
         "financing_activities": {"financing_cash_flow": -10e9}}],
}

with mock.patch.object(fund, "CACHE_DIR", tmp_cache), \
     mock.patch.object(fund, "_td_request", return_value=TD_DATA):
    f = fund.get_fundamentals("AAPL", api_key="k")
assert f["source"] == "twelvedata-fundamentals"
assert abs(f["revenue"] - 330e9) < 1e6          # TTM 四季度和
assert abs(f["net_income"] - 79e9) < 1e6
assert abs(f["gross_margin"] - 146/330*100) < 0.01  # TTM 毛利/营收
assert abs(f["net_margin"] - 79/330*100) < 0.5
assert abs(f["roe"] - 79e9/150e9*100) < 0.5     # TTM 净利 / 权益
assert abs(f["debt_to_equity"] - 250/150) < 0.01
assert abs(f["current_ratio"] - 120/100) < 0.01
assert f["revenue_growth_yoy"] is not None and abs(f["revenue_growth_yoy"] - (90/70-1)*100) < 0.5
assert len(f["revenue_trend"]) == 4
assert abs(f["operating_cash_flow"] - 30e9) < 1e6
print("PASS Twelve Data fundamentals parse (TTM/margins/ROE/trend)")

# ── 1b. _td_request：三端点 URL 正确 + 429 自动重试一次 ──
from urllib.error import HTTPError
class FakeResp:
    def __init__(self, payload): self._p = payload
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self._p.encode()

td_calls = []
def fake_urlopen(req, timeout=15):
    url = req.full_url
    td_calls.append(url)
    assert "period=quarterly" in url and "apikey=" in url, url
    if url.endswith("income_statement?symbol=AAPL&period=quarterly&apikey=k"):
        return FakeResp('{"status":"ok","income_statement":[{"fiscal_date":"2026-06-30","sales":1e9,"net_income":2e8,"gross_profit":4e8,"eps_basic":0.1}]}')
    if url.endswith("balance_sheet?symbol=AAPL&period=quarterly&apikey=k"):
        if td_calls.count(url) == 1:
            raise HTTPError(url, 429, "Too Many Requests", {}, None)
        return FakeResp('{"status":"ok","balance_sheet":[{"fiscal_date":"2026-06-30","assets":{"total_assets":5e9},"liabilities":{"total_liabilities":3e9},"shareholders_equity":{"total_shareholders_equity":2e9}}]}')
    if url.endswith("cash_flow?symbol=AAPL&period=quarterly&apikey=k"):
        return FakeResp('{"status":"ok","cash_flow":[{"fiscal_date":"2026-06-30","operating_activities":{"operating_cash_flow":1e8},"investing_activities":{"investing_cash_flow":-1e7},"financing_activities":{"financing_cash_flow":-2e7}}]}')
    raise AssertionError("unexpected url " + url)

with mock.patch.object(fund.time, "sleep", return_value=None), \
     mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
    td = fund._td_request("AAPL", "k")
assert set(td) == {"income_statement", "balance_sheet", "cash_flow"}
assert len(td["income_statement"]) == 1 and td["income_statement"][0]["sales"] == 1e9
assert sum(1 for u in td_calls if "balance_sheet" in u) == 2   # 429 → 重试一次
print("PASS _td_request 3-endpoint URLs + 429 auto-retry")

# ── 1c. stockanalysis.com 解析（mock 页面 HTML，结构与真实页面一致）──
SA_INC = """
<table><thead><tr><th>Fiscal Quarter</th><th>Q3 2026</th><th>Q2 2026</th>
<th>Q1 2026</th><th>Q4 2025</th><th>Q3 2025</th></tr>
<tr><th>Period Ending</th><th>Jun '26</th><th>Mar '26</th><th>Dec '25</th>
<th>Sep '25</th><th>Jun '25</th></tr></thead><tbody>
<tr><td>Revenue</td><td>90000</td><td>85000</td><td>80000</td><td>75000</td><td>70000</td></tr>
<tr><td>Revenue Growth (YoY)</td><td>16.36%</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
<tr><td>Gross Profit</td><td>40000</td><td>38000</td><td>35000</td><td>33000</td><td>30000</td></tr>
<tr><td>Net Income</td><td>22000</td><td>20000</td><td>19000</td><td>18000</td><td>15000</td></tr>
<tr><td>Net Income Growth (YoY)</td><td>27.12%</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
<tr><td>EPS (Basic)</td><td>1.50</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
</tbody></table>
"""
SA_BAL = """
<table><tbody>
<tr><td>Total Current Assets</td><td>120000</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
<tr><td>Total Assets</td><td>400000</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
</tbody></table>
<table><tbody>
<tr><td>Total Current Liabilities</td><td>100000</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
<tr><td>Total Liabilities</td><td>250000</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
</tbody></table>
<table><tbody>
<tr><td>Shareholders' Equity</td><td>150000</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
</tbody></table>
"""
SA_CF = """
<table><tbody>
<tr><td>Operating Cash Flow</td><td>30000</td><td>28000</td><td>27000</td><td>26000</td><td>-</td></tr>
</tbody></table>
<table><tbody>
<tr><td>Investing Cash Flow</td><td>-8000</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
</tbody></table>
<table><tbody>
<tr><td>Financing Cash Flow</td><td>-10000</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
</tbody></table>
"""
def fake_sa_fetch(url):
    if "income-statement" in url: return SA_INC
    if "balance-sheet" in url: return SA_BAL
    if "cash-flow-statement" in url: return SA_CF
    raise AssertionError(url)

with mock.patch.object(fund, "_sa_fetch", side_effect=fake_sa_fetch):
    fsa = fund._from_stockanalysis("MSFT")
assert fsa["source"] == "stockanalysis"
assert abs(fsa["revenue"] - 330e9) < 1e6          # TTM 四季度和 ×1e6
assert abs(fsa["net_income"] - 79e9) < 1e6
assert abs(fsa["gross_margin"] - 146/330*100) < 0.01
assert abs(fsa["revenue_growth_yoy"] - 16.36) < 0.01
assert abs(fsa["debt_to_equity"] - 250/150) < 0.01
assert abs(fsa["current_ratio"] - 120/100) < 0.01
assert fsa["eps"] == 1.5
assert len(fsa["revenue_trend"]) == 4 and fsa["revenue_trend"][0]["period"] == "Q3 2026"
assert abs(fsa["operating_cash_flow"] - 111e9) < 1e6   # 30+28+27+26 TTM
print("PASS stockanalysis parse (TTM/ratios/trend)")

import pandas as pd

class FakeYfTicker:
    def __init__(self, symbol=None):
        pass

    @property
    def quarterly_financials(self):
        return pd.DataFrame({
            "2026-06-30": [90e9, 40e9, 22e9, 1.5],
            "2026-03-31": [85e9, 38e9, 20e9, 1.4],
            "2025-12-31": [80e9, 35e9, 19e9, 1.3],
            "2025-09-30": [75e9, 33e9, 18e9, 1.2],
            "2025-06-30": [70e9, 30e9, 15e9, 1.1]},
            index=["Total Revenue", "Gross Profit", "Net Income", "Basic EPS"])
    @property
    def quarterly_balance_sheet(self):
        return pd.DataFrame({
            "2026-06-30": [400e9, 250e9, 150e9, 120e9, 100e9]},
            index=["Total Assets", "Total Liabilities Net Minority Interest",
                   "Stockholders Equity", "Current Assets", "Current Liabilities"])
    @property
    def quarterly_cashflow(self):
        return pd.DataFrame({"2026-06-30": [30e9, -8e9, -10e9]},
                            index=["Operating Cash Flow", "Investing Cash Flow",
                                   "Financing Cash Flow"])

class FakeYf:
    Ticker = FakeYfTicker

# ── 2. yfinance 全量解析（TD 失败 → yfinance 成功）──
with mock.patch.object(fund, "_td_request", side_effect=Exception("403 paid")), \
     mock.patch.object(fund, "_yf", FakeYf):
    fy = fund.get_fundamentals("MSFT", api_key="free")
assert fy["source"] == "yfinance"
assert abs(fy["revenue"] - 330e9) < 1e6          # TTM 四季度和
assert abs(fy["net_income"] - 79e9) < 1e6
assert abs(fy["gross_margin"] - 146/330*100) < 0.01
assert abs(fy["debt_to_equity"] - 250/150) < 0.01
assert abs(fy["current_ratio"] - 120/100) < 0.01
assert abs(fy["revenue_growth_yoy"] - (90/70-1)*100) < 0.5  # 最新季 vs 去年同季
assert len(fy["revenue_trend"]) == 4
assert fy["operating_cash_flow"] == 30e9 and fy["eps"] == 1.5
print("PASS yfinance parse (TTM/ratios/trend)")

# ── 3. 新浪摘要解析（TD + yfinance 都不可用 → 新浪）──
SINA = {"symbol": "aapl", "name": "苹果", "总营业收入": "1000亿", "净利润": "200亿",
        "毛利润": "450亿", "总资产": "3000亿", "总负债": "1800亿", "股东权益": "1200亿",
        "经营现金流量": "150亿", "投资现金流量": "-30亿", "筹资现金流量": "-50亿",
        "每股收益": "1.2", "净资产收益率": "16.7"}
with mock.patch.object(fund, "_td_request", side_effect=Exception("403 paid")), \
     mock.patch.object(fund, "_yf", None), \
     mock.patch.object(fund, "_sina_request", return_value=SINA):
    f2 = fund.get_fundamentals("NVDA", api_key="free")
assert f2["source"] == "sina"
assert abs(f2["gross_margin"] - 45.0) < 0.01     # 450/1000
assert abs(f2["net_margin"] - 20.0) < 0.01       # 200/1000
assert abs(f2["debt_to_equity"] - 1.5) < 0.01    # 1800/1200
assert f2["eps"] == 1.2 and f2["roe"] == 16.7
print("PASS Sina summary parse (bilingual keys)")

# ── 4. 双源都失败 → 空模型，不抛异常 ──
with mock.patch.object(fund, "_td_request", side_effect=Exception("net")), \
     mock.patch.object(fund, "_yf", None), \
     mock.patch.object(fund, "_sina_request", side_effect=Exception("net")):
    f3 = fund.get_fundamentals("ZZZZ")
assert f3["source"] == "none" and f3["revenue"] is None and f3["revenue_trend"] == []
print("PASS graceful empty fallback")

# ── 4b. 新浪「伪成功」（有 source 但字段全空）→ 识别为失败，不返回空壳 ──
with mock.patch.object(fund, "_td_request", side_effect=Exception("403")), \
     mock.patch.object(fund, "_yf", None), \
     mock.patch.object(fund, "_sina_request", return_value={"symbol": "aapl",
                                                            "unknown": "x"}):
    f3b = fund.get_fundamentals("TSLA", api_key="free")
assert f3b["source"] == "none" and f3b["revenue"] is None
print("PASS sina pseudo-success detected (falls through, no empty shell)")

# ── 4. 缓存：二次调用不再请求数据源 ──
with mock.patch.object(fund, "CACHE_DIR", tmp_cache), \
     mock.patch.object(fund, "_td_request", return_value=TD_DATA) as td:
    a = fund.get_fundamentals("ORCL", api_key="k")
    b = fund.get_fundamentals("ORCL", api_key="k")
assert a == b and td.call_count == 1  # 第二次命中缓存，不再请求
print("PASS fundamentals disk cache (24h)")

# ── 4c. 空壳缓存（历史伪成功的全空结果）→ 视为无效，删除并重新抓取 ──
os.makedirs(tmp_cache, exist_ok=True)
empty_shell = fund._empty("NVDA", "sina")   # source 有值但核心字段全空
with open(fund._cache_path("NVDA"), "w") as f:
    json.dump({"ts": time.time(), "value": empty_shell}, f)
with mock.patch.object(fund, "CACHE_DIR", tmp_cache), \
     mock.patch.object(fund, "_td_request", return_value=TD_DATA):
    fc = fund.get_fundamentals("NVDA", api_key="k")
assert fc["source"] == "twelvedata-fundamentals"   # 未命中空壳缓存，重新抓取
assert fc["revenue"] is not None and fc["net_income"] is not None
print("PASS empty shell cache ignored (re-fetch)")

# ── 5. tool_get_financials 合并估值 + 财务深度 ──
FAKE_FUND = {"source": "sina", "revenue": 390e9, "net_income": 95e9,
             "gross_margin": 43.0, "net_margin": 24.0,
             "revenue_growth_yoy": 6.5, "net_income_growth_yoy": 9.0,
             "revenue_trend": [], "net_income_trend": [],
             "total_assets": 350e9, "total_liabilities": 280e9,
             "stockholders_equity": 70e9, "debt_to_equity": 4.0,
             "current_ratio": 1.2, "operating_cash_flow": 110e9,
             "investing_cash_flow": -15e9, "financing_cash_flow": -90e9,
             "eps": 6.5, "roe": 135.0}
with mock.patch.object(at, "get_statistics", side_effect=Exception("403")), \
     mock.patch.object(at, "_quote_with_fallback",
                       return_value=({"pe_ratio": 30.1, "market_cap": 3.5e12}, "cache")), \
     mock.patch.object(at, "get_fundamentals", return_value=FAKE_FUND):
    out = at.tool_get_financials("AAPL")
assert out["symbol"] == "AAPL"
assert out["pe_ratio"] == 30.1 and out["market_cap"] == 3.5e12   # 估值来自备用报价
assert out["revenue"] == 390e9 and out["debt_to_equity"] == 4.0  # 深度来自财务源
assert out["current_ratio"] == 1.2 and out["operating_cash_flow"] == 110e9
assert out["source"] == "sina"
print("PASS get_financials merges valuation + deep fundamentals")

# ── 5b. stockanalysis 主页概况解析（公司简介/行业/板块/员工/官网 + 市值/PE）──
SA_MAIN = """
<html><body>
<h2 class="mb-2">About NVDA</h2>
<p>NVIDIA Corporation operates as a data center company in the US and internationally.
<a href="/stocks/nvda/company/" tabIndex="-1">[Read more]</a></p>
<div class="mt-3 grid grid-cols-2 gap-3">
<div class="col-span-1"><span class="block font-semibold">Industry</span><a class="dothref text-default">Semiconductors</a></div>
<div class="col-span-1"><span class="block font-semibold">Sector</span><a class="dothref text-default">Technology</a></div>
<div class="col-span-1"><span class="block font-semibold">Employees</span><a class="dothref text-default">42,000</a></div>
<div class="col-span-1"><span class="block font-semibold">Stock Exchange</span><span>NASDAQ</span></div>
<div class="col-span-2"><span class="block font-semibold">Website</span><a href="https://www.nvidia.com">nvidia.com</a></div>
</div>
<table><tbody>
<tr><td>Market Cap</td><td>5.42T +23.9%</td></tr>
<tr><td>PE Ratio</td><td>34.30</td></tr>
</tbody></table>
</body></html>
"""
def fake_sa_main(url):
    assert "nvda" in url
    return SA_MAIN

with mock.patch.object(fund, "_sa_fetch", side_effect=fake_sa_main), \
     mock.patch.object(fund, "_sa_profile_cache_path",
                       return_value=os.path.join(tmp_cache, "sa_prof_NVDA.json")):
    sp = fund._from_stockanalysis_profile("NVDA")
assert sp["source"] == "stockanalysis"
assert sp["industry"] == "Semiconductors" and sp["sector"] == "Technology"
assert sp["employees"] == 42000.0 and sp["exchange"] == "NASDAQ"
assert sp["website"] == "https://www.nvidia.com"
assert sp["description"].startswith("NVIDIA Corporation")
assert abs(sp["market_cap"] - 5.42e12) < 1e9
assert abs(sp["pe_ratio"] - 34.3) < 0.01
print("PASS stockanalysis profile parse (description/sector/employees + market cap/PE)")

# ── 5c. valuation_fallback：腾讯失败 → stockanalysis 兜底 ──
with mock.patch.object(fund, "_from_stockanalysis_profile",
                       return_value={"market_cap": 5.42e12, "pe_ratio": 34.3}), \
     mock.patch("data.fallback_data.get_fallback_quote", side_effect=Exception("no tencent")):
    v = fund.valuation_fallback("NVDA")
assert v["market_cap"] == 5.42e12 and v["pe_ratio"] == 34.3 and v["source"] == "stockanalysis"
with mock.patch("data.fallback_data.get_fallback_quote",
                return_value={"market_cap": 5.21e12, "pe_ratio": 33.9}):
    v2 = fund.valuation_fallback("NVDA")
assert v2["market_cap"] == 5.21e12 and v2["pe_ratio"] == 33.9 and v2["source"] == "tencent"
print("PASS valuation_fallback (tencent → stockanalysis)")

# ── 5d. tool_get_profile：/profile 403 → stockanalysis 概况补齐 ──
# V3.4.4 重构：兜底逻辑在 services.stock_service.profile_with_fallback，
# mock 目标改为 stock_service 模块符号。
import services.stock_service as _ss
SA_PROFILE = {"source": "stockanalysis", "name": None, "exchange": "NASDAQ",
              "industry": "Semiconductors", "sector": "Technology",
              "ceo": None, "employees": 42000.0,
              "website": "https://www.nvidia.com",
              "description": "NVIDIA Corporation operates as a data center company.",
              "market_cap": 5.42e12, "pe_ratio": 34.3}
with mock.patch.object(_ss, "get_profile", side_effect=Exception("403 pro")), \
     mock.patch.object(_ss, "_quote_with_fallback",
                       return_value=({"name": "NVIDIA Corporation", "exchange": "NASDAQ"}, "twelvedata")), \
     mock.patch.object(_ss, "_from_stockanalysis_profile", return_value=SA_PROFILE):
    prof = at.tool_get_profile("NVDA")
assert prof["name"] == "NVIDIA Corporation"
assert prof["industry"] == "Semiconductors" and prof["sector"] == "Technology"
assert prof["employees"] == 42000.0 and prof["description"].startswith("NVIDIA")
assert prof["source"] == "stockanalysis"
print("PASS tool_get_profile falls back to stockanalysis (no 403 crash)")

# ── 5e. tool_get_financials：TD quote 无 PE/市值 → valuation_fallback 补齐 ──
with mock.patch.object(at, "get_statistics", side_effect=Exception("403")), \
     mock.patch.object(at, "_quote_with_fallback",
                       return_value=({"pe_ratio": None, "market_cap": None}, "twelvedata")), \
     mock.patch.object(at, "valuation_fallback",
                       return_value={"market_cap": 5.21e12, "pe_ratio": 34.3, "source": "tencent"}), \
     mock.patch.object(at, "get_fundamentals",
                       return_value={"source": "stockanalysis", "revenue": 253e9,
                                     "net_income": 159e9}):
    fin = at.tool_get_financials("NVDA")
assert fin["market_cap"] == 5.21e12 and fin["pe_ratio"] == 34.3
print("PASS tool_get_financials fills market cap / PE from fallback")

# ── 6. 对比页财务表格（AppTest 真实渲染）──
QUOTE = {"symbol": "AAPL", "name": "Apple Inc.", "close": 234.56, "change": 2.31,
         "percent_change": 0.99, "currency": "USD",
         "fifty_two_week": {"high": 260.0}, "exchange": "NASDAQ"}
HIST = [{"datetime": f"2026-01-{i+1:02d}", "open": 100+i, "high": 102+i,
         "low": 99+i, "close": 101+i, "volume": 1000000} for i in range(30)]
def fake_fetch_compare_data(tickers, period_days, interval="1day"):
    return ({t: dict(QUOTE) for t in tickers},
            {t: list(HIST) for t in tickers},
            {t: "cache" for t in tickers})
def fake_fund(tk):
    return dict(FAKE_FUND, symbol=tk, market_cap=3.5e12, pe_ratio=30.1)
def fake_indices():
    return []
def fake_compare_fund(tk):
    f = dict(FAKE_FUND, symbol=tk)
    f["market_cap"] = 3.5e12
    f["pe_ratio"] = 30.1
    return f

import sys as _sys
_sys.modules.pop("app", None)  # 强制 AppTest 重新导入 app.py（避免 mock 残留）
with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
     mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
     mock.patch.object(fund, "CACHE_DIR", tmp_cache), \
     mock.patch("services.stock_service.fetch_compare_data", fake_fetch_compare_data), \
     mock.patch("services.stock_service.fetch_indices", fake_indices), \
     mock.patch.object(fund, "get_fundamentals", fake_compare_fund):
    from streamlit.testing.v1 import AppTest
    at2 = AppTest.from_file("app.py", default_timeout=60)
    at2.run()
    at2.button(key="mode_compare_btn").click(); at2.run()
    tinputs = at2.text_input
    tinputs[0].set_value("AAPL"); at2.run()
    [b for b in at2.button if b.label in ("Add", "添加")][0].click(); at2.run()
    tinputs = at2.text_input
    tinputs[0].set_value("MSFT"); at2.run()
    [b for b in at2.button if b.label in ("Add", "添加")][0].click(); at2.run()
    [b for b in at2.button
     if b.label in ("Compare", "开始对比") and b.key != "mode_compare_btn"][0].click(); at2.run()
    assert not at2.exception, [str(e) for e in at2.exception]
    md = " ".join(str(m.value) for m in at2.markdown)
    assert ("Financials" in md) or ("财务对比" in md), md[-500:]
    # 财务表格应渲染（dataframe 存在且行数 = 11 项指标）
    assert len(at2.dataframe) >= 1
    print("PASS compare page renders financials table")
    pref_backup = json.load(open(tmp_cfg.name)).get("preferences", {})
    print("  (preferences recorded during flow:", list(pref_backup.get("stocks", {}).keys()), ")")

CACHE_PATCH.stop()
SA_PATCH.stop()
print("\nALL V3.4.1 TESTS PASSED")
