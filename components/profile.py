"""
Company Profile Component
=========================
公司概况卡片：展示简介、行业、CEO、员工数、官网等信息。
注意：整张卡片用单个 HTML 块渲染，避免 Streamlit 组件造成空壳 div。
"""

import streamlit as st

from i18n import t, localize_sector, localize_industry
from services.app_state import C


def render_company_profile(profile: dict):
    """渲染公司概况卡片（数据来自 /profile 接口）"""
    if not profile:
        return

    description = profile.get("description", "")
    website = profile.get("website", "")

    employees = profile.get("employees", "N/A")
    if isinstance(employees, int):
        employees = f"{employees:,}"

    lang = st.session_state.lang
    ceo = profile.get("ceo") or profile.get("CEO") or "N/A"
    info = [
        (t("profile_sector", lang),
         localize_sector(profile.get("sector", "N/A"), lang)),
        (t("profile_industry", lang),
         localize_industry(profile.get("industry", "N/A"), lang)),
        (t("profile_employees", lang), employees),
        (t("profile_ceo", lang), ceo),
    ]

    info_html = "".join(
        f'<div style="flex:1;min-width:120px;">'
        f'<p style="font-size:.6875rem;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:.04em;color:{C["text3"]};margin:0 0 .25rem;">{label}</p>'
        f'<p style="font-size:1.05rem;font-weight:600;color:{C["text"]};margin:0;'
        f'line-height:1.4;">{value}</p></div>'
        for label, value in info
    )

    website_html = (
        f'<a href="{website}" target="_blank" '
        f'style="color:{C["accent"]};text-decoration:none;font-size:.8125rem;">'
        f'{website}</a>'
        if website else ""
    )

    st.markdown(
        f'<div style="background:{C["card"]};border:1px solid {C["border"]};'
        f'border-radius:18px;padding:1.5rem;margin-bottom:1.5rem;">'
        f'<h4 style="margin:0 0 .75rem;font-size:1rem;font-weight:600;'
        f'color:{C["text"]};">{t("company_profile", st.session_state.lang)}</h4>'
        f'<p style="font-size:.8125rem;color:{C["text2"]};line-height:1.7;'
        f'margin:0 0 1.25rem;">{description}</p>'
        f'<div style="display:flex;flex-wrap:wrap;gap:1.5rem;'
        f'margin-bottom:.5rem;">{info_html}</div>'
        f'{website_html}'
        f'</div>',
        unsafe_allow_html=True,
    )
