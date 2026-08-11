"""语言本地记忆回归：初始化恢复 + 切换持久化 + AppTest 端到端"""
import json, os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.storage as storage
import services.app_state as app_state
import components.header as header

# ── 1. 初始化：从配置恢复上次语言 ──
tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp.write(json.dumps({"api_key": "k1", "lang": "zh", "watchlist": ["AAPL"]}))
tmp.close()

class FakeSS(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v

with mock.patch.object(storage, "CONFIG_PATH", tmp.name), \
     mock.patch.object(app_state.st, "session_state", FakeSS()):
    app_state.init_session_state()
    assert app_state.st.session_state["lang"] == "zh", app_state.st.session_state["lang"]

# 无配置 → 默认英文
tmp2 = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp2.write("{}")
tmp2.close()
ss2 = FakeSS()
with mock.patch.object(storage, "CONFIG_PATH", tmp2.name), \
     mock.patch.object(app_state.st, "session_state", ss2):
    app_state.init_session_state()
    assert ss2["lang"] == "en"

# 非法语言值 → 回退英文
tmp3 = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp3.write(json.dumps({"lang": "fr"}))
tmp3.close()
ss3 = FakeSS()
with mock.patch.object(storage, "CONFIG_PATH", tmp3.name), \
     mock.patch.object(app_state.st, "session_state", ss3):
    app_state.init_session_state()
    assert ss3["lang"] == "en"
print("PASS init restores saved lang")

# ── 2. 切换语言 → 写入配置 ──
tmp4 = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp4.write(json.dumps({"api_key": "k1"}))
tmp4.close()
ss4 = FakeSS(lang="en")
with mock.patch.object(storage, "CONFIG_PATH", tmp4.name), \
     mock.patch.object(header.st, "session_state", ss4):
    header.next_lang()
    assert ss4["lang"] == "zh"
    saved = storage.load_config()
    assert saved.get("lang") == "zh", saved
    header.next_lang()
    assert ss4["lang"] == "en" and storage.load_config().get("lang") == "en"
print("PASS next_lang persists")

# ── 3. AppTest：配置 lang=zh → 启动即中文 ──
import data.chat_store as chat_store
from streamlit.testing.v1 import AppTest
tmp_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp_cfg.write(json.dumps({"api_key": "test-demo-key", "lang": "zh",
                          "watchlist": ["AAPL"]}))
tmp_cfg.close()
tmp_chat = os.path.join(tempfile.mkdtemp(), "chat_history.json")

def fake_fetch_data(ticker, period_days, interval="1day"):
    return ({"symbol": ticker}, {}, [], {}, {}, "cache", "twelvedata")

with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
     mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
     mock.patch("services.stock_service.fetch_data", fake_fetch_data):
    storage.save_llm_profiles([{"id": "p1", "name": "DeepSeek",
                                "provider": "deepseek", "model": "deepseek-chat",
                                "api_key": "sk", "base_url": "https://api.deepseek.com/v1"}])
    storage.set_active_llm_profile_id("p1")
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert at.session_state["lang"] == "zh", at.session_state["lang"]
    assert any("金融研究助手" in str(m.value) for m in at.markdown), "应为中文标题"
print("PASS AppTest boots in saved lang")

print("\nALL LANG MEMORY TESTS PASSED")
