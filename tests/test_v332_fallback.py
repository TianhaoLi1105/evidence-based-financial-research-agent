"""V3.3.2 兜底出图：模型只回文字不调工具时，系统直接生成图表（真实链路复现）"""
import os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.storage as storage
import data.chat_store as chat_store
import components.chat as chat_mod

REAL_CFG = os.path.join(os.getcwd(), ".agent_config.json")
with open(REAL_CFG) as f:
    real_content = f.read()

tmp_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp_cfg.write('{"api_key": "test-demo-key", "watchlist": ["AAPL"]}')
tmp_cfg.close()
tmp_chat = os.path.join(tempfile.mkdtemp(), "chat_history.json")

FAKE_SVG = "<svg viewBox=\"0 0 420 200\"><polyline points=\"1,1 2,2\"/></svg>"

def fake_run_agent_text_only(profile, messages, lang="en", max_rounds=3):
    # 模拟 DeepSeek 实际行为：只回文字，不调用 plot_chart
    yield {"t": "text", "c": "这是 AAPL 的K线图，先看蜡烛实体…"}

def fake_plot_chart(tickers, days=365, interval="1day", chart_type="line"):
    return {"symbol": tickers[0], "bars": 180, "chart_type": chart_type,
            "source": "cache", "message": "chart generated", "_chart_html": FAKE_SVG}

try:
    with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
         mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
         mock.patch.object(chat_mod, "run_agent", fake_run_agent_text_only), \
         mock.patch.object(chat_mod, "tool_plot_chart", fake_plot_chart):
        from streamlit.testing.v1 import AppTest
        storage.save_llm_profiles([{
            "id": "preset001", "name": "DeepSeek", "provider": "deepseek",
            "model": "deepseek-chat", "api_key": "sk-preset",
            "base_url": "https://api.deepseek.com/v1",
        }])
        storage.set_active_llm_profile_id("preset001")

        sid = chat_store.create_session()["id"]
        at = AppTest.from_file("app.py", default_timeout=60)
        at.session_state["chat_session_loaded"] = True
        at.session_state["chat_session_id"] = sid
        at.session_state["show_chat"] = True
        at.session_state["mode"] = "single"
        at.session_state["chat_messages"] = [
            {"role": "user", "content": "画一下 AAPL 的K线"}]
        at.run()

        joined = "".join(str(m.value) for m in at.markdown)
        has_svg = "chat-chart" in joined and "<svg" in joined
        print("exceptions:", [str(e) for e in at.exception])
        print("fallback chart rendered:", has_svg)
        assert not at.exception, [str(e) for e in at.exception]
        assert has_svg, "兜底出图没有渲染！"
        # 兜底图应随消息持久化
        store = chat_store._load()
        last_assistant = None
        for sess in store["sessions"]:
            for m in sess.get("messages") or []:
                if m.get("role") == "assistant":
                    last_assistant = m
        assert last_assistant and last_assistant.get("charts"), "图表未持久化！"
        print("PASS 兜底出图：模型只回文字也有图，且随消息持久化")
finally:
    with open(REAL_CFG, "w") as f:
        f.write(real_content)
