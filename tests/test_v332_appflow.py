"""V3.3.2 AppTest：真实链路复现——用户在 AI 框发画图消息，
mock run_agent 产出 tool 事件(含图表HTML) + 文本，检查最终渲染的 HTML 里有图表。"""
import os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.storage as storage
import data.chat_store as chat_store
import agent.tools as at
import components.chat as chat_mod

REAL_CFG = os.path.join(os.getcwd(), ".agent_config.json")
with open(REAL_CFG) as f:
    real_content = f.read()

tmp_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp_cfg.write('{"api_key": "test-demo-key", "watchlist": ["AAPL"]}')
tmp_cfg.close()

tmp_chat = os.path.join(tempfile.mkdtemp(), "chat_history.json")

ROWS = [{"datetime": f"2026-01-{i+1:02d}", "open": 100+i, "high": 102+i,
         "low": 99+i, "close": 101+i, "volume": 1000000+i*1000} for i in range(30)]

def fake_run_agent(profile, messages, lang="en", max_rounds=3):
    yield {"t": "tool", "c": "正在获取 AAPL 的价格图表…",
           "html": "<svg viewBox=\"0 0 420 200\"><polyline points=\"1,1 2,2\"/></svg>"}
    yield {"t": "text", "c": "这是 AAPL 的K线图。"}

try:
    with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
         mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
         mock.patch.object(chat_mod, "run_agent", fake_run_agent):
        from streamlit.testing.v1 import AppTest
        storage.save_llm_profiles([{
            "id": "preset001", "name": "DeepSeek", "provider": "deepseek",
            "model": "deepseek-chat", "api_key": "sk-preset",
            "base_url": "https://api.deepseek.com/v1",
        }])
        storage.set_active_llm_profile_id("preset001")

        at = AppTest.from_file("app.py", default_timeout=60)
        # 预置：AI 框已打开、会话已加载、最后一条是用户画图消息
        at.session_state["chat_session_loaded"] = True
        at.session_state["show_chat"] = True
        at.session_state["chat_messages"] = [
            {"role": "user", "content": "画一下 AAPL 的K线"}]
        at.run()

        print("exceptions:", [str(e) for e in at.exception])
        all_md = [str(m.value) for m in at.markdown]
        joined = "".join(all_md)
        has_svg = "chat-chart" in joined and "<svg" in joined
        has_pending = "chat-pending-charts" in joined
        has_text = "这是 AAPL 的K线图" in joined
        print("has chart:", has_svg, "| pending stage:", has_pending, "| answer:", has_text)
        assert not at.exception, [str(e) for e in at.exception]
        assert has_svg, "图表没有渲染出来！"
        assert has_text
        print("PASS 真实链路：AI 画图请求 → 图表出现在消息区")
finally:
    with open(REAL_CFG, "w") as f:
        f.write(real_content)
