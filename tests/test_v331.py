"""V3.3.1 回归：多股对比问答 + 个性化记忆（自选股注入）"""
import json, os, sys, tempfile, types
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.storage as storage
import data.chat_store as chat_store
import agent.tools as at
import agent.executor as ex
import components.chat as chat
from agent.prompts import build_system_prompt

# ── 1. compare 工具结果含公司名 ──
QUOTES = {"AAPL": {"name": "Apple Inc.", "close": 234.5, "percent_change": 1.2,
                   "pe_ratio": 30.1, "market_cap": 3.5e12},
          "MSFT": {"name": "Microsoft Corp.", "close": 410.2, "percent_change": -0.4,
                   "pe_ratio": 35.0, "market_cap": 3.1e12}}
HIST = {}
for tk in ("AAPL", "MSFT"):
    rows, px = [], 100.0
    for i in range(30):
        rows.append({"datetime": f"2026-01-{i+1:02d}", "close": px,
                     "open": px, "high": px + 1, "low": px - 1})
        px += 1
    HIST[tk] = rows

with mock.patch.object(at, "fetch_compare_data",
                       return_value=(QUOTES, HIST, {"AAPL": "cache", "MSFT": "cache"})):
    out = at.tool_compare(["AAPL", "MSFT"])
assert len(out["items"]) == 2
a_item = next(i for i in out["items"] if i["symbol"] == "AAPL")
assert a_item["name"] == "Apple Inc.", a_item
assert a_item["pe_ratio"] == 30.1 and a_item["market_cap"] == 3.5e12
print("PASS compare includes company name")

# ── 2. 提示词含多股对比规则（en/zh）──
zh = build_system_prompt("zh")
en = build_system_prompt("en")
assert "多股对比" in zh and "compare 工具一次性传入" in zh
assert "Multi-stock comparisons" in en and "call the compare tool ONCE" in en
schema = json.dumps(at.TOOL_SCHEMAS, ensure_ascii=False)
assert "instead of calling get_quote" in schema
print("PASS compare prompt rules (en/zh + schema)")

# ── 3. 验收：多股对比问答完整链路（LLM 一轮 compare → 一轮回答）──
class FakeDelta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls
class FakeChoice:
    def __init__(self, d): self.delta = d
class FakeChunk:
    def __init__(self, d): self.choices = [FakeChoice(d)]
class FakeToolDelta:
    def __init__(self, index=0, id=None, name=None, args=None):
        self.index = index
        self.id = id
        self.function = types.SimpleNamespace(name=name, arguments=args)
class FakeResp:
    def __init__(self, deltas):
        self.chunks = [FakeChunk(d) for d in deltas]
    def __iter__(self): return iter(self.chunks)

tool_resp = FakeResp([FakeDelta(content=None, tool_calls=[
    FakeToolDelta(0, "c1", "compare", '{"tickers": ["AAPL", "MSFT"]}')])])
text_resp = FakeResp([FakeDelta(content="**对比结论**：AAPL PE 30.1 低于 MSFT 35.0，"),
                      FakeDelta(content="市值 AAPL 3.5T 高于 MSFT 3.1T。")])
orig_openai = ex.openai.OpenAI
try:
    calls = []
    class FakeCompletions:
        def __init__(self, responses): self.responses = list(responses)
        def create(self, **kw):
            calls.append(kw)
            return self.responses.pop(0)
    class FakeChat:
        def __init__(self, responses): self.completions = FakeCompletions(responses)
    class FakeClient:
        def __init__(self, responses): self.chat = FakeChat(responses)
    ex.openai.OpenAI = lambda **kw: FakeClient([tool_resp, text_resp])
    with mock.patch.object(at, "fetch_compare_data",
                           return_value=(QUOTES, HIST, {"AAPL": "cache", "MSFT": "cache"})):
        from agent.prompts import build_messages
        profile = {"api_key": "sk-x", "base_url": "http://x/v1", "model": "gpt-4o-mini"}
        events = list(ex.run_agent(profile, build_messages("zh", [
            {"role": "user", "content": "对比 AAPL 和 MSFT 的估值"}]), "zh"))
finally:
    ex.openai.OpenAI = orig_openai

tool_evs = [ev for ev in events if ev["t"] == "tool"]
assert len(tool_evs) == 1, tool_evs
assert "AAPL" in tool_evs[0]["c"] and "MSFT" in tool_evs[0]["c"], tool_evs[0]
full = "".join(ev["c"] for ev in events if ev["t"] == "text")
assert "AAPL PE 30.1" in full and "3.5T" in full, full
# 工具结果已把公司名传给模型
tool_msgs = [m for m in calls[1]["messages"] if m.get("role") == "tool"]
assert "Apple Inc." in tool_msgs[0]["content"], tool_msgs[0]["content"][:200]
print("PASS compare Q&A full pipeline")

# ── 4. 个性化记忆：自选股注入上下文 ──
tmp_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp_cfg.write(json.dumps({"api_key": "k", "lang": "zh", "watchlist": ["AAPL", "MSFT"]}))
tmp_cfg.close()
tmp_chat = os.path.join(tempfile.mkdtemp(), "chat_history.json")

class FakeSS(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v

ss = FakeSS(mode="single", cached={"ticker": "NVDA", "period_label": "1 年"},
            chat_session_id=None)
with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
     mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
     mock.patch.object(chat.st, "session_state", ss):
    ctx = chat._context_text("zh")
    assert "用户自选股" in ctx, ctx
    assert "AAPL、MSFT" in ctx, ctx

# 无自选股 → 不注入
tmp_cfg2 = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp_cfg2.write(json.dumps({"api_key": "k"}))
tmp_cfg2.close()
with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg2.name), \
     mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
     mock.patch.object(chat.st, "session_state", FakeSS(mode="single", cached={},
                                                        chat_session_id=None)):
    ctx2 = chat._context_text("zh")
    assert "用户自选股" not in ctx2
print("PASS watchlist injected into context")

print("\nALL V3.3.1 TESTS PASSED")
