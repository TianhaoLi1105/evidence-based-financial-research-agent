"""
Sidebar Component
=================
侧边栏：股票搜索输入（带建议）、时间范围、K线周期、技术指标开关、分析按钮。
"""

import streamlit as st

from i18n import t, get_period_options
from data.stocks import STOCKS
from data.storage import load_config, save_config


def _watchlist() -> list:
    """读取自选股列表（本地配置）"""
    return load_config().get("watchlist", [])


def _add_watch(tk: str):
    wl = _watchlist()
    if tk and tk not in wl:
        wl.append(tk)
        save_config({"watchlist": wl})


def _remove_watch(tk: str):
    wl = _watchlist()
    if tk in wl:
        wl.remove(tk)
        save_config({"watchlist": wl})


def _select_watch(tk: str):
    """单股模式：点击自选股 → 填入输入框并自动分析"""
    st.session_state.ticker_input = tk
    st.session_state.auto_ticker = tk
    # 删除输入框 widget 状态，使本轮用 value= 重新渲染为 tk
    # （直接赋值会与 value= 冲突触发 Streamlit 警告）
    try:
        del st.session_state["ticker_input_widget"]
    except KeyError:
        pass


def _select_watch_compare(tk: str):
    """对比模式：点击自选股 → 加入对比列表"""
    if tk not in st.session_state.compare_tickers:
        st.session_state.compare_tickers.append(tk)


def _render_watchlist(mode: str):
    """渲染自选股区块（mode: single / compare）"""
    wl = _watchlist()
    if not wl:
        return
    st.markdown(
        f'<p style="font-size:.6875rem;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:.06em;'
        f'color:#98989d;margin:.8rem 0 .3rem;">'
        f'{t("watchlist", st.session_state.lang)}</p>',
        unsafe_allow_html=True,
    )
    for tk in list(wl):
        name = STOCKS.get(tk, tk)
        c1, c2 = st.columns([4, 1])
        with c1:
            label = f"{name}" if name != tk else tk
            if mode == "single":
                st.button(label, key=f"watch_{tk}", use_container_width=True,
                          on_click=_select_watch, args=(tk,))
            else:
                if st.button(label, key=f"watch_{tk}", use_container_width=True):
                    _select_watch_compare(tk)
        with c2:
            if st.button("✕", key=f"watch_rm_{tk}",
                         help=t("remove", st.session_state.lang)):
                _remove_watch(tk)


def render_sidebar() -> dict:
    """
    渲染单股分析的侧边栏，返回配置字典：
    {
        "ticker": 最终确定的股票代码,
        "period_days": 时间范围天数,
        "period_label": 时间范围显示文本,
        "interval": K线周期 ("1day"/"1week"/"1month"),
        "interval_label": 周期显示文本,
        "show_ma20": 是否显示 MA20,
        "show_ma60": 是否显示 MA60,
        "show_rsi": 是否显示 RSI,
        "run_btn": 是否点击了「分析」,
    }
    """
    with st.sidebar:
        st.markdown(
            f'<p class="sidebar-title">{t("settings", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )

        # ── 股票输入（支持名称或代码，带实时建议）──
        ticker_input = st.text_input(
            t("ticker_label", st.session_state.lang),
            value=st.session_state.ticker_input,
            placeholder=t("ticker_placeholder", st.session_state.lang),
            key="ticker_input_widget",
        ).strip().upper()
        if ticker_input != st.session_state.ticker_input:
            st.session_state.ticker_input = ticker_input

        query = ticker_input
        matches = [
            (name, tk) for tk, name in STOCKS.items()
            if (query and (query in tk or query.lower() in name.lower()))
        ]
        matches.sort(key=lambda x: (0 if x[1].startswith(query) else 1, x[0]))

        ticker = ticker_input
        if matches and not any(tk == query for _, tk in matches):
            match_opts = [f"{name} ({tk})" for name, tk in matches[:6]]
            sel_suggestion = st.selectbox(
                t("suggestions", st.session_state.lang), match_opts, index=None,
                placeholder=t("suggestions_placeholder", st.session_state.lang),
                label_visibility="collapsed",
            )
            if sel_suggestion:
                ticker = sel_suggestion.split(" (")[1].rstrip(")")
        elif not ticker_input:
            ticker = ""

        # ── 时间范围 ──
        popts = get_period_options(st.session_state.lang)
        plabels = list(popts.keys())
        p1y = t("period_1y", st.session_state.lang)
        def_idx = plabels.index(p1y) if p1y in plabels else 0
        sel_period = st.selectbox(
            t("period_label", st.session_state.lang), plabels, index=def_idx,
        )
        period_days = popts[sel_period]

        # ── K 线周期 ──
        interval_opts = {
            t("interval_day", st.session_state.lang): "1day",
            t("interval_week", st.session_state.lang): "1week",
            t("interval_month", st.session_state.lang): "1month",
        }
        interval_label = st.selectbox(
            t("interval_label", st.session_state.lang),
            list(interval_opts.keys()),
        )
        interval = interval_opts[interval_label]

        # ── 技术指标开关 ──
        st.markdown(
            f'<p style="font-size:.6875rem;font-weight:600;'
            f'text-transform:uppercase;letter-spacing:.06em;'
            f'color:#98989d;margin:.8rem 0 .3rem;">'
            f'{t("indicators_label", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )
        ind_c1, ind_c2 = st.columns(2)
        with ind_c1:
            show_ma20 = st.checkbox("MA20", value=True)
            show_ema = st.checkbox("EMA12/26", value=True)
            show_macd = st.checkbox("MACD", value=True)
        with ind_c2:
            show_ma60 = st.checkbox("MA60", value=True)
            show_boll = st.checkbox("BOLL", value=True)
            show_rsi = st.checkbox("RSI14", value=True)

        # ── 加入自选股 ──
        if ticker and ticker not in _watchlist():
            if st.button(t("add_watch", st.session_state.lang),
                         use_container_width=True):
                _add_watch(ticker)

        _render_watchlist("single")

        run_btn = st.button(t("run_button", st.session_state.lang), type="primary")

    return {
        "ticker": ticker,
        "period_days": period_days,
        "period_label": sel_period,
        "interval": interval,
        "interval_label": interval_label,
        "show_ma20": show_ma20,
        "show_ma60": show_ma60,
        "show_ema": show_ema,
        "show_boll": show_boll,
        "show_rsi": show_rsi,
        "show_macd": show_macd,
        "run_btn": run_btn,
    }


def render_compare_sidebar():
    """
    渲染多股对比的侧边栏：添加/删除股票 + 时间范围 + 对比按钮。

    返回 (tickers, period_days, period_label, compare_clicked)：
    - tickers: 已选股票代码列表
    - compare_clicked: 是否点击了「开始对比」按钮
    """
    with st.sidebar:
        st.markdown(
            f'<p class="sidebar-title">{t("settings", st.session_state.lang)}</p>',
            unsafe_allow_html=True,
        )

        # ── 添加股票 ──
        new_ticker = st.text_input(
            t("compare_add_label", st.session_state.lang),
            placeholder=t("compare_add_placeholder", st.session_state.lang),
        ).strip().upper()
        if st.button(t("compare_add_btn", st.session_state.lang),
                     use_container_width=True) and new_ticker:
            if new_ticker not in st.session_state.compare_tickers:
                st.session_state.compare_tickers.append(new_ticker)

        # ── 已选股票列表（带删除）──
        if st.session_state.compare_tickers:
            st.markdown(
                f'<p style="font-size:.6875rem;font-weight:600;'
                f'text-transform:uppercase;letter-spacing:.06em;'
                f'color:#98989d;margin:.8rem 0 .3rem;">'
                f'{t("compare_selected", st.session_state.lang)}</p>',
                unsafe_allow_html=True,
            )
            for tk in list(st.session_state.compare_tickers):
                c1, c2 = st.columns([0.16, 1])
                with c1:
                    if st.button("✕", key=f"cmp_rm_{tk}",
                                 help=t("remove", st.session_state.lang)):
                        st.session_state.compare_tickers.remove(tk)
                with c2:
                    st.markdown(
                        f'<p style="margin:0;padding-left:14px;padding-top:.35rem;'
                        f'color:#f5f5f7;font-weight:500;font-size:.875rem;">{tk}</p>',
                        unsafe_allow_html=True,
                    )

        # ── K 线周期 ──
        interval_opts = {
            t("interval_day", st.session_state.lang): "1day",
            t("interval_week", st.session_state.lang): "1week",
            t("interval_month", st.session_state.lang): "1month",
        }
        interval_label = st.selectbox(
            t("interval_label", st.session_state.lang),
            list(interval_opts.keys()),
        )
        interval = interval_opts[interval_label]

        # ── 时间范围 ──
        popts = get_period_options(st.session_state.lang)
        plabels = list(popts.keys())
        p1y = t("period_1y", st.session_state.lang)
        def_idx = plabels.index(p1y) if p1y in plabels else 0
        sel_period = st.selectbox(
            t("period_label", st.session_state.lang), plabels, index=def_idx,
        )
        period_days = popts[sel_period]

        _render_watchlist("compare")

        st.markdown("<br>", unsafe_allow_html=True)
        compare_btn = st.button(t("compare_button", st.session_state.lang),
                                type="primary")

    return st.session_state.compare_tickers, period_days, interval, sel_period, compare_btn
