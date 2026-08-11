"""chat_store 回归：原子存储 / 自动标题 / 会话上下文（stub 临时文件）"""
import json, os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.chat_store as cs

tmpdir = tempfile.mkdtemp()
path = os.path.join(tmpdir, "chat_history.json")

with mock.patch.object(cs, "CHAT_PATH", path):
    # 1. 初始空结构
    assert cs._load() == {"version": 1, "active_session_id": None, "sessions": []}
    # 2. 创建会话
    s1 = cs.create_session()
    assert s1["id"] and cs.get_session(s1["id"])
    assert cs.get_active_session_id() == s1["id"]
    # 3. 追加消息 + 自动标题
    cs.append_message(s1["id"], {"role": "user", "content": "请分析 AAPL 的 MACD"})
    s1b = cs.get_session(s1["id"])
    assert s1b["title"] == "请分析 AAPL 的 MACD", s1b["title"]
    assert s1b["messages"][0]["role"] == "user"
    # 4. 会话上下文快照
    assert cs.set_session_context(s1["id"], {"page": "single", "ticker": "AAPL"})
    assert cs.get_session_context(s1["id"]) == {"page": "single", "ticker": "AAPL"}
    # 5. 切换 / 新建 / 删除
    s2 = cs.create_session()
    assert cs.get_active_session_id() == s2["id"]
    assert cs.set_active_session_id(s1["id"]) is None
    assert cs.get_active_session_id() == s1["id"]
    assert cs.delete_session(s1["id"]) is True
    assert cs.get_session(s1["id"]) is None
    # 6. 原子写入：文件是合法 JSON 且无 .tmp 残留
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        json.load(f)
    assert not os.path.exists(path + ".tmp")

print("PASS chat_store regression")
