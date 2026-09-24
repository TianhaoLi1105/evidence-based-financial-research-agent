"""会话的原子存储、自动标题与上下文测试。"""
import json, os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.chat_store as cs

tmpdir = tempfile.mkdtemp()
path = os.path.join(tmpdir, "chat_history.json")

with mock.patch.object(cs, "CHAT_PATH", path):
    assert cs._load() == {"version": 1, "active_session_id": None, "sessions": []}
    s1 = cs.create_session()
    assert s1["id"] and cs.get_session(s1["id"])
    assert cs.get_active_session_id() == s1["id"]
    cs.append_message(s1["id"], {"role": "user", "content": "请分析 AAPL 的 MACD"})
    s1b = cs.get_session(s1["id"])
    assert s1b["title"] == "请分析 AAPL 的 MACD", s1b["title"]
    assert s1b["messages"][0]["role"] == "user"
    assert cs.set_session_context(s1["id"], {"page": "single", "ticker": "AAPL"})
    assert cs.get_session_context(s1["id"]) == {"page": "single", "ticker": "AAPL"}
    s2 = cs.create_session()
    assert cs.get_active_session_id() == s2["id"]
    assert cs.set_active_session_id(s1["id"]) is None
    assert cs.get_active_session_id() == s1["id"]
    assert cs.delete_session(s1["id"]) is True
    assert cs.get_session(s1["id"]) is None
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        json.load(f)
    assert not os.path.exists(path + ".tmp")

print("PASS chat_store regression")
