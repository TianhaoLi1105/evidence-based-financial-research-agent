"""
Application State
=================
应用初始化：加载配置、初始化 session_state、注入全局主题 CSS。
"""

import streamlit as st

from data.storage import load_config
from data.finance_data import set_api_key
from i18n import get_language_options

# ─── Apple 风格深色主题色板 ─────────────────────────────
C = {
    "bg": "#1c1c1e", "bg2": "#2c2c2e", "card": "#2c2c2e",
    "text": "#f5f5f7", "text2": "#d1d1d6", "text3": "#98989d",
    "border": "#38383a", "accent": "#0a84ff", "chart": "#0a84ff",
    "green": "#34c759", "red": "#ff3b30", "shadow": "rgba(0,0,0,0.3) 0 2px 8px",
}


def init_session_state() -> None:
    """初始化跨页面共享的 session_state 变量"""
    # 从本地配置恢复上次选择的语言（默认英文）
    config = load_config()
    saved_lang = config.get("lang", "en")
    if saved_lang not in get_language_options():
        saved_lang = "en"
    for k, v in {"lang": saved_lang, "cached": None, "ticker_input": "",
                 "show_api": False, "show_chat": False,
                 "chat_messages": [], "chat_session_id": None,
                 "chat_session_loaded": False, "show_threads": False,
                 "show_mini": False}.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # 从本地配置恢复 API Key
    saved_api_key = config.get("api_key", "")
    if "api_key" not in st.session_state:
        st.session_state.api_key = saved_api_key

    set_api_key(st.session_state.api_key if st.session_state.api_key else "demo")


def apply_css() -> None:
    """注入全局深色主题 CSS"""
    st.markdown(f"""
<style>
    .stApp,.main,.block-container,section[data-testid="stSidebar"]{{background:{C["bg"]}!important}}
    section[data-testid="stSidebar"]{{border-right:1px solid {C["border"]};padding:.75rem 1rem 1.25rem!important;min-width:260px}}
    div[data-testid="stSidebarContent"]>header{{display:none!important}}
    section[data-testid="stSidebar"] .stSelectbox,section[data-testid="stSidebar"] .stTextInput,section[data-testid="stSidebar"] .stCheckbox{{margin-bottom:.4rem!important}}
    section[data-testid="stSidebar"] [data-baseweb="select"]>div{{margin-top:.1rem!important}}
    .block-container{{padding:1.5rem 2rem!important;max-width:1200px}}
    *{{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Helvetica Neue",Arial,sans-serif}}
    h1{{font-size:2rem!important;font-weight:700!important;letter-spacing:-0.03em!important;color:{C["text"]}!important;margin-bottom:0.1rem!important}}
    h2{{font-size:1.25rem!important;font-weight:600!important;letter-spacing:-0.015em!important;color:{C["text"]}!important;margin-top:2rem!important;margin-bottom:1rem!important;padding-bottom:0.5rem!important;border-bottom:1px solid {C["border"]}!important}}
    p,li,.stMarkdown,.stMarkdown p{{color:{C["text2"]}!important;font-size:.9375rem;line-height:1.6}}
    .pref-chip{{display:inline-block;margin:2px 6px 2px 0;padding:3px 12px;border-radius:999px;
      background:{C["bg2"]};border:1px solid {C["border"]};color:{C["text"]};
      font-size:.8125rem;font-weight:600}}
    .pref-topic{{margin:.35rem 0;color:{C["text2"]};font-size:.875rem}}
    .pref-topic b{{color:{C["text"]}!important}}
    strong{{color:{C["text"]}!important;font-weight:600}}
    .stSelectbox label,.stTextInput label{{color:{C["text2"]}!important;font-size:.8125rem!important;font-weight:500!important}}
    .stSelectbox>div>div,.stTextInput input{{background:{C["card"]}!important;color:{C["text"]}!important;border:1px solid {C["border"]}!important;border-radius:10px!important}}
    .stTextInput input{{padding:.55rem .85rem!important;font-size:.875rem!important}}
    .stTextInput input:focus{{border-color:{C["accent"]}!important;box-shadow:0 0 0 3px rgba(10,132,255,.15)!important}}
    .stButton>button[data-testid="baseButton-primary"]{{background:{C["accent"]}!important;color:#fff!important;border:none!important;border-radius:24px!important;padding:.5rem 1.5rem!important;font-size:.9375rem!important;font-weight:500!important;transition:all .2s ease!important}}
    .stButton>button[data-testid="baseButton-primary"]:hover{{background:#409cff!important;box-shadow:0 2px 12px rgba(10,132,255,.3)!important}}
    .stButton>button[key="lang_btn"]{{background:transparent!important;color:{C["text3"]}!important;border:1px solid {C["border"]}!important;border-radius:20px!important;font-size:.8125rem!important;font-weight:500!important;padding:.25rem 1rem!important;width:auto!important;transition:all .2s ease!important}}
    .stButton>button[key="lang_btn"]:hover{{border-color:#0a84ff!important;color:#0a84ff!important}}
    .stButton>button[key="api_btn"]{{background:transparent!important;color:#98989d!important;border:1px solid #38383a!important;border-radius:20px!important;font-size:.75rem!important;font-weight:500!important;padding:.25rem .7rem!important;width:auto!important;margin-left:6px!important;transition:all .2s ease!important}}
    .stButton>button[key="api_btn"]:hover{{border-color:#0a84ff!important;color:#0a84ff!important}}
    div[data-testid="metric-container"]{{background:{C["card"]}!important;border:1px solid {C["border"]}!important;border-radius:14px!important;padding:1rem 1.25rem!important;box-shadow:{C["shadow"]}!important}}
    div[data-testid="metric-container"] label{{color:{C["text3"]}!important;font-size:.6875rem!important;font-weight:600!important;text-transform:uppercase!important;letter-spacing:.04em!important}}
    div[data-testid="metric-container"] [data-testid="stMetricValue"]{{color:{C["text"]}!important;font-size:1.5rem!important;font-weight:700!important;letter-spacing:-.02em!important}}
    div[data-testid="metric-container"] [data-testid="stMetricDelta"]{{font-size:.8125rem!important;font-weight:500!important}}
    .delta_positive{{color:{C["green"]}!important}}.delta_negative{{color:{C["red"]}!important}}
    .stDataFrame{{border:1px solid {C["border"]}!important;border-radius:14px!important;overflow:hidden!important;box-shadow:{C["shadow"]}!important}}
    .stDataFrame thead tr th{{background:{C["bg2"]}!important;color:{C["text"]}!important;font-weight:600!important;font-size:.8125rem!important;padding:.75rem 1rem!important;border-bottom:1px solid {C["border"]}!important}}
    .stDataFrame tbody tr td{{background:{C["card"]}!important;color:{C["text"]}!important;font-size:.875rem!important;padding:.65rem 1rem!important;border-bottom:1px solid {C["border"]}!important}}
    .js-plotly-plot{{border:1px solid {C["border"]}!important;border-radius:14px!important;overflow:hidden!important;box-shadow:{C["shadow"]}!important}}
    .stAlert{{border-radius:12px!important;padding:1rem 1.25rem!important;border:1px solid {C["border"]}!important}}
    .sidebar-title{{font-size:.6875rem!important;font-weight:600!important;text-transform:uppercase!important;letter-spacing:.06em!important;color:{C["text3"]}!important;margin:0 0 .5rem!important}}
    .welcome-card{{background:{C["card"]}!important;border:1px solid {C["border"]}!important;border-radius:14px!important;padding:1.5rem!important;box-shadow:{C["shadow"]}!important}}
    .welcome-card h3{{font-size:.75rem!important;font-weight:600!important;text-transform:uppercase!important;letter-spacing:.05em!important;color:{C["text3"]}!important;margin-bottom:.75rem!important}}
    .welcome-card li{{color:{C["text2"]}!important;margin-bottom:.5rem!important;font-size:.875rem!important}}
    .welcome-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin:1.5rem 0}}
    .source-item{{color:{C["text2"]}!important;font-size:.8125rem;padding:.3rem 0}}
    .source-item strong{{color:{C["text"]}!important}}
    .disclaimer{{color:{C["text3"]}!important;font-size:.75rem;margin-top:2rem;padding-top:1rem;border-top:1px solid {C["border"]}}}
    .app-subtitle{{color:{C["text3"]}!important;margin-bottom:1.5rem}}
    .stButton>button[key^="cmp_rm_"]{{width:26px!important;min-width:26px!important;height:26px!important;min-height:26px!important;padding:0!important;border-radius:50%!important;border:1px solid {C["border"]}!important;background:transparent!important;color:{C["text3"]}!important;font-size:.7rem!important;line-height:1!important;display:flex!important;align-items:center!important;justify-content:center!important;margin-top:.1rem!important}}
    .stButton>button[key^="cmp_rm_"]:hover{{border-color:{C["red"]}!important;color:{C["red"]}!important}}
    .stButton>button[key="mode_single_btn"],.stButton>button[key="mode_compare_btn"]{{white-space:nowrap!important;min-height:38px!important;height:38px!important;padding:0 1.2rem!important;font-size:.875rem!important;display:inline-flex!important;align-items:center!important;justify-content:center!important}}
    div[data-testid="stChatMessage"]{{background:{C["card"]}!important;border:1px solid {C["border"]}!important;border-radius:14px!important;padding:.25rem 1rem!important;margin-bottom:.5rem!important}}
    div[data-testid="stChatInput"]{{border:1px solid {C["border"]}!important;border-radius:24px!important;background:{C["card"]}!important}}
    div[data-testid="stChatInput"] textarea{{background:transparent!important;color:{C["text"]}!important;font-size:.9375rem!important}}
    div[data-testid="stChatInput"] button{{color:{C["accent"]}!important}}
    button[data-baseweb="tab"]{{color:{C["text3"]}!important;font-size:.8125rem!important}}
    button[data-baseweb="tab"][aria-selected="true"]{{color:{C["accent"]}!important}}
    div[data-baseweb="tab-highlight"]{{background-color:{C["accent"]}!important}}
    #MainMenu,footer,.stDeployButton{{display:none!important}}

    /* ── AI 助手（V3.1.2：组件 iframe + 消息区浮层）── */
    iframe[data-testid="stIFrame"]{{border:none!important;background:transparent!important}}
    .chat-bubble{{margin:4px 0!important;padding:10px 14px!important;border-radius:16px!important;max-width:88%!important;font-size:.875rem!important;line-height:1.55!important;word-break:break-word!important}}
    .chat-bubble-user{{margin-left:auto!important;background:{C["accent"]}!important;color:#fff!important;border-bottom-right-radius:6px!important}}
    .chat-bubble-assistant{{margin-right:auto!important;background:{C["card"]}!important;color:{C["text2"]}!important;border:1px solid {C["border"]}!important;border-bottom-left-radius:6px!important}}
    .chat-bubble-assistant strong{{color:{C["text"]}!important}}
    .chat-bubble-assistant a{{color:{C["accent"]}!important;text-decoration:none!important}}
    .chat-bubble-assistant pre{{background:{C["bg"]}!important;border:1px solid {C["border"]}!important;border-radius:8px!important;padding:8px 10px!important;overflow-x:auto!important;font-size:.75rem!important;margin:6px 0!important}}
    .chat-bubble-assistant code{{font-family:"SF Mono",Menlo,monospace!important;font-size:.8em!important;background:{C["bg"]}!important;border-radius:4px!important;padding:1px 4px!important}}
    .chat-bubble-assistant h4,.chat-bubble-assistant h3{{font-size:.9rem!important;margin:.5rem 0 .25rem!important;color:{C["text"]}!important}}
    .chat-bubble-assistant table{{display:block!important;overflow-x:auto!important;max-width:100%!important;border-collapse:collapse!important;font-size:.75rem!important;line-height:1.5!important;margin:6px 0 8px!important;white-space:nowrap!important}}
    .chat-bubble-assistant th{{background:rgba(255,255,255,.05)!important;color:{C["text"]}!important;font-weight:600!important;padding:6px 10px!important;border-bottom:1px solid {C["border"]}!important;text-align:left!important}}
    .chat-bubble-assistant td{{padding:5px 10px!important;border-bottom:1px solid rgba(255,255,255,.05)!important;vertical-align:top!important;color:{C["text2"]}!important}}
    .chat-bubble-assistant th,.chat-bubble-assistant td{{word-break:normal!important;white-space:nowrap!important}}
    .chat-bubble-assistant tr:last-child td{{border-bottom:none!important}}
    .chat-bubble-assistant .src-tag{{display:inline-block;padding:0 .35rem;margin-left:.15rem;border-radius:4px;background:rgba(120,120,128,.16);color:#98989d;font-size:.66rem;line-height:1.5;vertical-align:middle;white-space:nowrap}}
    .chat-bubble-assistant ul,.chat-bubble-assistant ol{{margin:.25rem 0 .5rem!important;padding-left:1.1rem!important}}
    .chat-bubble-assistant li{{margin:.15rem 0!important;line-height:1.55!important}}
    .chat-welcome{{color:{C["text3"]}!important;margin-top:auto!important}}
    .chat-welcome h4{{font-size:1rem!important;font-weight:600!important;color:{C["text"]}!important;margin:0 0 .4rem!important}}
    .chat-welcome p{{font-size:.8125rem!important;color:{C["text3"]}!important;line-height:1.6!important;margin:0 0 .3rem!important}}
    .chat-welcome-model{{font-size:.75rem!important;color:{C["accent"]}!important}}
    .chat-tool-hint{{margin:4px 0 8px;padding:6px 12px;border-radius:10px;background:rgba(10,132,255,.08);border:1px solid rgba(10,132,255,.18);color:{C["accent"]}!important;font-size:.75rem!important;line-height:1.5}}
</style>
""", unsafe_allow_html=True)


def init_app() -> None:
    """应用入口统一初始化"""
    st.set_page_config(page_title="Financial Research Agent", layout="wide")
    init_session_state()
    apply_css()
