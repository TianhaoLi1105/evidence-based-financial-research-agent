"""
Header Component
================
顶部区域：标题、副标题、语言切换按钮、API Key 按钮与设置弹窗。

设置弹窗包含两个标签页：
- 数据 API：Twelve Data 股票数据 Key
- AI 模型：大模型服务商配置（可保存多个，随时切换）
"""

import streamlit as st

from i18n import t, get_language_options
from data.storage import (
    save_config, get_llm_profiles, upsert_llm_profile,
    delete_llm_profile, get_active_llm_profile_id, set_active_llm_profile_id,
)
from data.preferences import (top_stocks, topic_counts, clear as clear_prefs,
                              get_deep_review, set_deep_review)
from agent.llm_client import PROVIDER_PRESETS
from services.app_state import C

LANG_LABEL = {"en": "EN", "zh": "中"}


def next_lang():
    """循环切换语言（en -> zh -> en）"""
    codes = list(get_language_options().keys())
    i = codes.index(st.session_state.lang) if st.session_state.lang in codes else 0
    st.session_state.lang = codes[(i + 1) % len(codes)]
    # 本地记忆：刷新/重开应用后保持上次选择的语言
    save_config({"lang": st.session_state.lang})


def render_header():
    """渲染顶部标题 + 右上角操作按钮"""
    col_l, col_r = st.columns([1, 0.22])
    with col_l:
        st.markdown(f'<h1>{t("app_title", st.session_state.lang)}</h1>', unsafe_allow_html=True)
        st.markdown(f'<p class="app-subtitle">{t("app_subtitle", st.session_state.lang)}</p>', unsafe_allow_html=True)
    with col_r:
        btn_row = st.columns([1, 1])
        with btn_row[0]:
            st.button(
                LANG_LABEL.get(st.session_state.lang, "EN"),
                key="lang_btn", on_click=next_lang, use_container_width=True,
            )
        with btn_row[1]:
            st.button(
                t("key_button", st.session_state.lang),
                key="api_btn",
                on_click=lambda: setattr(
                    st.session_state, "show_api",
                    not st.session_state.get("show_api", False)),
                use_container_width=True,
            )

    if st.session_state.show_api:
        render_api_modal()


# ─── 设置弹窗 ────────────────────────────────────────────
def render_api_modal():
    """渲染设置弹窗：数据 API / AI 模型 两个标签页"""
    _, m, _ = st.columns([1, 2.5, 1])
    with m:
        st.markdown(
            f'<h4 style="margin:0 0 1rem;font-size:1rem;font-weight:600;'
            f'color:{C["text"]};">{t("settings", st.session_state.lang)}</h4>',
            unsafe_allow_html=True,
        )
        tab_data, tab_llm, tab_prefs = st.tabs(
            [t("tab_data_api", st.session_state.lang),
             t("tab_llm", st.session_state.lang),
             t("tab_prefs", st.session_state.lang)]
        )
        with tab_data:
            _render_data_api_tab()
        with tab_llm:
            _render_llm_tab()
        with tab_prefs:
            _render_prefs_tab()

        st.button(
            t("close", st.session_state.lang), key="modal_close",
            use_container_width=True,
            on_click=lambda: setattr(st.session_state, "show_api", False))


def _render_prefs_tab():
    """个性化标签页：展示行为学习到的档案（常看股票 / 关注维度），可一键清空"""
    lang = st.session_state.lang
    # V3.4.4：分析师→风控二次审阅开关
    review_on = st.toggle(
        t("deep_review_toggle", lang), value=get_deep_review(),
        key="deep_review_toggle", help=t("deep_review_hint", lang))
    if review_on != get_deep_review():
        set_deep_review(review_on)
    st.markdown(
        f'<p style="font-size:.75rem;color:{C["text3"]};margin:.25rem 0 .75rem;">'
        f'{t("prefs_note", lang)}</p>',
        unsafe_allow_html=True,
    )
    stocks = top_stocks(5)
    topics = topic_counts()
    if not stocks and not any(v > 0 for v in topics.values()):
        st.markdown(
            f'<p style="color:{C["text3"]};font-size:.875rem;">'
            f'{t("prefs_empty", lang)}</p>',
            unsafe_allow_html=True,
        )
        return
    if stocks:
        st.markdown(
            f'<p style="color:{C["text2"]};font-weight:600;font-size:.8125rem;'
            f'margin:.5rem 0 .25rem;">{t("prefs_stocks", lang)}</p>',
            unsafe_allow_html=True,
        )
        chips = "".join(f'<span class="pref-chip">{tk}</span>' for tk in stocks)
        st.markdown(f'<div>{chips}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<p style="color:{C["text2"]};font-weight:600;font-size:.8125rem;'
        f'margin:1rem 0 .25rem;">{t("prefs_topics", lang)}</p>',
        unsafe_allow_html=True,
    )
    topic_labels = {"technical": t("topic_technical", lang),
                    "fundamental": t("topic_fundamental", lang),
                    "price": t("topic_price", lang)}
    topic_html = "".join(
        f'<p class="pref-topic"><b>{topic_labels[tp]}</b> × {topics.get(tp, 0)}</p>'
        for tp in ("technical", "fundamental", "price") if topics.get(tp, 0) > 0)
    st.markdown(topic_html, unsafe_allow_html=True)
    if st.button(t("prefs_clear", lang), key="prefs_clear_btn"):
        clear_prefs()
        st.success(t("prefs_clear_done", lang))


def _render_data_api_tab():
    """数据 API 标签页：Twelve Data Key 保存"""
    lang = st.session_state.lang

    api_input = st.text_input(
        t("api_key", lang),
        value=st.session_state.api_key,
        placeholder="Twelve Data API Key", key="api_modal_input",
        label_visibility="collapsed", type="password",
    )

    if not st.session_state.api_key:
        st.markdown(
            f'<p style="font-size:.7rem;color:{C["text3"]};margin-bottom:.5rem;">'
            f'{t("demo_key_hint", lang)} '
            f'<a href="https://twelvedata.com/apikey" target="_blank" '
            f'style="color:{C["accent"]};">twelvedata.com/apikey</a></p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<p style="font-size:.7rem;color:{C["text3"]};margin-bottom:.5rem;">'
            f'<span style="color:{C["green"]};">✓</span> '
            f'{t("custom_key_saved", lang)}</p>',
            unsafe_allow_html=True,
        )

    if st.button(t("save", lang), key="modal_save", type="primary",
                 use_container_width=True):
        new_key = api_input.strip()
        if new_key and new_key != st.session_state.api_key:
            st.session_state.api_key = new_key
            save_config({"api_key": new_key})
            from data.finance_data import set_api_key
            set_api_key(new_key)
            st.session_state.cached = None
        st.session_state.show_api = False  # 保存后关闭弹窗


def _render_llm_tab():
    """AI 模型标签页：新增/覆盖模型配置 + 已保存列表 + 切换/删除"""
    lang = st.session_state.lang
    st.markdown(
        f'<p style="font-size:.8125rem;font-weight:600;color:{C["text2"]};'
        f'margin:0 0 .5rem;">{t("llm_save", lang)}</p>',
        unsafe_allow_html=True,
    )

    name = st.text_input(
        t("llm_profile_name", lang), key="llm_name",
        placeholder="DeepSeek", label_visibility="collapsed",
    )
    provider_labels = {v["label"]: k for k, v in PROVIDER_PRESETS.items()}
    provider_label = st.selectbox(
        t("llm_provider", lang), list(provider_labels.keys()),
        key="llm_provider",
    )
    provider = provider_labels[provider_label]
    preset = PROVIDER_PRESETS[provider]
    model = st.text_input(
        t("llm_model", lang), value=preset["default_model"],
        key="llm_model_input", label_visibility="collapsed",
    )
    api_key = st.text_input(
        t("llm_api_key", lang), type="password",
        key="llm_key_input", label_visibility="collapsed",
    )
    base_url = st.text_input(
        t("llm_base_url", lang), value=preset["base_url"],
        key="llm_base_url_input", label_visibility="collapsed",
    )
    st.markdown(
        f'<p style="font-size:.7rem;color:{C["text3"]};margin-bottom:.5rem;">'
        f'{t("llm_models_hint", lang, hint=preset["models_hint"])}</p>',
        unsafe_allow_html=True,
    )

    if st.button(t("llm_save", lang), key="llm_save_btn", type="primary",
                 use_container_width=True):
        if name.strip() and model.strip() and api_key.strip():
            upsert_llm_profile({
                "name": name.strip(),
                "provider": provider,
                "model": model.strip(),
                "api_key": api_key.strip(),
                "base_url": (base_url or preset["base_url"]).strip(),
            })
            if not get_active_llm_profile_id():
                set_active_llm_profile_id(get_llm_profiles()[-1]["id"])
            st.success(t("llm_saved", lang))
        else:
            st.warning(t("llm_need_fields", lang))

    # ── 已保存模型列表 ──
    st.markdown(
        f'<p style="font-size:.8125rem;font-weight:600;color:{C["text2"]};'
        f'margin:1rem 0 .5rem;">{t("llm_saved_profiles", lang)}</p>',
        unsafe_allow_html=True,
    )
    profiles = get_llm_profiles()
    if not profiles:
        st.markdown(
            f'<p style="font-size:.75rem;color:{C["text3"]};">'
            f'{t("llm_empty_profiles", lang)}</p>',
            unsafe_allow_html=True,
        )
        return

    active_id = get_active_llm_profile_id()
    for p in profiles:
        is_active = p.get("id") == active_id
        badge = (f'<span style="color:{C["green"]};font-size:.6875rem;'
                 f'font-weight:600;">● {t("llm_active", lang)}</span>'
                 if is_active else "")
        label = p.get("name", "") or p.get("model", "")
        provider_label = PROVIDER_PRESETS.get(p.get("provider"), {}).get("label", "")
        c1, c2, c3 = st.columns([3.1, 1, 1])
        with c1:
            st.markdown(
                f'<div style="padding:.35rem 0;">'
                f'<p style="margin:0;font-size:.875rem;font-weight:500;'
                f'color:{C["text"]};">{label} <span style="color:{C["text3"]};'
                f'font-weight:400;">· {p.get("model", "")}</span></p>'
                f'<p style="margin:0;font-size:.6875rem;color:{C["text3"]};">'
                f'{provider_label} {badge}</p></div>',
                unsafe_allow_html=True,
            )
        with c2:
            if st.button(t("llm_use", lang), key=f"llm_use_{p.get('id')}",
                         use_container_width=True):
                set_active_llm_profile_id(p.get("id", ""))
        with c3:
            if st.button(t("llm_delete", lang), key=f"llm_del_{p.get('id')}",
                         use_container_width=True):
                delete_llm_profile(p.get("id", ""))
