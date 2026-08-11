"""
Technical Indicators Module
============================
本地计算技术指标（SMA / RSI），不再消耗 API 调用次数。

输入统一为 K 线列表：[{"datetime": "2024-01-02", "open": ..., "high": ...,
"low": ..., "close": ..., "volume": ...}, ...]
输出与 charts.py 期望的字段名保持一致：
    indicators = {"ma20": [...], "ma60": [...], "rsi14": [...]}
其中每条为 {"datetime": ..., "ma20": ...} 形式。
"""

import pandas as pd

from utils import safe_float


def _closes(values: list) -> pd.Series:
    """提取收盘价序列，非法值置为 NaN"""
    return pd.Series(
        [safe_float(v.get("close"), float("nan")) for v in values],
        dtype="float64",
    )


def compute_sma(values: list, period: int, key: str = "ma") -> list:
    """简单移动平均线：从第 period 根 K 线开始有值"""
    closes = _closes(values)
    sma = closes.rolling(period).mean()
    out = []
    for v, val in zip(values, sma):
        if pd.notna(val):
            out.append({"datetime": v.get("datetime"), key: round(float(val), 4)})
    return out


def compute_rsi(values: list, period: int = 14) -> list:
    """相对强弱指标（Wilder 平滑），从第 period+1 根 K 线开始有值"""
    closes = _closes(values)
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rsi = pd.Series(float("nan"), index=closes.index)
    valid = avg_loss != 0
    rsi.loc[valid] = 100 - 100 / (1 + avg_gain[valid] / avg_loss[valid])
    # 平均亏损为 0：持续上涨→RSI 100，横盘→RSI 50
    rsi.loc[~valid & (avg_gain > 0)] = 100.0
    rsi.loc[~valid & (avg_gain == 0)] = 50.0

    out = []
    for v, val in zip(values, rsi):
        if pd.notna(val):
            out.append({"datetime": v.get("datetime"), "rsi14": round(float(val), 2)})
    return out


def compute_ema(values: list, period: int, key: str = "ema") -> list:
    """指数移动平均线：从第一根 K 线起有值（以首值作种子）"""
    closes = _closes(values)
    ema = closes.ewm(span=period, adjust=False).mean()
    out = []
    for v, val in zip(values, ema):
        if pd.notna(val):
            out.append({"datetime": v.get("datetime"), key: round(float(val), 4)})
    return out


def compute_macd(values: list, fast: int = 12, slow: int = 26,
                 signal: int = 9) -> dict:
    """
    MACD 指标：DIF = EMA12 - EMA26；DEA = DIF 的 EMA9；柱 = DIF - DEA。

    返回 {"dif": [...], "dea": [...], "hist": [...]}，每条为
    {"datetime", "dif"/"dea"/"hist"} 形式。
    """
    closes = _closes(values)
    dif = closes.ewm(span=fast, adjust=False).mean() - closes.ewm(span=slow, adjust=False).mean()
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = dif - dea

    dif_rows, dea_rows, hist_rows = [], [], []
    for v, d, e, h in zip(values, dif, dea, hist):
        if pd.isna(d):
            continue
        dif_rows.append({"datetime": v.get("datetime"), "dif": round(float(d), 4)})
        dea_rows.append({"datetime": v.get("datetime"), "dea": round(float(e), 4)})
        hist_rows.append({"datetime": v.get("datetime"), "hist": round(float(h), 4)})
    return {"dif": dif_rows, "dea": dea_rows, "hist": hist_rows}


def compute_boll(values: list, period: int = 20, mult: float = 2.0) -> dict:
    """
    布林带：中轨 = MA(period)，上下轨 = 中轨 ± mult × 标准差。

    返回 {"middle": [...], "upper": [...], "lower": [...]}。
    """
    closes = _closes(values)
    mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()

    middle_rows, upper_rows, lower_rows = [], [], []
    for v, m, sd in zip(values, mid, std):
        if pd.isna(m) or pd.isna(sd):
            continue
        middle_rows.append({"datetime": v.get("datetime"), "middle": round(float(m), 4)})
        upper_rows.append({"datetime": v.get("datetime"), "upper": round(float(m + mult * sd), 4)})
        lower_rows.append({"datetime": v.get("datetime"), "lower": round(float(m - mult * sd), 4)})
    return {"middle": middle_rows, "upper": upper_rows, "lower": lower_rows}


def compute_indicators(values: list) -> dict:
    """一次算完全部指标：MA / EMA / RSI / MACD / BOLL"""
    return {
        "ma20": compute_sma(values, 20, "ma20"),
        "ma60": compute_sma(values, 60, "ma60"),
        "ema12": compute_ema(values, 12, "ema12"),
        "ema26": compute_ema(values, 26, "ema26"),
        "rsi14": compute_rsi(values, 14),
        "macd": compute_macd(values),
        "boll": compute_boll(values),
    }
