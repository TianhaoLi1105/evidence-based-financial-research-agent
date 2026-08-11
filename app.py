"""
Evidence-Based Financial Research Agent
========================================
入口文件：初始化应用，渲染页面主流程（单股分析 / 多股对比）。
"""

import streamlit as st

from i18n import t
from services.app_state import init_app, C
from components.header import render_header
from components.sidebar import render_sidebar, render_compare_sidebar
from components.results import render_results
from components.comparison import render_comparison
from components.market import render_market_overview
from components.chat import render_ai_panel
from services.stock_service import fetch_data, fetch_compare_data
from data.preferences import record_stock
from data.fundamentals import get_fundamentals, valuation_fallback

# ─── 初始化（配置 / session_state / 主题）────────────────
init_app()

# 对比模式的已选股票列表（session_state 持久化）
if "compare_tickers" not in st.session_state:
    st.session_state.compare_tickers = []
if "mode" not in st.session_state:
    st.session_state.mode = "single"
if "compare_cached" not in st.session_state:
    st.session_state.compare_cached = None

# ─── 页面结构 ────────────────────────────────────────────
render_header()

# ─── 市场概览（三大指数卡片）──────────────────────────────
render_market_overview()

# ─── 模式切换（单股分析 / 多股对比）──────────────────────
mode_c1, mode_c2, mode_c3 = st.columns([1.4, 1.2, 4])
with mode_c1:
    st.button(
        t("mode_single", st.session_state.lang),
        key="mode_single_btn", use_container_width=True,
        type="primary" if st.session_state.mode == "single" else "secondary",
        on_click=lambda: setattr(st.session_state, "mode", "single"),
    )
with mode_c2:
    st.button(
        t("mode_compare", st.session_state.lang),
        key="mode_compare_btn", use_container_width=True,
        type="primary" if st.session_state.mode == "compare" else "secondary",
        on_click=lambda: setattr(st.session_state, "mode", "compare"),
    )

st.markdown("<br>", unsafe_allow_html=True)

# ─── 主流程 ──────────────────────────────────────────────
if st.session_state.mode == "compare":
    # ══ 多股对比模式 ══
    tickers, period_days, interval, sel_period, compare_btn = render_compare_sidebar()

    if compare_btn:
        if len(tickers) < 2:
            st.warning(t("compare_need_two", st.session_state.lang))
        else:
            with st.spinner(t("compare_fetching", st.session_state.lang)):
                try:
                    quotes, histories, sources = fetch_compare_data(
                        tickers, period_days, interval,
                    )
                    # V3.4.1：逐只拉财务深度数据（有本地 24h 缓存，失败不阻断对比）
                    fundamentals = {}
                    for tk in tickers:
                        f = get_fundamentals(tk)
                        if f.get("source") != "none":
                            # V3.4.2：免费 /quote 无市值/PE → 用兜底源补齐财务表估值行
                            val = valuation_fallback(tk)
                            f = dict(f, market_cap=val.get("market_cap"),
                                     pe_ratio=val.get("pe_ratio"))
                            fundamentals[tk] = f
                    st.session_state.compare_cached = {
                        "quotes": quotes,
                        "histories": histories,
                        "sources": sources,
                        "fundamentals": fundamentals,
                        "period_label": sel_period,
                    }
                    render_comparison(quotes, histories, sel_period, sources=sources,
                                      fundamentals=fundamentals)
                    # V3.3.3 个性化记忆：记录对比的每只股票
                    for tk in tickers:
                        record_stock(tk)
                except Exception as e:
                    st.session_state.compare_cached = None
                    em = str(e)
                    st.error(f"{em}")
                    if "401" in em:
                        st.info(t("error_401", st.session_state.lang))
                    elif "403" in em:
                        st.info(t("error_403", st.session_state.lang))
                    else:
                        st.info(t("error_generic", st.session_state.lang))

    elif st.session_state.compare_cached is not None:
        st.session_state.compare_cached["period_label"] = sel_period
        cached = st.session_state.compare_cached
        render_comparison(cached["quotes"], cached["histories"], cached["period_label"],
                          sources=cached.get("sources"),
                          fundamentals=cached.get("fundamentals"))

    else:
        st.markdown(
            f'<p style="color:{C["text3"]};">{t("compare_hint", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )

else:
    # ══ 单股分析模式 ══
    cfg = render_sidebar()
    # 自选股按钮在 sidebar 内触发后设置 auto_ticker，这里取走
    auto_ticker = st.session_state.pop("auto_ticker", None)
    ticker = cfg["ticker"]
    period_days = cfg["period_days"]
    sel_period = cfg["period_label"]
    run_btn = cfg["run_btn"]

    # 自选股点击 → 自动分析；否则用输入框的 ticker
    target = auto_ticker or ticker

    if run_btn or auto_ticker:
        if not target:
            st.warning(t("ticker_required", st.session_state.lang))
        else:
            with st.spinner(t("fetching", st.session_state.lang, ticker=target)):
                try:
                    quote, stats, hist, profile, indicators, hist_source, quote_source = fetch_data(
                        target, period_days, cfg["interval"],
                    )
                    st.session_state.cached = {
                        "quote": quote,
                        "stats": stats,
                        "hist": hist,
                        "profile": profile,
                        "indicators": indicators,
                        "hist_source": hist_source,
                        "quote_source": quote_source,
                        "ticker": target,
                        "period_days": period_days,
                        "interval": cfg["interval"],
                        "period_label": sel_period,
                        "interval_label": cfg["interval_label"],
                        "show_ma20": cfg["show_ma20"],
                        "show_ma60": cfg["show_ma60"],
                        "show_ema": cfg["show_ema"],
                        "show_boll": cfg["show_boll"],
                        "show_rsi": cfg["show_rsi"],
                        "show_macd": cfg["show_macd"],
                    }
                    render_results(st.session_state.cached)
                    # V3.3.3 个性化记忆：记录这次分析的股票
                    record_stock(target)
                except Exception as e:
                    st.session_state.cached = None
                    em = str(e)
                    st.error(f"{em}")
                    if "401" in em:
                        st.info(t("error_401", st.session_state.lang))
                    elif "403" in em:
                        st.info(t("error_403", st.session_state.lang))
                    else:
                        st.info(t("error_generic", st.session_state.lang))

    elif st.session_state.cached is not None:
        cached = st.session_state.cached
        # 指标开关只影响显示，数据已包含全部指标，可即时生效
        cached["show_ma20"] = cfg["show_ma20"]
        cached["show_ma60"] = cfg["show_ma60"]
        cached["show_ema"] = cfg["show_ema"]
        cached["show_boll"] = cfg["show_boll"]
        cached["show_rsi"] = cfg["show_rsi"]
        cached["show_macd"] = cfg["show_macd"]
        # 时间范围 / K线周期决定数据本身：设置与缓存数据一致时才同步标题（兼容语言切换）
        if (cfg["period_days"] == cached.get("period_days")
                and cfg["interval"] == cached.get("interval")):
            cached["period_label"] = sel_period
            cached["interval_label"] = cfg["interval_label"]
        else:
            st.markdown(
                f'<p style="font-size:.8125rem;color:{C["accent"]};'
                f'margin-bottom:.5rem;">'
                f'&#9654; {t("settings_changed_hint", st.session_state.lang)}</p>',
                unsafe_allow_html=True,
            )
        render_results(cached)

    else:
        # ── 欢迎页（未查询时）──
        st.markdown(
            f'<p style="color:{C["text3"]};margin-bottom:2rem;">'
            f'{t("welcome_hint", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )
        st.markdown(f"""
        <div class="welcome-grid">
            <div class="welcome-card"><h3>{t("quick_start", st.session_state.lang)}</h3>
                <ol><li>{t("step_1", st.session_state.lang)}</li><li>{t("step_2", st.session_state.lang)}</li><li>{t("step_3", st.session_state.lang)}</li></ol></div>
            <div class="welcome-card"><h3>{t("what_you_see", st.session_state.lang)}</h3>
                <ul><li>{t("feature_1", st.session_state.lang)}</li><li>{t("feature_2", st.session_state.lang)}</li><li>{t("feature_3", st.session_state.lang)}</li><li>{t("feature_4", st.session_state.lang)}</li></ul></div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(
            f'<p style="font-size:0.8rem;color:{C["text3"]};">'
            f'{t("data_source_note", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )

# ─── AI 助手（右下角悬浮按钮 + 抽屉，组件 iframe 承载）──
render_ai_panel()
