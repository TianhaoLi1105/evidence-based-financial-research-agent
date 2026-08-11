"""
Results Component
=================
分析结果页：组合公司概况、指标卡片、K 线图（含技术指标）、财务数据、数据来源。
"""

import csv
import io

import streamlit as st
from datetime import datetime

from i18n import t
from components.cards import render_metric_cards, render_financials
from components.charts import render_price_chart
from components.profile import render_company_profile


def _fmt_price(val) -> str:
    """价格统一保留两位小数（行业惯例，同时消除 API 浮点噪声）"""
    try:
        return f"{float(val):.2f}"
    except (TypeError, ValueError):
        return ""


def _fmt_volume(val) -> str:
    """成交量输出为整数（不加千分位，保持 CSV 数字可计算）"""
    try:
        return f"{int(float(val)):d}"
    except (TypeError, ValueError):
        return ""


def _kline_csv(rows: list) -> str:
    """把 K 线列表转为 CSV 文本（价格两位小数、成交量整数）"""
    buf = io.StringIO()
    fields = ["datetime", "open", "high", "low", "close", "volume"]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "datetime": r.get("datetime"),
            "open": _fmt_price(r.get("open")),
            "high": _fmt_price(r.get("high")),
            "low": _fmt_price(r.get("low")),
            "close": _fmt_price(r.get("close")),
            "volume": _fmt_volume(r.get("volume")),
        })
    return buf.getvalue()


def render_results(data: dict):
    """
    渲染分析结果。

    data 结构：
    {
        "quote": {...}, "stats": {...}, "hist": [...], "profile": {...},
        "indicators": {...},
        "ticker": "AAPL", "period_label": "1 Year",
        "interval_label": "日K", "show_ma20": True, "show_ma60": True, "show_rsi": True,
    }
    """
    quote, stats, hist, profile = (
        data["quote"], data["stats"], data["hist"], data.get("profile", {}),
    )
    indicators = data.get("indicators", {})
    tk, sp = data["ticker"], data["period_label"]
    interval_label = data.get("interval_label", "")
    name = quote.get("name", tk)

    st.markdown(
        f'<h2 style="border-bottom:none;padding-bottom:0;margin-bottom:1rem;">{name}</h2>',
        unsafe_allow_html=True,
    )

    # ── 公司概况 ──
    render_company_profile(profile)

    # ── 关键指标卡片 ──
    render_metric_cards(quote, stats)

    # ── K 线图（蜡烛图 + 均线 + RSI）──
    cc1, cc2 = st.columns([6, 1])
    with cc1:
        st.markdown(f'<h2>{t("price_chart", st.session_state.lang)}</h2>',
                    unsafe_allow_html=True)
    with cc2:
        if hist:
            st.download_button(
                t("download_csv", st.session_state.lang),
                data=_kline_csv(hist),
                file_name=f"{tk}_{data.get('interval', '1day')}_kline.csv",
                mime="text/csv",
            )
    render_price_chart(
        hist, indicators, tk, sp, interval_label,
        show_ma20=data.get("show_ma20", True),
        show_ma60=data.get("show_ma60", True),
        show_ema=data.get("show_ema", True),
        show_boll=data.get("show_boll", True),
        show_macd=data.get("show_macd", True),
        show_rsi=data.get("show_rsi", True),
    )

    # ── 财务数据 ──
    st.markdown(f'<h2>{t("financial_data", st.session_state.lang)}</h2>', unsafe_allow_html=True)
    render_financials(stats)

    # ── 数据来源 ──
    st.markdown(
        f'<h2 style="margin-top:2.5rem;">{t("data_sources", st.session_state.lang)}</h2>',
        unsafe_allow_html=True,
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lang = st.session_state.lang
    source_labels = {
        "twelvedata": t("source_from_twelve", lang),
        "tencent": t("source_from_tencent", lang),
        "cache": t("source_from_cache", lang),
    }
    hist_source = source_labels.get(data.get("hist_source"), t("source_from_twelve", lang))
    quote_source = source_labels.get(data.get("quote_source"), t("source_from_twelve", lang))
    st.markdown(f"""
    <div class="source-item"><strong>{t("source_price", st.session_state.lang)}:</strong> {hist_source} | {t("source_time", period=sp, lang=lang)} | {t("source_updated", time=now, lang=lang)}</div>
    <div class="source-item"><strong>{t("quote_source", st.session_state.lang)}:</strong> {quote_source}</div>
    <div class="source-item"><strong>{t("source_company", st.session_state.lang)}:</strong> Twelve Data | {name}</div>
    """, unsafe_allow_html=True)
    st.markdown(f'<p class="disclaimer">{t("disclaimer", st.session_state.lang)}</p>',
                unsafe_allow_html=True)
