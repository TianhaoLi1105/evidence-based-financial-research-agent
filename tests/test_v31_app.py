"""V3.1.2 AppTest 集成测试：AI 组件抽屉 + 设置弹窗 + V2 回归（全部 mock，无网络）"""
import os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.storage as storage
import data.chat_store as chat_store
from data.indicators import compute_indicators

REAL_CFG = os.path.join(os.getcwd(), ".agent_config.json")
with open(REAL_CFG) as f:
    real_content = f.read()

tmp_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp_cfg.write('{"api_key": "test-demo-key", "watchlist": ["AAPL"]}')
tmp_cfg.close()

tmp_chat = os.path.join(tempfile.mkdtemp(), "chat_history.json")

def _hist(n=120, start=200.0):
    rows, px = [], start
    for i in range(n):
        dt = f"2026-{(i//28)+1:02d}-{(i%28)+1:02d}"
        o, c = px, px + (0.5 if i % 2 else -0.3)
        hi, lo = max(o, c) + 1.2, min(o, c) - 1.0
        rows.append({"datetime": dt, "open": f"{o:.2f}", "high": f"{hi:.2f}",
                     "low": f"{lo:.2f}", "close": f"{c:.2f}",
                     "volume": str(1_000_000 + i * 1000)})
        px = c
    return rows

HIST = _hist()
QUOTE = {"symbol": "AAPL", "name": "Apple Inc.", "close": 234.56, "change": 2.31,
         "percent_change": 0.99, "currency": "USD", "market_cap": 3_500_000_000_000,
         "pe_ratio": 30.12}
STATS = {"valuations_metrics": {"market_capitalization": 3_500_000_000_000,
                                "trailing_pe": 30.12},
         "dividends_and_splits": {},
         "quote_fallback": {"fifty_two_week": {"high": 260.0}, "amount": 0, "turnover": 0}}
PROFILE = {"name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics",
           "description": "Apple designs, manufactures and markets smartphones.",
           "CEO": "Tim Cook", "employees": 164000, "website": "https://www.apple.com"}

def fake_fetch_data(ticker, period_days, interval="1day"):
    q = dict(QUOTE); q["symbol"] = ticker
    return q, dict(STATS), list(HIST), dict(PROFILE), compute_indicators(HIST), "cache", "twelvedata"

def fake_fetch_compare_data(tickers, period_days, interval="1day"):
    return ({t: dict(QUOTE) for t in tickers},
            {t: list(HIST) for t in tickers},
            {t: "cache" for t in tickers})

def fake_indices():
    return [{"code": ".DJI", "name": "Dow Jones", "close": 39000.0, "change": 100.0,
             "percent_change": 0.26}]

def fake_run_agent(profile, messages, lang="en", max_rounds=3):
    yield {"t": "text", "c": "这是 mock 的 AI 回答。"}
    yield {"t": "text", "c": "补充段落。" * 40}

passed = []
def check(name, cond, extra=""):
    assert cond, f"FAIL: {name} {extra}"
    passed.append(name)

try:
    with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
         mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
         mock.patch("services.stock_service.fetch_data", fake_fetch_data), \
         mock.patch("services.stock_service.fetch_compare_data", fake_fetch_compare_data), \
         mock.patch("services.stock_service.fetch_indices", fake_indices), \
         mock.patch("components.chat.run_agent", fake_run_agent):
        from streamlit.testing.v1 import AppTest

        # 预置模型配置
        storage.save_llm_profiles([{
            "id": "preset001", "name": "DeepSeek", "provider": "deepseek",
            "model": "deepseek-chat", "api_key": "sk-preset",
            "base_url": "https://api.deepseek.com/v1",
        }])
        storage.set_active_llm_profile_id("preset001")

        at = AppTest.from_file("app.py", default_timeout=60)

        # ── 1. 初始加载（英文）：两模式 + 组件 iframe + fab 尺寸 ──
        at.run()
        check("no exception on boot", not at.exception, str(at.exception))
        check("two mode buttons", bool(at.button(key="mode_single_btn"))
              and bool(at.button(key="mode_compare_btn")))
        check("no mode_chat button", not [b for b in at.button if b.key == "mode_chat_btn"])
        check("ai panel component renders", not at.exception)
        boot_css = " ".join(str(m.value) for m in at.markdown)
        check("fab size css (closed)", "width:56px!important" in boot_css)
        check("drawer css hidden", "width:460px" not in boot_css)
        check("single sidebar ticker input", bool(at.text_input(key="ticker_input_widget")))

        # ── 2. 单股分析回归 ──
        at.text_input(key="ticker_input_widget").set_value("AAPL"); at.run()
        analyze_btn = [b for b in at.button if b.label == "Analyze"]
        check("analyze button found", len(analyze_btn) == 1)
        analyze_btn[0].click(); at.run()
        check("no exception after analyze", not at.exception, str(at.exception))
        check("metric cards rendered", len(at.metric) >= 4)
        check("price chart rendered", len(at.get("plotly_chart")) >= 1)

        # ── 3. 语言切换 ──
        at.button(key="lang_btn").click(); at.run()
        check("zh title shown", any("金融研究助手" in str(m.value) for m in at.markdown))
        check("ticker preserved", at.text_input(key="ticker_input_widget").value == "AAPL")

        # ── 4. 多股对比回归 ──
        at.button(key="mode_compare_btn").click(); at.run()
        tinputs = at.text_input
        tinputs[0].set_value("GOOGL"); at.run()
        [b for b in at.button if b.label == "添加"][0].click(); at.run()
        tinputs = at.text_input
        tinputs[0].set_value("MSFT"); at.run()
        [b for b in at.button if b.label == "添加"][0].click(); at.run()
        [b for b in at.button if b.label == "开始对比"][0].click(); at.run()
        check("no exception after compare", not at.exception, str(at.exception))
        check("compare chart rendered", len(at.get("plotly_chart")) >= 1)

        # ── 5. 打开 AI 抽屉（会话状态注入，等价于点击悬浮按钮）──
        at.session_state["show_chat"] = True
        at.run()
        check("no exception opening drawer", not at.exception, str(at.exception))
        open_css = " ".join(str(m.value) for m in at.markdown)
        check("drawer css applied", "width:460px" in open_css)
        check("no overlay (V3.2.2d)", "#ai-overlay" not in open_css)
        check("welcome shown", any("AI 金融助手" in str(m.value) for m in at.markdown))

        # ── 5b. 最小化：消息区隐藏、iframe 高度切换为迷你条 ──
        at.session_state["show_mini"] = True
        at.run()
        check("no exception mini mode", not at.exception, str(at.exception))
        mini_css = " ".join(str(m.value) for m in at.markdown)
        check("mini height 48px", "height:48px" in mini_css)
        check("mini hides msgs", 'id="chat-msgs"' not in mini_css)
        at.session_state["show_mini"] = False
        at.run()

        # ── 6. 发消息 → 流式回复（长文本 + markdown 渲染）──
        at.session_state["chat_messages"] = [{"role": "user", "content": "什么是 RSI？"}]
        at.run()
        check("no exception after send", not at.exception, str(at.exception))
        check("assistant reply in history",
              at.session_state["chat_messages"][-1]["role"] == "assistant")
        check("assistant reply rendered", any(
            "mock 的 AI 回答" in str(m.value) for m in at.markdown))
        check("message area rendered", any(
            'id="chat-msgs"' in str(m.value) for m in at.markdown))

        # ── 7. 关闭抽屉（等价于点击 ✕）──
        at.session_state["show_chat"] = False
        at.run()
        closed_css = " ".join(str(m.value) for m in at.markdown)
        check("drawer css hidden after close", "width:460px" not in closed_css)

        # ── 8. KEY 弹窗：新增第二个模型配置 ──
        at.button(key="api_btn").click(); at.run()
        check("three tabs in modal (data/llm/prefs)", len(at.tabs) == 3)
        llm_tab = at.tabs[1]
        llm_tab.text_input(key="llm_name").set_value("OpenAI"); at.run()
        llm_tab = at.tabs[1]
        llm_tab.text_input(key="llm_model_input").set_value("gpt-4o-mini"); at.run()
        llm_tab = at.tabs[1]
        llm_tab.text_input(key="llm_key_input").set_value("sk-test-123"); at.run()
        llm_tab = at.tabs[1]
        llm_tab.button(key="llm_save_btn").click(); at.run()
        profiles = storage.get_llm_profiles()
        check("second llm profile saved", len(profiles) == 2
              and any(p["name"] == "OpenAI" for p in profiles), str(profiles))
        at.button(key="modal_close").click(); at.run()

        # ── 9. 删除新增配置 ──
        at.button(key="api_btn").click(); at.run()
        llm_tab = at.tabs[1]
        openai_pid = next(p["id"] for p in storage.get_llm_profiles() if p["name"] == "OpenAI")
        llm_tab.button(key=f"llm_del_{openai_pid}").click(); at.run()
        check("second llm profile deleted", len(storage.get_llm_profiles()) == 1)

        # ── 10. 配置文件未污染 ──
        cfg = storage.load_config()
        check("config api_key intact", cfg.get("api_key") == "test-demo-key")
        check("config watchlist intact", cfg.get("watchlist") == ["AAPL"])
        print("\nALL APP TESTS PASSED:", len(passed))
        for p in passed:
            print("  ✓", p)
finally:
    with open(REAL_CFG, "w") as f:
        f.write(real_content)
    if os.path.exists(tmp_cfg.name):
        os.remove(tmp_cfg.name)
    print("config restored")
