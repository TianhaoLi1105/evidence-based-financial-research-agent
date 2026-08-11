"""
Comparison Component
====================
多股对比：归一化走势图（起始日=100）+ 关键指标对比表。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from i18n import t
from utils import safe_float
from services.app_state import C


def render_normalized_chart(histories: dict, period_label: str):
    """
    渲染归一化对比图：每只股票以起始日收盘价为基准（=100），
    这样不同价格的股票可以在同一张图上公平比较涨跌幅。
    """
    if not histories:
        st.markdown(
            f'<p style="color:{C["text3"]};">{t("no_compare_data", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )
        return

    fig = go.Figure()
    colors = ["#0a84ff", "#34c759", "#ff9f0a", "#bf5af2", "#ff375f"]
    for i, (tk, hist) in enumerate(histories.items()):
        if not hist:
            continue
        df = pd.DataFrame(hist)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime")
        df["close"] = df["close"].astype(float)
        if len(df) < 2:
            continue
        base = df["close"].iloc[0]
        if not base:
            continue
        df["norm"] = df["close"] / base * 100
        fig.add_trace(go.Scatter(
            x=df["datetime"], y=df["norm"], mode="lines", name=tk,
            line=dict(width=2, color=colors[i % len(colors)]),
        ))

    if not fig.data:
        st.markdown(
            f'<p style="color:{C["text3"]};">{t("no_compare_data", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )
        return

    fig.update_layout(
        title=dict(
            text=t("compare_chart_title", st.session_state.lang, period=period_label),
            font=dict(size=14, color=C["text"]),
        ),
        xaxis=dict(title=t("xaxis_date", st.session_state.lang),
                   showgrid=False, tickfont=dict(size=11, color=C["text3"])),
        yaxis=dict(title=t("compare_yaxis", st.session_state.lang),
                   showgrid=True, gridcolor=C["border"],
                   tickfont=dict(size=11, color=C["text3"])),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=C["text"], font=dict(color=C["bg"], size=12)),
        margin=dict(l=20, r=20, t=60, b=70), height=480,
        plot_bgcolor=C["bg"], paper_bgcolor=C["bg"],
        legend=dict(orientation="h", yanchor="top", y=-0.18,
                    font=dict(color=C["text2"])),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_metrics_table(quotes: dict):
    """渲染关键指标对比表：行为指标，列为股票"""
    if not quotes:
        return

    rows = {
        t("current_price", st.session_state.lang): {},
        t("compare_change_pct", st.session_state.lang): {},
        t("compare_52w_high", st.session_state.lang): {},
        t("compare_exchange", st.session_state.lang): {},
    }

    for tk, q in quotes.items():
        close = safe_float(q.get("close"), 0)
        chg_p = safe_float(q.get("percent_change"), 0)
        fw = safe_float(q.get("fifty_two_week", {}).get("high"))

        rows[t("current_price", st.session_state.lang)][tk] = f"${close:.2f}"
        rows[t("compare_change_pct", st.session_state.lang)][tk] = f"{chg_p:+.2f}%"
        rows[t("compare_52w_high", st.session_state.lang)][tk] = f"${fw:.2f}" if fw else "N/A"
        rows[t("compare_exchange", st.session_state.lang)][tk] = q.get("exchange", "N/A")

    df = pd.DataFrame(rows).T
    st.dataframe(df, use_container_width=True)


def _fmt_money(v):
    """金额缩写：4.2e9 → $4.20B"""
    v = safe_float(v)
    if v is None:
        return "N/A"
    if abs(v) >= 1e12:
        return f"${v / 1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:,.0f}"


def render_financials_table(fundamentals: dict):
    """财务深度对比表（V3.4.1）：行为指标，列为股票。字段缺失显示 N/A。"""
    if not fundamentals:
        return
    lang = st.session_state.lang
    rows = {
        t("fin_market_cap", lang): {},
        t("fin_pe", lang): {},
        t("fin_revenue", lang): {},
        t("fin_net_income", lang): {},
        t("fin_revenue_growth", lang): {},
        t("fin_gross_margin", lang): {},
        t("fin_net_margin", lang): {},
        t("fin_roe", lang): {},
        t("fin_debt_to_equity", lang): {},
        t("fin_current_ratio", lang): {},
        t("fin_operating_cash_flow", lang): {},
    }
    for tk, f in fundamentals.items():
        if not isinstance(f, dict):
            continue
        mc = safe_float(f.get("market_cap"))
        pe = safe_float(f.get("pe_ratio"))
        rev = safe_float(f.get("revenue"))
        ni = safe_float(f.get("net_income"))
        yoy = safe_float(f.get("revenue_growth_yoy"))
        gm = safe_float(f.get("gross_margin"))
        nm = safe_float(f.get("net_margin"))
        roe = safe_float(f.get("roe"))
        d2e = safe_float(f.get("debt_to_equity"))
        cr = safe_float(f.get("current_ratio"))
        ocf = safe_float(f.get("operating_cash_flow"))

        rows[t("fin_market_cap", lang)][tk] = _fmt_money(mc)
        rows[t("fin_pe", lang)][tk] = f"{pe:.2f}" if pe is not None else "N/A"
        rows[t("fin_revenue", lang)][tk] = _fmt_money(rev)
        rows[t("fin_net_income", lang)][tk] = _fmt_money(ni)
        rows[t("fin_revenue_growth", lang)][tk] = f"{yoy:+.1f}%" if yoy is not None else "N/A"
        rows[t("fin_gross_margin", lang)][tk] = f"{gm:.1f}%" if gm is not None else "N/A"
        rows[t("fin_net_margin", lang)][tk] = f"{nm:.1f}%" if nm is not None else "N/A"
        rows[t("fin_roe", lang)][tk] = f"{roe:.1f}%" if roe is not None else "N/A"
        rows[t("fin_debt_to_equity", lang)][tk] = f"{d2e:.2f}" if d2e is not None else "N/A"
        rows[t("fin_current_ratio", lang)][tk] = f"{cr:.2f}" if cr is not None else "N/A"
        rows[t("fin_operating_cash_flow", lang)][tk] = _fmt_money(ocf)

    df = pd.DataFrame(rows).T
    st.dataframe(df, use_container_width=True)


def _source_label(source: str) -> str:
    """数据来源标识 → 本地化文案"""
    lang = st.session_state.lang
    return {
        "twelvedata": t("source_from_twelve", lang),
        "tencent": t("source_from_tencent", lang),
        "cache": t("source_from_cache", lang),
    }.get(source, "N/A")


def render_comparison(quotes: dict, histories: dict, period_label: str,
                      sources: dict = None, fundamentals: dict = None):
    """渲染多股对比结果：归一化图 + 指标表 + 财务对比（V3.4.1）+ 数据来源"""
    if not quotes and not histories:
        st.markdown(
            f'<p style="color:{C["text3"]};">{t("no_compare_data", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(f'<h2>{t("compare_price_trend", st.session_state.lang)}</h2>',
                unsafe_allow_html=True)
    render_normalized_chart(histories, period_label)

    st.markdown(f'<h2>{t("compare_metrics", st.session_state.lang)}</h2>',
                unsafe_allow_html=True)
    render_metrics_table(quotes)

    if fundamentals:
        st.markdown(f'<h2>{t("compare_financials", st.session_state.lang)}</h2>',
                    unsafe_allow_html=True)
        render_financials_table(fundamentals)

    if sources:
        items = " · ".join(
            f"{tk} ({_source_label(src)})" for tk, src in sources.items()
        )
        st.markdown(
            f'<p style="color:{C["text3"]};font-size:.75rem;margin-top:1rem;">'
            f'{t("compare_source_note", st.session_state.lang)} {items}</p>',
            unsafe_allow_html=True,
        )
