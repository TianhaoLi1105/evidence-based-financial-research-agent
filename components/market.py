"""
Market Overview Component
==========================
市场概览：三大美股指数卡片（道琼斯 / 纳斯达克 / 标普500）。
数据来自腾讯财经备用源，免 Key，缓存 60 秒。
"""

import streamlit as st

from services.stock_service import fetch_indices
from utils import safe_float

INDEX_NAMES = {
    ".DJI": ("Dow Jones", "道琼斯"),
    ".IXIC": ("NASDAQ", "纳斯达克"),
    ".INX": ("S&P 500", "标普500"),
}


@st.cache_data(ttl=60, show_spinner=False)
def _load_indices() -> list:
    """缓存三大指数报价 60 秒，避免每次交互都请求"""
    return fetch_indices()


def render_market_overview() -> None:
    """渲染三大指数卡片行（数据不可用时静默跳过）"""
    indices = _load_indices()
    if not indices:
        return

    lang = st.session_state.lang
    cols = st.columns(len(indices))
    for col, item in zip(cols, indices):
        code = item.get("code", "")
        en_name, zh_name = INDEX_NAMES.get(code, (item.get("name", ""), item.get("name", "")))
        name = zh_name if lang == "zh" else en_name
        close = safe_float(item.get("close"), 0)
        chg = safe_float(item.get("change"), 0)
        chg_p = safe_float(item.get("percent_change"), 0)
        with col:
            st.metric(
                name,
                f"{close:,.2f}",
                delta=f"{chg:+.2f} ({chg_p:+.2f}%)",
            )
