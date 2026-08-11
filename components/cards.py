"""
Cards Component
===============
指标卡片与财务数据表格组件。
"""

import pandas as pd
import streamlit as st

from i18n import t
from utils import format_large_num, safe_float


def render_metric_cards(quote: dict, stats: dict):
    """渲染顶部 4 个指标卡片"""
    has_stats = bool(stats)

    c1, c2, c3, c4 = st.columns(4)
    close = safe_float(quote.get("close"), 0)
    chg = safe_float(quote.get("change"), 0)
    chg_p = safe_float(quote.get("percent_change"), 0)

    with c1:
        st.metric(
            t("current_price", st.session_state.lang),
            f"${close:.2f}",
            delta=f"{chg:+.2f} ({chg_p:+.2f}%)",
        )

    if has_stats:
        vm = stats.get("valuations_metrics", {})
        div = stats.get("dividends_and_splits", {})
        is_fallback = bool(stats.get("quote_fallback"))
        with c2:
            st.metric(t("market_cap", st.session_state.lang),
                      format_large_num(vm.get("market_capitalization")))
        with c3:
            pe = vm.get("trailing_pe")
            st.metric(t("pe_ratio", st.session_state.lang),
                      f"{float(pe):.2f}" if pe else "N/A")
        with c4:
            if is_fallback:
                # 备用源无股息率，改用 52 周最高价
                fw = safe_float(quote.get("fifty_two_week", {}).get("high"))
                st.metric(t("high_52w", st.session_state.lang),
                          f"${fw:.2f}" if fw else "N/A")
            else:
                dy = safe_float(div.get("forward_annual_dividend_yield"), 0)
                st.metric(t("div_yield", st.session_state.lang),
                          f"{dy*100:.2f}%" if dy else "N/A")
    else:
        fw = safe_float(quote.get("fifty_two_week", {}).get("high"))
        with c2:
            st.metric(t("high_52w", st.session_state.lang),
                      f"${fw:.2f}" if fw else "N/A")
        with c3:
            st.metric(t("exchange_label", st.session_state.lang),
                      quote.get("exchange", "N/A"))
        with c4:
            st.metric(t("currency_label", st.session_state.lang),
                      quote.get("currency", "USD"))


def _fmt_pe(pe) -> str:
    """PE 显示两位小数，空值显示 N/A"""
    return f"{float(pe):.2f}" if pe else "N/A"


def _fmt_usd(val) -> str:
    """美元金额格式化"""
    return f"${float(val):,.2f}" if val else "N/A"


def _deep_financial_rows(stats: dict, lang: str) -> list:
    """V3.4.5：四源深度财务行（免费 Key 主路径；字段缺失自动跳过）"""
    f = stats.get("deep_fundamentals") or {}
    if not isinstance(f, dict) or f.get("source") in (None, "none"):
        return []
    rows = []

    def add(key, label, fmt):
        v = f.get(key)
        if v is None:
            return
        rows.append((label, fmt(v)))

    add("revenue", t("fin_revenue", lang), format_large_num)
    add("net_income", t("fin_net_income", lang), format_large_num)
    add("gross_margin", t("fin_gross_margin", lang),
        lambda v: f"{v:.1f}%")
    add("net_margin", t("fin_net_margin", lang),
        lambda v: f"{v:.1f}%")
    add("revenue_growth_yoy", t("fin_revenue_growth", lang),
        lambda v: f"{v:+.1f}%")
    add("net_income_growth_yoy", t("fin_net_income_growth", lang),
        lambda v: f"{v:+.1f}%")
    add("total_assets", t("fin_total_assets", lang), format_large_num)
    add("total_liabilities", t("fin_total_liabilities", lang), format_large_num)
    add("stockholders_equity", t("fin_equity", lang), format_large_num)
    add("debt_to_equity", t("fin_debt_to_equity", lang),
        lambda v: f"{v:.2f}")
    add("current_ratio", t("fin_current_ratio", lang),
        lambda v: f"{v:.2f}")
    add("operating_cash_flow", t("fin_operating_cash_flow", lang),
        format_large_num)
    add("eps", t("fin_eps", lang), lambda v: f"${v:.2f}")
    add("roe", t("fin_roe", lang), lambda v: f"{v:.1f}%")
    return rows


def render_financials(stats: dict):
    """渲染财务数据表格（Pro 套餐可用；免费 Key 显示备用估值表）"""
    from services.app_state import C
    rows = []
    if stats:
        fin = stats.get("financials", {})
        inc = fin.get("income_statement", {})
        if inc:
            rows.append((t("revenue_ttm", st.session_state.lang),
                         format_large_num(inc.get("revenue_ttm"))))
            rows.append((t("gross_profit_ttm", st.session_state.lang),
                         format_large_num(inc.get("gross_profit_ttm"))))
            rows.append((t("net_income_ttm", st.session_state.lang),
                         format_large_num(inc.get("net_income_to_common_ttm"))))
            eps = safe_float(inc.get("diluted_eps_ttm"))
            if eps:
                rows.append((t("eps_ttm", st.session_state.lang), f"${eps:.2f}"))
            ebitda = inc.get("ebitda")
            if ebitda:
                rows.append((t("ebitda", st.session_state.lang),
                             format_large_num(ebitda)))
        bs = fin.get("balance_sheet", {})
        if bs:
            cash = bs.get("total_cash_mrq")
            if cash:
                rows.append((t("total_cash", st.session_state.lang),
                             format_large_num(cash)))
            debt = bs.get("total_debt_mrq")
            if debt:
                rows.append((t("total_debt", st.session_state.lang),
                             format_large_num(debt)))
    else:
        st.markdown(
            f'<p style="color:{C["text3"]};">'
            f'{t("pro_upgrade_hint", st.session_state.lang)} '
            f'<a href="https://twelvedata.com/pricing" target="_blank" '
            f'style="color:{C["accent"]};">Twelve Data Pro plan</a>.</p>',
            unsafe_allow_html=True,
        )

    if rows:
        st.dataframe(
            pd.DataFrame(
                rows,
                columns=[t("indicator", st.session_state.lang),
                         t("value", st.session_state.lang)],
            ),
            use_container_width=True, hide_index=True,
        )
    elif stats and _deep_financial_rows(stats, st.session_state.lang):
        # V3.4.5：无 Pro 财报时展示四源深度财务（营收/净利/负债率等）
        st.dataframe(
            pd.DataFrame(
                _deep_financial_rows(stats, st.session_state.lang),
                columns=[t("indicator", st.session_state.lang),
                         t("value", st.session_state.lang)],
            ),
            use_container_width=True, hide_index=True,
        )
    elif stats and stats.get("quote_fallback"):
        # 无 Pro 财报时展示备用源关键估值数据
        fb = stats["quote_fallback"]
        fw = fb.get("fifty_two_week") or {}
        vrows = [
            (t("market_cap", st.session_state.lang),
             format_large_num(stats.get("valuations_metrics", {}).get("market_capitalization"))),
            (t("pe_ratio", st.session_state.lang),
             _fmt_pe(stats.get("valuations_metrics", {}).get("trailing_pe"))),
            (t("high_52w", st.session_state.lang),
             _fmt_usd(fw.get("high"))),
            (t("low_52w", st.session_state.lang),
             _fmt_usd(fw.get("low"))),
            (t("turnover", st.session_state.lang),
             f"{fb.get('turnover'):.2f}%" if fb.get("turnover") else "N/A"),
            (t("amount", st.session_state.lang),
             format_large_num(fb.get("amount"))),
        ]
        st.dataframe(
            pd.DataFrame(vrows, columns=[t("indicator", st.session_state.lang),
                                         t("value", st.session_state.lang)]),
            use_container_width=True, hide_index=True,
        )
        st.markdown(
            f'<p style="color:{C["text3"]};font-size:.75rem;margin-top:.5rem;">'
            f'{t("financials_pro_note", st.session_state.lang)} '
            f'<a href="https://twelvedata.com/pricing" target="_blank" '
            f'style="color:{C["accent"]};">Twelve Data Pro plan</a>.</p>',
            unsafe_allow_html=True,
        )
