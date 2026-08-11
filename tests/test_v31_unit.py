"""V3.1.2 单元测试：LLM 客户端 / 消息组装 / 存储 / i18n / markdown 转换 / 抽屉动作"""
import json, os, sys, tempfile, types
from unittest import mock

sys.path.insert(0, os.getcwd())

# ── 1. build_messages ──
from agent.prompts import build_messages, build_system_prompt
msgs = build_messages("zh", [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "嗨"},
    {"role": "bogus", "content": "drop?"},
])
assert msgs[0]["role"] == "system" and "金融" in msgs[0]["content"]
assert msgs[1] == {"role": "user", "content": "你好"}
assert msgs[3] == {"role": "user", "content": "drop?"}
assert build_system_prompt("fr") == build_system_prompt("en")
print("PASS build_messages / system prompt")

# ── 2. stream_chat 无 Key / mock 流 ──
from agent import llm_client
out = list(llm_client.stream_chat({}, msgs, lang="zh"))
assert out and "未配置" in "".join(out)
out_en = list(llm_client.stream_chat({}, msgs, lang="en"))
assert out_en and "configure" in "".join(out_en).lower()

class FakeDelta:
    content = None
class FakeChoice:
    def __init__(self, c): self.delta = types.SimpleNamespace(content=c)
class FakeChunk:
    def __init__(self, c): self.choices = [FakeChoice(c)]
class FakeResp:
    def __init__(self): self.chunks = [FakeChunk("你好"), FakeChunk("，世界")]
    def __iter__(self): return iter(self.chunks)
class FakeCompletions:
    def create(self, **kw):
        assert kw["model"] == "deepseek-chat" and kw["stream"] is True
        return FakeResp()
class FakeChat:
    completions = FakeCompletions()
class FakeClient:
    chat = FakeChat()

orig = llm_client.openai.OpenAI
llm_client.openai.OpenAI = lambda **kw: FakeClient()
try:
    out = list(llm_client.stream_chat(
        {"api_key": "sk-x", "base_url": "https://api.deepseek.com/v1",
         "model": "deepseek-chat"}, msgs, lang="zh"))
finally:
    llm_client.openai.OpenAI = orig
assert "".join(out) == "你好，世界"
print("PASS stream_chat no-key / streamed chunks")

# ── 3. storage upsert/delete/active ──
import data.storage as storage
tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp.write('{"api_key": "k", "watchlist": ["AAPL"]}')
tmp.close()
storage.CONFIG_PATH = tmp.name
try:
    p1 = storage.upsert_llm_profile({"name": "DeepSeek", "model": "deepseek-chat",
                                     "api_key": "a", "base_url": "u", "provider": "deepseek"})
    pid = p1[0]["id"]
    p2 = storage.upsert_llm_profile({"name": "DeepSeek", "model": "deepseek-r1",
                                     "api_key": "b", "base_url": "u", "provider": "deepseek"})
    assert len(p2) == 1 and p2[0]["id"] == pid and p2[0]["api_key"] == "b"
    p3 = storage.upsert_llm_profile({"name": "OpenAI", "model": "gpt-4o",
                                     "api_key": "c", "base_url": "u", "provider": "openai"})
    assert len(p3) == 2
    storage.set_active_llm_profile_id(pid)
    assert storage.get_active_llm_profile_id() == pid
    storage.delete_llm_profile(pid)
    assert len(storage.get_llm_profiles()) == 1 and storage.get_active_llm_profile_id() == ""
    assert storage.load_config().get("api_key") == "k"
    os.remove(tmp.name)
    assert storage.load_config() == {}
    print("PASS storage upsert/delete/active")
finally:
    storage.CONFIG_PATH = os.path.join(os.getcwd(), ".agent_config.json")
    if os.path.exists(tmp.name):
        os.remove(tmp.name)

# ── 4. markdown → HTML 转换器 ──
from components.chat import _md_to_html
md = "**加粗** 和 `code`\n\n- 项目一\n- 项目二\n\n1. 第一\n2. 第二\n\n### 小标题\n\n```python\nprint('x')\n```\n\n> 引用\n\n[链接](https://a.b)"
h = _md_to_html(md)
assert "<strong>加粗</strong>" in h and "<code>code</code>" in h
assert "<ul>" in h and "项目一" in h and "<ol>" in h and "第一" in h
assert "<h4>小标题</h4>" in h and "<pre><code>" in h and "<blockquote>引用</blockquote>" in h
assert '<a href="https://a.b"' in h
h2 = _md_to_html("<script>alert(1)</script>")
assert "<script>" not in h2 and "&lt;script&gt;" in h2
assert _md_to_html("") == "" and _md_to_html(None) == ""
print("PASS md_to_html")

# ── 5. 抽屉动作处理（mock session_state）──
import components.chat as chat
class FakeSS(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v
ss = FakeSS(chat_messages=[], show_chat=False)
with mock.patch.object(chat.st, "session_state", ss):
    chat.handle_ai_action({"action": "toggle"}, "zh")
    assert ss["show_chat"] is True
    chat.handle_ai_action({"action": "send", "text": "  你好  "}, "zh")
    assert ss["chat_messages"] == [{"role": "user", "content": "你好"}]
    chat.handle_ai_action({"action": "send", "text": ""}, "zh")
    assert len(ss["chat_messages"]) == 1  # 空文本不发送
    chat.handle_ai_action({"action": "clear"}, "zh")
    assert ss["chat_messages"] == []
    chat.handle_ai_action({"action": "close"}, "zh")
    assert ss["show_chat"] is False
    # mini：最小化 → show_mini 置真；再次 → 恢复
    ss["show_chat"] = True
    chat.handle_ai_action({"action": "mini"}, "zh")
    assert ss["show_mini"] is True
    chat.handle_ai_action({"action": "mini"}, "zh")
    assert ss["show_mini"] is False
    # 关闭时重置迷你态
    ss["show_chat"] = True
    ss["show_mini"] = True
    chat.handle_ai_action({"action": "close"}, "zh")
    assert ss["show_chat"] is False and ss["show_mini"] is False
    # toggle 关闭时同样重置迷你态
    ss["show_chat"] = True
    ss["show_mini"] = True
    chat.handle_ai_action({"action": "toggle"}, "zh")
    assert ss["show_chat"] is False and ss["show_mini"] is False
    chat.handle_ai_action({"action": "bogus"}, "zh")  # 未知动作忽略
    chat.handle_ai_action("not-a-dict", "zh")          # 非 dict 忽略
    # 历史上限 30 条
    for i in range(35):
        chat.handle_ai_action({"action": "send", "text": f"msg{i}"}, "zh")
    assert len(ss["chat_messages"]) == 30
    print("PASS handle_ai_action")

# ── 6. i18n 完整性 ──
import re
calls = set()
for root, _, files in os.walk("."):
    if ".git" in root: continue
    for f in files:
        if f.endswith(".py"):
            calls |= set(re.findall(r'\bt\(\s*"([a-zA-Z0-9_]+)"', open(os.path.join(root, f)).read()))
src = open("i18n.py").read()
en_b = re.search(r'"en":\s*\{(.*?)\n    \},', src, re.S).group(1)
zh_b = re.search(r'"zh":\s*\{(.*?)\n    \},', src, re.S).group(1)
en_k = set(re.findall(r'"([a-zA-Z0-9_]+)"\s*:', en_b))
zh_k = set(re.findall(r'"([a-zA-Z0-9_]+)"\s*:', zh_b))
assert not (calls - en_k) and not (calls - zh_k), (calls - en_k, calls - zh_k)
assert en_k == zh_k
print(f"PASS i18n ({len(en_k)} keys, en==zh)")

print("\nALL UNIT TESTS PASSED")
