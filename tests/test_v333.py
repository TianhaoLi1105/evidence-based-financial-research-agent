"""V3.3.3 回归：个性化记忆（隐式学习 / 注入 / 设置弹窗）"""
import json, os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.storage as storage
import data.chat_store as chat_store
import data.preferences as pref
import components.chat as chat_mod
import components.header as header_mod

REAL_CFG = os.path.join(os.getcwd(), ".agent_config.json")
with open(REAL_CFG) as f:
    real_content = f.read()
tmp_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp_cfg.write('{"api_key": "test-demo-key", "watchlist": ["AAPL"]}')
tmp_cfg.close()
tmp_chat = os.path.join(tempfile.mkdtemp(), "chat_history.json")

def rel():
    pref.clear()

with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
     mock.patch.object(chat_store, "CHAT_PATH", tmp_chat):
    rel()

    # ── 1. 股票记录：计数 / 去重 / 排序 / 清空 ──
    with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name):
        pref.record_stock("aapl")
        pref.record_stock("AAPL")
        pref.record_stock("NVDA")
        pref.record_stock("msft")
        pref.record_stock("NVDA")
    assert pref.top_stocks(2) == ["NVDA", "AAPL"], pref.top_stocks(2)
    assert pref.top_stocks(1) == ["NVDA"]
    assert pref.has_profile()
    pref.clear()
    assert not pref.has_profile() and pref.top_stocks() == []
    print("PASS stock memory (count/dedupe/sort/clear)")

    # ── 2. 话题分类：技术面 / 基本面 / 行情 / 混合 ──
    cases = {
        "RSI 和 MACD 怎么看": ["technical"],
        "解释一下PE和市值": ["fundamental"],
        "苹果现在多少钱": ["price"],
        "AAPL 的 RSI 和 PE 如何": ["technical", "fundamental"],
        "你好呀": [],
    }
    for q, want in cases.items():
        got = sorted(pref._topics_of(q))
        assert got == sorted(want), (q, got)
    with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name):
        pref.record_question("RSI 和 MACD 怎么看")
        pref.record_question("解释一下PE和市值")
        pref.record_question("苹果现在多少钱")
    counts = pref.topic_counts()
    assert counts["technical"] == 1 and counts["fundamental"] == 1 and counts["price"] == 1
    assert pref.top_topics(2) == ["technical", "fundamental"] or pref.top_topics(2) == ["fundamental", "price"]
    pref.clear()
    print("PASS topic classification (tech/fund/price/mixed)")

    # ── 3. 上下文注入：档案出现在 _context_text ──
    with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name):
        pref.record_stock("NVDA")
        pref.record_stock("AAPL")
        pref.record_question("RSI 和 MACD 怎么看")
        pref.record_question("RSI 背离怎么看")
    fake_st = mock.MagicMock()
    fake_st.session_state.get.return_value = None
    with (mock.patch.object(chat_mod, "st", fake_st),
          mock.patch.object(chat_mod, "_page_state",
                            return_value={"mode": "single", "ticker": "NVDA"}),
          mock.patch.object(chat_mod, "_page_data_text", return_value=""),
          mock.patch.object(chat_mod, "load_config",
                            return_value={"watchlist": []})):
        ctx = chat_mod._context_text("zh")
    assert "个性化档案" in ctx and "NVDA" in ctx and "AAPL" in ctx
    assert "技术面" in ctx
    assert "自选股" not in ctx  # 空自选股不注入
    pref.clear()
    print("PASS profile injected into AI context")

    # ── 4. 设置弹窗：个性化标签页渲染 + 清空按钮 ──
    QUOTE = {"symbol": "AAPL", "name": "Apple Inc.", "close": 234.56,
             "change": 2.31, "percent_change": 0.99, "currency": "USD"}
    HIST = [{"datetime": f"2026-01-{i+1:02d}", "open": 100+i, "high": 102+i,
             "low": 99+i, "close": 101+i, "volume": 1000000} for i in range(30)]
    def fake_fetch_data(ticker, period_days, interval="1day"):
        return dict(QUOTE), {}, list(HIST), {}, {}, "cache", "twelvedata"
    def fake_indices():
        return [{"code": ".DJI", "name": "Dow Jones", "close": 39000.0,
                 "change": 100.0, "percent_change": 0.26}]
    with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
         mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
         mock.patch("services.stock_service.fetch_data", fake_fetch_data), \
         mock.patch("services.stock_service.fetch_indices", fake_indices):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file("app.py", default_timeout=60)
        at.run()
        at.button(key="api_btn").click(); at.run()
        assert not at.exception, [str(e) for e in at.exception]
        tabs = [t.label for t in at.tabs]
        assert any("Personalization" in x or "个性化" in x for x in tabs), tabs
        # 弹窗里应显示个性化内容或空态
        md = " ".join(str(m.value) for m in at.markdown)
        assert any(x in md for x in ("常看股票", "Stocks you follow",
                                     "暂无记录", "No activity recorded yet")), md[-400:]
        print("PASS personalization tab renders in settings modal")

    # ── 5. 分析股票 → 自动记录（隐式学习闭环）──
    with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
         mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
         mock.patch("services.stock_service.fetch_data", fake_fetch_data), \
         mock.patch("services.stock_service.fetch_indices", fake_indices):
        at2 = AppTest.from_file("app.py", default_timeout=60)
        at2.run()
        at2.text_input(key="ticker_input_widget").set_value("AAPL"); at2.run()
        [b for b in at2.button if b.label in ("Analyze", "开始分析")][0].click(); at2.run()
        assert not at2.exception, [str(e) for e in at2.exception]
    prefs = json.load(open(tmp_cfg.name)).get("preferences", {})
    assert "AAPL" in (prefs.get("stocks") or {}), prefs
    print("PASS analyze records stock to preferences")
    pref.clear()

print("\nALL V3.3.3 TESTS PASSED")
