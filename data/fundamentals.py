"""
Fundamentals Module (V3.4.1)
============================
财务深度数据：三大报表关键项（利润表 / 资产负债表 / 现金流量表）+ 营收净利趋势。

数据源四降级：
1. Twelve Data /income_statement|balance_sheet|cash_flow（period=quarterly）——
   免费套餐对美股仅开放 AAPL 一只演示股，其余 403；限速 429 时自动等待重试。
2. stockanalysis.com（免 Key，覆盖全部美股）—— 季度三大报表 + 同比 + 趋势。
3. yfinance（免 Key，本机已装）—— 三大报表全量 + 季度趋势；国内访问 Yahoo
   慢/失败时加 20 秒硬超时自动降级。
4. 新浪财经财务摘要（免 Key）—— 仅支持 A/港股票；美股返回空时自动识别并降级。

设计原则（沿用项目哲学）：
- 所有字段允许 None：数据缺失时不编造，由 AI 如实说明
- 比率只从已取到的真实字段计算（毛利率/净利率/负债率/流动比率/ROE）
- 接口失败静默降级，不抛异常（返回 source="none" 的空模型）
"""

import concurrent.futures
import io
import re as _re
import json as _json
import os
import time
import urllib.error
import urllib.request

import data.finance_data as _finance_data
from utils import safe_float

try:
    import yfinance as _yf   # 免费深度源（三大报表全量），未安装时自动跳过
except ImportError:
    _yf = None

try:
    import pandas as _pd   # 解析 stockanalysis 财报表格
except ImportError:
    _pd = None

SINA_URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "FinanceSummaryService.getFinanceSummary?symbol={ticker}")
TD_BASE = "https://api.twelvedata.com"
TD_PERIOD = "quarterly"          # 季度报表（TTM 计算需要）
TD_ENDPOINTS = ("income_statement", "balance_sheet", "cash_flow")
TD_RETRY_WAIT = 12               # 免费套餐 8 次/分钟，429 后等待秒数

SA_MAIN_URL = "https://stockanalysis.com/stocks/{ticker}/"
SA_BASE = "https://stockanalysis.com/stocks/{ticker}/financials/{page}/quarterly/"
SA_PAGES = ("income-statement", "balance-sheet", "cash-flow-statement")
SA_MULT = 1e6                    # stockanalysis 数值单位：百万美元
SA_TIMEOUT = 15
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36")}
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         ".cache")
CACHE_TTL = 86400   # 财务数据 24 小时缓存（非关键实时数据，够用）


# ─── 通用工具 ───────────────────────────────────────────

def _td_request(symbol: str, api_key: str) -> dict:
    """请求 Twelve Data 三大报表（季度）；任一失败抛异常，由外层降级"""
    out = {}
    for ep in TD_ENDPOINTS:
        url = (f"{TD_BASE}/{ep}?symbol={symbol}&period={TD_PERIOD}&apikey={api_key}")
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:          # 免费套餐限速：等 12 秒重试一次
                time.sleep(TD_RETRY_WAIT)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = _json.loads(resp.read().decode())
            else:
                raise
        if not data.get(ep):   # 裸端点返回 {"meta":…, "<ep>":[…]}，无 status 字段
            raise ValueError(data.get("message") or f"{ep} unavailable")
        out[ep] = data[ep]
    return out


def _sina_request(ticker: str) -> dict:
    """请求新浪财经财务摘要；失败时抛异常"""
    url = SINA_URL.format(ticker=ticker.lower())
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read().decode("utf-8", errors="replace").strip()
    if not raw:
        raise ValueError("empty sina response")
    # 新浪偶发返回 JSONP 包裹或前导注释
    if raw.startswith("/*") or raw.startswith("//"):
        raw = raw[raw.index("{"):]
    if raw.startswith("["):
        raw = raw[1:raw.rindex("]")]
    return _json.loads(raw)


def _pick(d: dict, *keys):
    """多候选键名提取（兼容 Twelve Data / 新浪字段差异）"""
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def _num(v):
    """解析带单位的中文数字（"1000亿"→1e11，"1.5万"→1.5e4，"1,234.5"→1234.5）"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace(" ", "")
    if not s:
        return None
    mult = 1.0
    for unit, m in (("万亿", 1e12), ("亿", 1e8), ("万", 1e4), ("百万", 1e6),
                    ("元", 1.0), ("¥", 1.0), ("$", 1.0), ("%", 1.0)):
        if s.endswith(unit):
            s = s[: -len(unit)]
            mult = m
            break
    try:
        return float(s) * mult
    except (TypeError, ValueError):
        return safe_float(v)


def _first(rows: list, key: str):
    """取最新一期（数组首条）的字段值"""
    if not rows or not isinstance(rows[0], dict):
        return None
    return safe_float(rows[0].get(key))


def _pct_change(latest, older) -> float:
    """同比/环比百分比（older 为 0/None 时返回 None）"""
    latest = safe_float(latest)
    older = safe_float(older)
    if latest is None or not older:
        return None
    return (latest / older - 1) * 100


# ─── Twelve Data 全量解析 ───────────────────────────────

def _from_twelvedata(ticker: str, api_key: str) -> dict:
    """解析 Twelve Data 三大报表（period=quarterly）：TTM 营收/净利/毛利 + 资产负债 + 现金流 + 趋势"""
    data = _td_request(ticker, api_key)
    inc = data.get("income_statement") or []
    bs = data.get("balance_sheet") or []
    cf = data.get("cash_flow") or []
    if not inc:
        raise ValueError("income statement unavailable")

    def trend(rows, key, limit=4):
        out = []
        for r in rows[:limit]:
            v = safe_float(r.get(key))
            if v is None:
                continue
            out.append({"period": r.get("fiscal_date") or "?", "value": v})
        return out

    # 最近 4 季求和得到 TTM（营收/净利/毛利）
    def ttm(rows, key, limit=4):
        vals = [safe_float(r.get(key)) for r in rows[:limit]]
        return sum(v for v in vals if v is not None) or None

    revenue_ttm = ttm(inc, "sales")
    gross_ttm = ttm(inc, "gross_profit")
    net_ttm = ttm(inc, "net_income")
    # 同比：最新一季 vs 去年同季（rows 按最新在前）
    q_rev = _first(inc, "sales")
    q_net = _first(inc, "net_income")
    revenue_yoy = (_pct_change(q_rev, _first(inc[4:], "sales"))
                   if len(inc) > 4 else None)
    net_yoy = (_pct_change(q_net, _first(inc[4:], "net_income"))
               if len(inc) > 4 else None)

    # 资产负债表（点值：取最新一期）
    b0 = bs[0] if bs else {}
    assets = (b0.get("assets") or {})
    liab = (b0.get("liabilities") or {})
    total_assets = assets.get("total_assets")
    total_liabilities = liab.get("total_liabilities")
    equity = (b0.get("shareholders_equity") or {}).get("total_shareholders_equity")
    cur_assets = (assets.get("current_assets") or {}).get("total_current_assets")
    cur_liab = (liab.get("current_liabilities") or {}).get("total_current_liabilities")

    # 现金流量表（TTM：最近 4 季求和）
    def ttm_cf(section, key, limit=4):
        vals = []
        for r in cf[:limit]:
            v = safe_float((r.get(section) or {}).get(key))
            if v is not None:
                vals.append(v)
        return sum(vals) or None

    ocf = ttm_cf("operating_activities", "operating_cash_flow")
    icf = ttm_cf("investing_activities", "investing_cash_flow")
    fcf = ttm_cf("financing_activities", "financing_cash_flow")
    eps = _first(inc, "eps_basic") or _first(inc, "eps_diluted")

    def _ratio(a, b):
        """比率 ×100（毛利/净利/ROE 等）"""
        a, b = safe_float(a), safe_float(b)
        if a is None or not b:
            return None
        return a / b * 100

    return {
        "source": "twelvedata-fundamentals",
        "revenue": revenue_ttm, "net_income": net_ttm, "gross_profit": gross_ttm,
        "gross_margin": _ratio(gross_ttm, revenue_ttm),
        "net_margin": _ratio(net_ttm, revenue_ttm),
        "revenue_growth_yoy": revenue_yoy, "net_income_growth_yoy": net_yoy,
        "revenue_trend": trend(inc, "sales"),
        "net_income_trend": trend(inc, "net_income"),
        "total_assets": total_assets, "total_liabilities": total_liabilities,
        "stockholders_equity": equity,
        "debt_to_equity": (safe_float(total_liabilities) / equity
                           if total_liabilities is not None and equity else None),
        "current_ratio": (safe_float(cur_assets) / safe_float(cur_liab)
                          if cur_assets is not None and cur_liab else None),
        "operating_cash_flow": ocf, "investing_cash_flow": icf,
        "financing_cash_flow": fcf, "eps": eps,
        "roe": _ratio(net_ttm, equity),
    }


# ─── yfinance 全量解析（免费，三大报表 + 季度趋势）────────

def _yf_row(df, *keywords):
    """按关键词在 DataFrame index 找行，返回 Series（最新一列在前）"""
    if df is None or df.empty:
        return None
    for name in df.index:
        low = str(name).lower()
        if any(kw in low for kw in keywords):
            return df.loc[name]
    return None


def _yf_ttm(series, n=4):
    """最近 n 期求和（TTM）；无有效值返回 None"""
    if series is None:
        return None
    vals = [safe_float(v) for v in series.iloc[:n]]
    vals = [v for v in vals if v is not None]
    return sum(vals) or None


def _yf_latest(series):
    if series is None or len(series) == 0:
        return None
    return safe_float(series.iloc[0])


def _yf_trend(series, n=4):
    out = []
    if series is None:
        return out
    for i in range(min(n, len(series))):
        v = safe_float(series.iloc[i])
        if v is None:
            continue
        out.append({"period": str(series.index[i])[:10], "value": v})
    return out


def _from_yfinance(ticker: str) -> dict:
    """用 yfinance 拉三大报表：TTM 营收/净利/毛利 + 资产负债 + 现金流 + 季度趋势"""
    if _yf is None:
        raise ValueError("yfinance not installed")
    t = _yf.Ticker(str(ticker).upper())

    def qdf(*attrs):
        for a in attrs:
            try:
                df = getattr(t, a)
                if df is not None and not df.empty:
                    return df
            except Exception:
                continue
        return None

    inc = qdf("quarterly_financials", "quarterly_income_stmt")
    bs = qdf("quarterly_balance_sheet")
    cf = qdf("quarterly_cashflow")

    rev_s = _yf_row(inc, "total revenue")
    gross_s = _yf_row(inc, "gross profit")
    net_s = _yf_row(inc, "net income")
    eps_s = _yf_row(inc, "basic eps", "diluted eps")
    assets_s = _yf_row(bs, "total assets")
    liab_s = _yf_row(bs, "total liabilities")
    eq_s = _yf_row(bs, "stockholders equity", "total equity")
    ca_s = _yf_row(bs, "current assets")
    cl_s = _yf_row(bs, "current liabilities")
    ocf_s = _yf_row(cf, "operating cash flow")
    icf_s = _yf_row(cf, "investing cash flow")
    fcf_s = _yf_row(cf, "financing cash flow")

    revenue = _yf_ttm(rev_s)
    gross = _yf_ttm(gross_s)
    net = _yf_ttm(net_s)
    assets = _yf_latest(assets_s)
    liab = _yf_latest(liab_s)
    eq = _yf_latest(eq_s)
    ca, cl = _yf_latest(ca_s), _yf_latest(cl_s)

    def _ratio(a, b):
        a, b = safe_float(a), safe_float(b)
        if a is None or not b:
            return None
        return a / b * 100

    q_rev = _yf_latest(rev_s)
    yoy_rev = None
    if q_rev is not None and rev_s is not None and len(rev_s) > 4:
        older = safe_float(rev_s.iloc[4])
        if older:
            yoy_rev = (q_rev / older - 1) * 100
    q_net = _yf_latest(net_s)
    yoy_net = None
    if q_net is not None and net_s is not None and len(net_s) > 4:
        older = safe_float(net_s.iloc[4])
        if older:
            yoy_net = (q_net / older - 1) * 100

    return {
        "source": "yfinance",
        "revenue": revenue, "net_income": net, "gross_profit": gross,
        "gross_margin": _ratio(gross, revenue),
        "net_margin": _ratio(net, revenue),
        "revenue_growth_yoy": yoy_rev, "net_income_growth_yoy": yoy_net,
        "revenue_trend": _yf_trend(rev_s), "net_income_trend": _yf_trend(net_s),
        "total_assets": assets, "total_liabilities": liab,
        "stockholders_equity": eq,
        "debt_to_equity": (safe_float(liab) / eq if liab is not None and eq else None),
        "current_ratio": (safe_float(ca) / safe_float(cl)
                          if ca is not None and cl else None),
        "operating_cash_flow": _yf_ttm(ocf_s),
        "investing_cash_flow": _yf_ttm(icf_s),
        "financing_cash_flow": _yf_ttm(fcf_s),
        "eps": _yf_latest(eps_s),
        "roe": _ratio(net, eq),
    }


# ─── stockanalysis.com 主页解析（公司概况 + 估值，无 Key）──

def _sa_num_abbr(v):
    """解析缩写数值："5.42T +23.9%"→5.42e12，"253.49B"→2.53e11，"42,000"→42000"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    s = s.split()[0]
    mult = 1.0
    for suf, m in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if s.endswith(suf):
            mult = m
            s = s[:-1]
            break
    try:
        return float(s) * mult
    except ValueError:
        return None


def _sa_main_stats(html: str) -> dict:
    """主页数据框：Market Cap / PE Ratio 等（read_html 多表合并为 label→value）"""
    out = {}
    for t in _pd.read_html(io.StringIO(html)):
        if t.shape[1] < 2:
            continue
        for _, row in t.iterrows():
            label = str(row.iloc[0]).strip()
            if label and label not in out:
                out[label] = row.iloc[1]
    return out


def _sa_profile_box(html: str) -> dict:
    """概况框：Industry/Sector/Employees/Stock Exchange/Website（div 结构，bs4 解析）"""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}
    soup = BeautifulSoup(html, "lxml")
    out = {}

    def el(label):
        span = soup.find("span", class_="block font-semibold",
                         string=lambda t: t and t.strip() == label)
        if span is None:
            return None
        for sib in span.find_next_siblings():
            if getattr(sib, "name", None) is not None:
                return sib
        return None

    for label, key in (("Industry", "industry"), ("Sector", "sector"),
                       ("Employees", "employees"),
                       ("Stock Exchange", "exchange"), ("Website", "website")):
        e = el(label)
        if e is None:
            continue
        v = e.get("href") if label == "Website" else e.get_text(strip=True)
        if v:
            out[key] = v
    return out


def _sa_about_text(html: str):
    """"About {TICKER}" 段落（公司简介）"""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html, "lxml")
    h2 = soup.find("h2", string=lambda t: t and t.strip().startswith("About "))
    if h2 is None:
        return None
    p = h2.find_next("p")
    if p is None:
        return None
    text = p.get_text(" ", strip=True)
    return _re.sub(r"\s*\[Read more\]\s*$", "", text) or None


def _sa_profile_cache_path(ticker: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = "".join(c for c in str(ticker).upper() if c.isalnum()) or "TICKER"
    return os.path.join(CACHE_DIR, f"sa_prof_{safe}.json")


def _from_stockanalysis_profile(ticker: str) -> dict:
    """公司概况（免费）：简介/行业/板块/员工/官网/交易所 + 市值/PE，24h 缓存"""
    tk = str(ticker).lower()
    try:
        with open(_sa_profile_cache_path(ticker)) as f:
            d = _json.load(f)
        if time.time() - d.get("ts", 0) <= CACHE_TTL and isinstance(d.get("value"), dict):
            return d["value"]
    except (FileNotFoundError, OSError, ValueError):
        pass

    html = _sa_fetch(SA_MAIN_URL.format(ticker=tk))
    stats = _sa_main_stats(html)
    box = _sa_profile_box(html)
    desc = _sa_about_text(html)
    out = {
        "source": "stockanalysis",
        "name": None,                       # 由调用方用报价名补全
        "description": (desc or "")[:600] or None,
        "sector": box.get("sector"),
        "industry": box.get("industry"),
        "exchange": box.get("exchange"),
        "employees": _sa_num_abbr(box.get("employees")),
        "website": box.get("website"),
        "ceo": None,                        # stockanalysis 主页无 CEO，留空不编造
        "market_cap": _sa_num_abbr(stats.get("Market Cap")),
        "pe_ratio": _sa_num(stats.get("PE Ratio"), 1.0),
    }
    try:
        path = _sa_profile_cache_path(ticker)
        with open(f"{path}.tmp", "w") as f:
            _json.dump({"ts": time.time(), "value": out}, f)
        os.replace(f"{path}.tmp", path)
    except OSError:
        pass
    return out


def valuation_fallback(ticker: str) -> dict:
    """市值/PE 兜底：腾讯备用报价 → stockanalysis 主页；都失败返回空 dict"""
    out = {"market_cap": None, "pe_ratio": None, "source": None}
    try:
        from data.fallback_data import get_fallback_quote
        q = get_fallback_quote(str(ticker).upper())
        out["market_cap"] = safe_float(q.get("market_cap"))
        out["pe_ratio"] = safe_float(q.get("pe_ratio"))
        out["source"] = "tencent"
    except Exception:
        pass
    if out["market_cap"] is None and out["pe_ratio"] is None:
        try:
            sa = _from_stockanalysis_profile(ticker)
            out["market_cap"] = safe_float(sa.get("market_cap"))
            out["pe_ratio"] = safe_float(sa.get("pe_ratio"))
            out["source"] = "stockanalysis"
        except Exception:
            pass
    return out


# ─── stockanalysis.com 免费财报解析（无 Key，覆盖全部美股）──

def _sa_fetch(url: str) -> str:
    """抓取 stockanalysis 页面；失败抛异常"""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=SA_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _sa_num(v, mult=1.0) -> float:
    """解析单元格数值："109417"→109417*mult，"16.36%"→16.36，"-"→None"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s or s == "-":
        return None
    if s.endswith("%"):
        return safe_float(s[:-1])     # 百分比行直接用数值（如 16.36）
    try:
        return float(s) * mult
    except ValueError:
        return None


def _sa_row(df, name):
    """按首列行名取整行（各季度列，最新在前）；找不到返回 None"""
    if df is None or df.empty:
        return None
    m = df[df.iloc[:, 0] == name]
    return m.iloc[0, 1:] if not m.empty else None


def _sa_find_in_tables(tables, name):
    """在页面全部表格中按行名搜索（不同公司页面表格分块方式不同）"""
    for df in tables:
        row = _sa_row(df, name)
        if row is not None:
            return row
    return None


def _sa_vals(series, mult=SA_MULT, n=4):
    """取最近 n 期数值列表"""
    if series is None:
        return []
    return [_sa_num(v, mult) for v in series.iloc[:n]]


def _sa_first(series, mult=1.0):
    """取最新一期数值"""
    vals = _sa_vals(series, mult, 1)
    return vals[0] if vals else None


def _sa_period_labels(df, n=4):
    """列标签（如 "Q3 2026"），用于趋势 period 字段"""
    out = []
    for c in df.columns[1:1 + n]:
        out.append(str(c[0]) if isinstance(c, tuple) else str(c))
    return out


def _from_stockanalysis(ticker: str) -> dict:
    """用 stockanalysis.com 免费季度财报：利润表/资产负债表/现金流 + 趋势"""
    if _pd is None:
        raise ValueError("pandas not installed")
    tk = str(ticker).lower()
    pages = {}
    for page in SA_PAGES:
        url = SA_BASE.format(ticker=tk, page=page)
        pages[page] = _pd.read_html(io.StringIO(_sa_fetch(url)))

    inc = pages["income-statement"]
    bal = pages["balance-sheet"]
    cf = pages["cash-flow-statement"]

    def ttm(series, mult=SA_MULT, n=4):
        vals = [v for v in _sa_vals(series, mult, n) if v is not None]
        return sum(vals) or None

    rev_s = _sa_find_in_tables(inc, "Revenue")
    gross_s = _sa_find_in_tables(inc, "Gross Profit")
    net_s = _sa_find_in_tables(inc, "Net Income")
    revenue_ttm = ttm(rev_s)
    gross_ttm = ttm(gross_s)
    net_ttm = ttm(net_s)

    rev_yoy = _sa_first(_sa_find_in_tables(inc, "Revenue Growth (YoY)"))
    net_yoy = _sa_first(_sa_find_in_tables(inc, "Net Income Growth (YoY)"))

    def trend(series, mult=SA_MULT, n=4):
        out = []
        labels = _sa_period_labels(inc[0], n)
        for i, v in enumerate(_sa_vals(series, mult, n)):
            if v is None:
                continue
            out.append({"period": labels[i] if i < len(labels) else "?", "value": v})
        return out

    # 资产负债表（点值：最新一期）
    def b_val(name):
        vals = _sa_vals(_sa_find_in_tables(bal, name), SA_MULT, 1)
        return vals[0] if vals else None

    total_assets = b_val("Total Assets")
    cur_assets = b_val("Total Current Assets")
    total_liabilities = b_val("Total Liabilities")
    cur_liab = b_val("Total Current Liabilities")
    equity = b_val("Shareholders' Equity")

    # 现金流量表（TTM）
    ocf = ttm(_sa_find_in_tables(cf, "Operating Cash Flow"))
    icf = ttm(_sa_find_in_tables(cf, "Investing Cash Flow"))
    fcf = ttm(_sa_find_in_tables(cf, "Financing Cash Flow"))
    eps = _sa_first(_sa_find_in_tables(inc, "EPS (Basic)"))

    def _ratio(a, b):
        a, b = safe_float(a), safe_float(b)
        if a is None or not b:
            return None
        return a / b * 100

    return {
        "source": "stockanalysis",
        "revenue": revenue_ttm, "net_income": net_ttm, "gross_profit": gross_ttm,
        "gross_margin": _ratio(gross_ttm, revenue_ttm),
        "net_margin": _ratio(net_ttm, revenue_ttm),
        "revenue_growth_yoy": rev_yoy, "net_income_growth_yoy": net_yoy,
        "revenue_trend": trend(rev_s), "net_income_trend": trend(net_s),
        "total_assets": total_assets, "total_liabilities": total_liabilities,
        "stockholders_equity": equity,
        "debt_to_equity": (safe_float(total_liabilities) / equity
                           if total_liabilities is not None and equity else None),
        "current_ratio": (safe_float(cur_assets) / safe_float(cur_liab)
                          if cur_assets is not None and cur_liab else None),
        "operating_cash_flow": ocf, "investing_cash_flow": icf,
        "financing_cash_flow": fcf, "eps": eps,
        "roe": _ratio(net_ttm, equity),
    }


# ─── 新浪财经摘要解析 ───────────────────────────────────

def _norm_key(k: str) -> str:
    """键名规范化：小写、去下划线/空格/括号，便于模糊匹配"""
    return "".join(ch for ch in str(k).lower() if ch.isalnum())


def _sina_find(raw: dict, *keywords) -> dict:
    """在新浪返回里按关键词找字段；优先精确匹配，再退化为子串匹配"""
    if not isinstance(raw, dict):
        return None
    for key, val in raw.items():
        nk = _norm_key(key)
        if any(nk == kw for kw in keywords):
            return val
    for key, val in raw.items():
        nk = _norm_key(key)
        if any(nk in kw or kw in nk for kw in keywords):
            return val
    return None


def _from_sina(ticker: str) -> dict:
    """解析新浪财务摘要：当期关键项（兼容 data 包裹 / 任意键名模糊匹配）"""
    raw = _sina_request(ticker)
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    elif isinstance(raw, dict) and isinstance(raw.get("result"), dict):
        raw = raw["result"]
    if not isinstance(raw, dict):
        raise ValueError("malformed sina summary")

    revenue = _num(_sina_find(raw, "revenue", "营业收入", "营收", "营业总收入"))
    net_income = _num(_sina_find(raw, "netprofit", "净利润", "归母净利润"))
    gross_profit = _num(_sina_find(raw, "grossprofit", "毛利润", "毛利"))
    total_assets = _num(_sina_find(raw, "totalassets", "总资产", "资产总计"))
    total_liabilities = _num(_sina_find(raw, "totalliabilities", "总负债", "负债合计"))
    equity = _num(_sina_find(raw, "equity", "股东权益", "所有者权益"))
    ocf = _num(_sina_find(raw, "operatingcashflow", "经营现金流量", "经营活动现金流",
                          "经营性现金流"))
    icf = _num(_sina_find(raw, "investingcashflow", "投资现金流量", "投资活动现金流"))
    fcf = _num(_sina_find(raw, "financingcashflow", "筹资现金流量", "筹资活动现金流"))
    eps = _num(_sina_find(raw, "eps", "每股收益"))
    roe_raw = _num(_sina_find(raw, "roe", "净资产收益率"))

    def _ratio(a, b):
        a, b = safe_float(a), safe_float(b)
        if a is None or not b:
            return None
        return a / b * 100

    return {
        "source": "sina",
        "revenue": revenue, "net_income": net_income, "gross_profit": gross_profit,
        "gross_margin": _ratio(gross_profit, revenue),
        "net_margin": _ratio(net_income, revenue),
        "revenue_growth_yoy": None, "net_income_growth_yoy": None,
        "revenue_trend": [], "net_income_trend": [],
        "total_assets": total_assets, "total_liabilities": total_liabilities,
        "stockholders_equity": equity,
        "debt_to_equity": (total_liabilities / equity
                           if total_liabilities is not None and equity else None),
        "current_ratio": None,
        "operating_cash_flow": ocf, "investing_cash_flow": icf,
        "financing_cash_flow": fcf, "eps": eps, "roe": roe_raw,
    }


# ─── 对外入口 ───────────────────────────────────────────

def _empty(ticker: str, source: str = "none") -> dict:
    return {"symbol": str(ticker).upper(), "source": source,
            "revenue": None, "net_income": None, "gross_profit": None,
            "gross_margin": None, "net_margin": None,
            "revenue_growth_yoy": None, "net_income_growth_yoy": None,
            "revenue_trend": [], "net_income_trend": [],
            "total_assets": None, "total_liabilities": None,
            "stockholders_equity": None, "debt_to_equity": None,
            "current_ratio": None, "operating_cash_flow": None,
            "investing_cash_flow": None, "financing_cash_flow": None,
            "eps": None, "roe": None}


def _cache_path(ticker: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = "".join(c for c in str(ticker).upper() if c.isalnum()) or "TICKER"
    return os.path.join(CACHE_DIR, f"fund_{safe}.json")


def _cache_get(ticker: str):
    """读取未过期缓存；校验核心字段，伪成功（全空）缓存视为无效并清除"""
    try:
        with open(_cache_path(ticker)) as f:
            data = _json.load(f)
        value = data.get("value")
        if (time.time() - data.get("ts", 0) <= CACHE_TTL
                and isinstance(value, dict) and _has_core(value)):
            return value
        # 过期或空壳缓存：删除，避免一直读到旧的全空结果
        try:
            os.remove(_cache_path(ticker))
        except OSError:
            pass
    except (FileNotFoundError, OSError, ValueError):
        pass
    return None


def _cache_set(ticker: str, value: dict) -> None:
    try:
        path = _cache_path(ticker)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            _json.dump({"ts": time.time(), "value": value}, f)
        os.replace(tmp, path)
    except OSError:
        pass


def _has_core(out: dict) -> bool:
    """校验解析结果是否拿到核心字段（防「有 source 但全空」的伪成功）"""
    return any(out.get(k) not in (None, [], "") for k in
               ("revenue", "net_income", "total_assets", "gross_margin"))


def _run_with_timeout(fn, args, timeout: float):
    """yfinance 等可能卡死的请求加硬超时（后台线程，超时即放弃）"""
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, *args)
    try:
        return fut.result(timeout=timeout)
    finally:
        # 关键：wait=False —— 超时后立即返回，不等待后台线程跑完
        ex.shutdown(wait=False)


def get_fundamentals(ticker: str, api_key: str = None) -> dict:
    """获取财务深度数据（缓存 → Twelve Data → yfinance → 新浪 → 空模型），永不抛异常"""
    cached = _cache_get(ticker)
    if isinstance(cached, dict):
        return cached
    for fetcher, args, tmo in (
            (_from_twelvedata, (ticker, api_key or _finance_data.API_KEY), None),
            (_from_stockanalysis, (ticker,), None),
            (_from_yfinance, (ticker,), 20),
            (_from_sina, (ticker,), None)):
        try:
            out = fetcher(*args) if tmo is None else _run_with_timeout(fetcher, args, tmo)
        except Exception:
            continue
        if out.get("source") != "none" and _has_core(out):
            out["symbol"] = str(ticker).upper()
            _cache_set(ticker, out)
            return out
    return _empty(ticker, "none")
