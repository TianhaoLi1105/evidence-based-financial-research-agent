"""
Charts Component
================
图表组件：K 线图（蜡烛图 + 均线叠加 + RSI 子图）。
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from i18n import t
from services.app_state import C


def _to_df(rows: list) -> pd.DataFrame:
    """把 API 返回的 values 列表转成 DataFrame"""
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def _merge_trace(df: pd.DataFrame, rows: list, key: str):
    """把指标行按日期左连接到主图 DataFrame，返回合并后的 DataFrame"""
    mdf = _to_df(rows)
    mdf[key] = mdf[key].astype(float)
    return pd.merge(df[["datetime"]], mdf, on="datetime", how="left")


def render_price_chart(hist: list, indicators: dict, ticker: str,
                       period_label: str, interval_label: str,
                       show_ma20: bool = True, show_ma60: bool = True,
                       show_rsi: bool = True, show_ema: bool = True,
                       show_boll: bool = True, show_macd: bool = True):
    """
    渲染 K 线图：主图蜡烛线 + 均线/布林带叠加，
    副图：成交量 + （可选 MACD）+（可选 RSI）。
    """
    if not hist:
        st.markdown(
            f'<p style="color:{C["text3"]};">{t("no_chart_data", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )
        return

    df = _to_df(hist)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

    # 副图开关：成交量固定，MACD / RSI 可选
    show_macd = show_macd and bool(indicators.get("macd", {}).get("dif"))
    show_rsi = show_rsi and bool(indicators.get("rsi14"))
    n_rows = 2 + int(show_macd) + int(show_rsi)
    if n_rows == 2:
        row_heights = [0.72, 0.28]
    elif n_rows == 3:
        row_heights = [0.60, 0.16, 0.24]
    else:
        row_heights = [0.55, 0.14, 0.15, 0.16]
    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        row_heights=row_heights, vertical_spacing=0.04,
    )

    # ── 主图：蜡烛图 ──
    fig.add_trace(go.Candlestick(
        x=df["datetime"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="OHLC",
        increasing_line_color=C["green"], increasing_fillcolor=C["green"],
        decreasing_line_color=C["red"], decreasing_fillcolor=C["red"],
    ), row=1, col=1)

    # ── 均线叠加（MA20 / MA60 / EMA12 / EMA26）──
    line_specs = {
        "ma20": ("#ff9f0a", show_ma20, 1.8),
        "ma60": ("#bf5af2", show_ma60, 1.8),
        "ema12": ("#64d2ff", show_ema, 1.4),
        "ema26": ("#ffd60a", show_ema, 1.4),
    }
    for key, (color, show, width) in line_specs.items():
        rows = indicators.get(key, [])
        if show and rows:
            merged = _merge_trace(df, rows, key)
            fig.add_trace(go.Scatter(
                x=merged["datetime"], y=merged[key], mode="lines",
                name=key.upper(),
                line=dict(color=color, width=width),
            ), row=1, col=1)

    # ── 布林带（BOLL 上/中/下轨）──
    if show_boll and indicators.get("boll", {}).get("middle"):
        boll = indicators["boll"]
        boll_specs = {
            "upper": ("dash", t("boll_upper", st.session_state.lang)),
            "middle": ("solid", t("boll_middle", st.session_state.lang)),
            "lower": ("dash", t("boll_lower", st.session_state.lang)),
        }
        for key, (dash, label) in boll_specs.items():
            rows = boll.get(key, [])
            if rows:
                merged = _merge_trace(df, rows, key)
                fig.add_trace(go.Scatter(
                    x=merged["datetime"], y=merged[key], mode="lines",
                    name=label, showlegend=True,
                    line=dict(color="#8e8e93", width=1.1, dash=dash),
                ), row=1, col=1)

    # ── 成交量（副图，固定 row2）──
    vol_colors = [C["green"] if c >= o else C["red"]
                  for o, c in zip(df["open"], df["close"])]
    fig.add_trace(go.Bar(
        x=df["datetime"], y=df["volume"], name=t("volume_label", st.session_state.lang),
        marker_color=vol_colors, opacity=0.55,
    ), row=2, col=1)

    next_row = 3

    # ── MACD 副图 ──
    if show_macd:
        macd = indicators["macd"]
        dif = _merge_trace(df, macd["dif"], "dif")
        dea = _merge_trace(df, macd["dea"], "dea")
        hist_df = _merge_trace(df, macd["hist"], "hist")
        hist_colors = [C["green"] if v >= 0 else C["red"]
                       for v in hist_df["hist"].fillna(0)]
        fig.add_trace(go.Bar(
            x=hist_df["datetime"], y=hist_df["hist"], name="MACD",
            marker_color=hist_colors, opacity=0.6,
        ), row=next_row, col=1)
        fig.add_trace(go.Scatter(
            x=dif["datetime"], y=dif["dif"], mode="lines",
            name="DIF", line=dict(color="#0a84ff", width=1.4),
        ), row=next_row, col=1)
        fig.add_trace(go.Scatter(
            x=dea["datetime"], y=dea["dea"], mode="lines",
            name="DEA", line=dict(color="#ff9f0a", width=1.4),
        ), row=next_row, col=1)
        next_row += 1

    # ── RSI 副图 ──
    if show_rsi:
        rdf = _to_df(indicators["rsi14"])
        rdf["rsi14"] = rdf["rsi14"].astype(float)
        rdf = pd.merge(df[["datetime"]], rdf, on="datetime", how="left")
        fig.add_trace(go.Scatter(
            x=rdf["datetime"], y=rdf["rsi14"], mode="lines",
            name=t("rsi_label", st.session_state.lang),
            line=dict(color="#0a84ff", width=1.5),
        ), row=next_row, col=1)
        # 超买/超卖参考线
        fig.add_hline(y=70, line_dash="dot", line_color=C["border"],
                      row=next_row, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color=C["border"],
                      row=next_row, col=1)

    # ── 布局 ──
    title_text = t("price_chart_title", st.session_state.lang,
                   ticker=ticker, period=period_label)
    if interval_label:
        title_text = f"{title_text} · {interval_label}"

    fig.update_layout(
        title=dict(
            text=title_text, x=0.02, xanchor="left",
            font=dict(size=15, color=C["text"], family="Inter, -apple-system, sans-serif"),
        ),
        xaxis_rangeslider_visible=False,
        height=520 + 50 * (n_rows - 2),
        margin=dict(l=20, r=20, t=70, b=120),
        plot_bgcolor=C["bg"], paper_bgcolor=C["bg"],
        hovermode="x unified",
        hoverlabel=dict(bgcolor=C["text"], font=dict(color=C["bg"], size=12)),
        legend=dict(
            orientation="h", x=0.02, xanchor="left",
            y=-0.18, yanchor="top",
            font=dict(size=11.5, color=C["text2"]),
            bgcolor="rgba(28,28,30,0.65)", bordercolor=C["border"],
            borderwidth=1, itemsizing="constant",
        ),
    )
    fig.update_xaxes(
        showgrid=False, tickfont=dict(size=11, color=C["text3"]),
        rangeslider_visible=False,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=C["border"], tickfont=dict(size=11, color=C["text3"]),
    )
    fig.update_yaxes(title_text=t("yaxis_price", st.session_state.lang), row=1, col=1)
    fig.update_yaxes(title_text=t("volume_label", st.session_state.lang),
                     tickformat=".2s", showgrid=False, row=2, col=1)
    row = 3
    if show_macd:
        fig.update_yaxes(title_text="MACD", showgrid=False, row=row, col=1)
        row += 1
    if show_rsi:
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=row, col=1)

    st.plotly_chart(fig, use_container_width=True)
