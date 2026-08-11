"""V3.2.1 工具层测试：tools / executor / prompts / i18n（全部 mock，无网络）"""
import os, sys, types, json
from unittest import mock

sys.path.insert(0, os.getcwd())

import agent.tools as at
import agent.executor as ex
from agent.prompts import build_messages, build_system_prompt

# ── 1. 参数校验 ──
assert at.clean_ticker(" aapl ") == "AAPL"
for bad in ("", "TOO-LONG-TICKER-XX", "ab cd", "$AAPL"):
    try:
        at.clean_ticker(bad)
        raise AssertionError(f"should reject {bad!r}")
    except ValueError:
        pass
assert at.clean_interval("1WEEK") == "1week"
assert at.clean_interval("1hour") == "1day"
assert at.clean_days("abc") == 365
assert at.clean_days(10) == 30
assert at.clean_days(99999) == 3650
print("PASS param validation")

# ── 2. dispatch_tool 未知工具 / 错误参数 ──
assert "unknown tool" in at.dispatch_tool("nope", {})["error"]
assert "must be a JSON object" in at.dispatch_tool("get_quote", [1])["error"]
r = at.dispatch_tool("get_quote", {"ticker": "bad ticker"})
assert "invalid ticker" in r["error"]
r = at.dispatch_tool("compare", {"tickers": ["AAPL"]})
assert "at least 2" in r["error"]
print("PASS dispatch_tool errors")

# ── 3. K 线摘要（本地假数据）──
fake_rows = []
px = 100.0
for i in range(120):
    o, c = px, px + (0.5 if i % 2 else -0.3)
    hi, lo = max(o, c) + 1.0, min(o, c) - 1.0
    fake_rows.append({"datetime": f"2026-01-{i:02d}", "open": f"{o:.2f}",
                      "high": f"{hi:.2f}", "low": f"{lo:.2f}",
                      "close": f"{c:.2f}", "volume": str(1_000_000 + i)})
    px = c
with mock.patch.object(at, "_time_series_with_fallback",
                       return_value=(list(fake_rows), "cache")):
    out = at.tool_get_time_series("AAPL", 365, "1day")
assert out["symbol"] == "AAPL" and out["bars"] == 120
assert out["source"] == "cache"
assert out["period_high"] > out["period_low"]
assert len(out["recent"]) == 5
assert out["recent"][-1]["close"] == float(fake_rows[-1]["close"])
print("PASS get_time_series summary")

# ── 4. 技术指标快照（本地计算）──
with mock.patch.object(at, "_time_series_with_fallback",
                       return_value=(list(fake_rows), "cache")):
    out = at.tool_get_indicators("AAPL", 365, "1day")
assert out["ma20"] is not None and out["ma60"] is not None
assert out["rsi14"] is not None
assert out["macd_dif"] is not None and out["boll_upper"] is not None
print("PASS get_indicators snapshot")

# ── 5. 财务提取（多候选键）──
stats = {"valuations_metrics": {"market_capitalization": 3.2e12, "trailing_pe": 31.2}}
fb = {"pe_ratio": 25.0, "market_cap": 2e12,
      "fifty_two_week": {"high": 260.0, "low": 180.0}}
out = at._extract_financials("AAPL", stats)
assert out["market_cap"] == 3.2e12 and out["pe_ratio"] == 31.2
out2 = at._extract_financials("AAPL", {"quote_fallback": fb})
assert out2["pe_ratio"] == 25.0 and out2["fifty_two_week_high"] == 260.0
assert out2["source"] == "tencent-fallback"
print("PASS extract_financials")

# ── 6. 序列化截断 ──
big = {"data": "x" * 6000}
s = at.result_to_json(big)
assert len(s) <= at.MAX_RESULT_CHARS + 20 and "truncated" in s
assert at.result_to_json(object())  # 不可序列化也不抛
print("PASS result_to_json truncation")

# ── 7. executor 基础判断 ──
assert ex._supports_tools("deepseek-chat")
assert not ex._supports_tools("deepseek-reasoner")
assert ex._supports_tools("gpt-4o-mini")
assert ex._tools_rejected(Exception("Error code: 400 - tools not supported"))
assert not ex._tools_rejected(Exception("Error code: 404 - model not found"))
assert ex._parse_args('{"a": 1}') == {"a": 1}
assert ex._parse_args("not-json") == {}
assert ex._history_from([{"role": "system", "content": "s"},
                         {"role": "user", "content": "u"}]) == [{"role": "user", "content": "u"}]
print("PASS executor guards")

# ── 8. _collect_stream：文本 + 工具调用分片 ──
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

d1 = FakeDelta(content="Let me check. ")
d2 = FakeDelta(content=None, tool_calls=[
    FakeToolDelta(0, id="call_1", name="get_", args='{"ticker": "AAP')])
d3 = FakeDelta(content=None, tool_calls=[
    FakeToolDelta(0, name="quote", args='L"}')])
text, calls = ex._collect_stream(FakeResp([d1, d2, d3]))
assert text == "Let me check. "
assert len(calls) == 1 and calls[0]["name"] == "get_quote"
assert calls[0]["id"] == "call_1" and calls[0]["arguments"] == '{"ticker": "AAPL"}'
print("PASS collect_stream")

# ── 9. run_agent：工具调用 → 执行 → 最终文本（mock OpenAI）──
class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)
class FakeChat:
    def __init__(self, responses): self.completions = FakeCompletions(responses)
class FakeClient:
    def __init__(self, responses): self.chat = FakeChat(responses)

tool_resp = FakeResp([
    FakeDelta(content=None, tool_calls=[
        FakeToolDelta(0, id="call_1", name="get_quote", args='{"ticker": "AAPL"}')]),
])
text_resp = FakeResp([
    FakeDelta(content="AAPL is at "), FakeDelta(content="$212.34"),
])

orig_openai = ex.openai.OpenAI
fc = None
try:
    fc = FakeClient([tool_resp, text_resp])
    ex.openai.OpenAI = lambda **kw: fc
    profile = {"api_key": "sk-x", "base_url": "http://x/v1", "model": "gpt-4o-mini"}
    events = list(ex.run_agent(profile, build_messages("zh", [
        {"role": "user", "content": "AAPL 现在多少钱？"}]), "zh"))
finally:
    ex.openai.OpenAI = orig_openai

kinds = [ev["t"] for ev in events]
assert "tool" in kinds and "text" in kinds, kinds
tool_ev = next(ev for ev in events if ev["t"] == "tool")
assert "AAPL" in tool_ev["c"] and "实时行情" in tool_ev["c"], tool_ev["c"]
full_text = "".join(ev["c"] for ev in events if ev["t"] == "text")
assert "AAPL is at $212.34" in full_text, full_text
# 第一次调用应带 tools schema
calls = fc.chat.completions.calls
assert calls and "tools" in calls[0], calls
print("PASS run_agent tool loop")

# ── 10. run_agent：reasoner 模型降级 ──
fake_gen = iter([{"t": "text", "c": "一般性回答。"}])
with mock.patch.object(ex, "stream_chat",
                       return_value=iter(["一般性回答。"])):
    profile = {"api_key": "sk-x", "base_url": "http://x/v1",
               "model": "deepseek-reasoner"}
    events = list(ex.run_agent(profile, build_messages("zh", [
        {"role": "user", "content": "hi"}]), "zh"))
assert events[0]["t"] == "tool" and "不支持" in events[0]["c"]
assert events[-1] == {"t": "text", "c": "一般性回答。"}
print("PASS run_agent fallback (reasoner)")

# ── 11. run_agent：tools 请求被拒 → 自动降级 ──
class RejectCompletions:
    def create(self, **kw):
        raise Exception("Error code: 400 - tools not supported by this model")
class RejectClient:
    chat = types.SimpleNamespace(completions=RejectCompletions())
orig_openai = ex.openai.OpenAI
try:
    ex.openai.OpenAI = lambda **kw: RejectClient()
    with mock.patch.object(ex, "stream_chat",
                           return_value=iter(["降级回答。"])):
        events = list(ex.run_agent(
            {"api_key": "sk-x", "base_url": "http://x/v1", "model": "qwen-plus"},
            build_messages("zh", [{"role": "user", "content": "hi"}]), "zh"))
finally:
    ex.openai.OpenAI = orig_openai
assert events[0]["t"] == "tool" and "不支持" in events[0]["c"]
assert events[-1] == {"t": "text", "c": "降级回答。"}
print("PASS run_agent auto-fallback on tools rejection")

# ── 12. prompts / i18n ──
assert "LIVE market data tools" in build_system_prompt("en", use_tools=True)
assert "无法获取实时行情" in build_system_prompt("zh", use_tools=False)
msgs = build_messages("zh", [{"role": "user", "content": "x"}], use_tools=True)
assert msgs[0]["role"] == "system" and "可用工具" in msgs[0]["content"]
import i18n
assert i18n.t("agent_tool_querying", "zh", tool="实时行情", subject="AAPL") == "正在获取 AAPL 的实时行情…"
assert i18n.t("agent_tool_limit", "en") != "agent_tool_limit"
print("PASS prompts / i18n")

print("\nALL V3.2 TOOL TESTS PASSED")
