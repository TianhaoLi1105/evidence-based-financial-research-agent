"""V3.3.2 回归：对话内出图（SVG 生成 / plot_chart 工具 / executor 传递 / 消息区渲染）"""
import json, os, sys, types
from unittest import mock

sys.path.insert(0, os.getcwd())
import agent.tools as at
import agent.executor as ex
import components.chat as chat
from components.chat import _messages_html
from agent.prompts import build_system_prompt, build_messages

ROWS = [{"datetime": f"2026-01-{i+1:02d}", "open": 100+i, "high": 102+i,
         "low": 99+i, "close": 101+i, "volume": 1_000_000+i*1000}
        for i in range(30)]
ROWS_DOWN = [{"datetime": f"2026-01-{i+1:02d}", "open": 200-i, "high": 201-i,
              "low": 198-i, "close": 199-i, "volume": 1_000_000}
             for i in range(30)]
QUOTES = {"AAPL": {"name": "Apple Inc.", "close": 131.0},
          "MSFT": {"name": "Microsoft Corp.", "close": 210.0}}
HIST = {"AAPL": ROWS, "MSFT": ROWS}

# ── 1. SVG 生成器 ──
from components.chart_svg import price_line_svg, candlestick_svg, multi_line_svg
up = price_line_svg(ROWS)
down = price_line_svg(ROWS_DOWN)
assert up.startswith("<svg") and "polyline" in up and "polygon" in up
assert "#34c759" in up and "#34c759" not in down and "#ff3b30" in down
assert "101.00" in up or "101" in up  # 收盘标注
c = candlestick_svg(ROWS)
assert "<svg" in c and "<rect" in c and "<line" in c
assert "opacity=\".4\"" in c  # 成交量柱
m = multi_line_svg(HIST)
assert "<svg" in m and "polyline" in m and "AAPL" in m and "MSFT" in m
assert "%.1f" not in m  # 图例含格式化涨跌
print("PASS svg generators (up/down/candlestick/multi)")

# ── 2. plot_chart 工具 ──
with mock.patch.object(at, "_time_series_with_fallback",
                       return_value=(list(ROWS), "cache")):
    out = at.tool_plot_chart(["AAPL"])
assert out["symbol"] == "AAPL" and out["chart_type"] == "line"
assert out["bars"] == 30 and out["_chart_html"].startswith("<svg")
with mock.patch.object(at, "_time_series_with_fallback",
                       return_value=(list(ROWS_DOWN), "cache")):
    out2 = at.tool_plot_chart(["AAPL"], chart_type="candlestick")
assert out2["chart_type"] == "candlestick" and "<rect" in out2["_chart_html"]
with mock.patch.object(at, "fetch_compare_data",
                       return_value=(QUOTES, HIST, {"AAPL": "cache", "MSFT": "cache"})):
    out3 = at.tool_plot_chart(["AAPL", "MSFT"])
assert out3["tickers"] == ["AAPL", "MSFT"] and "polyline" in out3["_chart_html"]
# 非法 chart_type 回退 line
with mock.patch.object(at, "_time_series_with_fallback",
                       return_value=(list(ROWS), "cache")):
    assert at.tool_plot_chart(["AAPL"], chart_type="pie")["chart_type"] == "line"
# 无数据 → error 无 html
with mock.patch.object(at, "_time_series_with_fallback", return_value=([], "cache")):
    err = at.tool_plot_chart(["AAPL"])
    assert "error" in err and "_chart_html" not in err
print("PASS plot_chart tool")

# ── 3. executor：图表 HTML 只进 UI 不进模型消息 ──
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
    FakeToolDelta(0, "c1", "plot_chart", '{"tickers": ["AAPL"], "chart_type": "line"}')])])
text_resp = FakeResp([FakeDelta(content="这是 AAPL 的走势图。")])
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
    with mock.patch.object(at, "_time_series_with_fallback",
                           return_value=(list(ROWS), "cache")):
        profile = {"api_key": "sk-x", "base_url": "http://x/v1", "model": "gpt-4o-mini"}
        events = list(ex.run_agent(profile, build_messages("zh", [
            {"role": "user", "content": "画一下 AAPL 的走势"}]), "zh"))
finally:
    ex.openai.OpenAI = orig_openai

tool_evs = [ev for ev in events if ev["t"] == "tool"]
assert len(tool_evs) == 1 and tool_evs[0]["html"].startswith("<svg"), tool_evs[0]
assert "价格图表" in tool_evs[0]["c"]
tool_msg = [m for m in calls[1]["messages"] if m.get("role") == "tool"][0]
assert "_chart_html" not in tool_msg["content"], "图表 HTML 不应进模型消息"
assert "<svg" not in tool_msg["content"]
assert "chart generated" in tool_msg["content"]
print("PASS executor passes chart HTML to UI only")

# ── 4. 消息区渲染 + 持久化（图表存在消息 dict 的 charts 字段里）──
msgs = [{"role": "user", "content": "画一下 AAPL 的走势"},
        {"role": "assistant", "content": "这是 AAPL 的走势图。", "charts": [up]}]
h = _messages_html(msgs, "zh")
assert 'class="chat-chart"' in h and "<svg" in h
assert h.index("chat-chart") > h.index("chat-bubble chat-bubble-assistant")
# 无图消息不渲染图表
assert _messages_html([{"role": "assistant", "content": "hi"}], "zh").count("chat-chart") == 0
# 历史多轮：图表跟随各自的那条 AI 回答
multi = [{"role": "user", "content": "AAPL"},
         {"role": "assistant", "content": "a", "charts": ["<svg>A1</svg>"]},
         {"role": "user", "content": "MSFT"},
         {"role": "assistant", "content": "b", "charts": ["<svg>B1</svg>", "<svg>B2</svg>"]}]
hm = _messages_html(multi, "zh")
assert hm.count("chat-chart") == 3 and "A1" in hm and "B2" in hm
# chat_store 持久化往返：带 charts 的消息刷新后仍保留
import data.chat_store as cs
sid = cs.create_session()["id"]
cs.append_message(sid, {"role": "user", "content": "画K线"})
cs.append_message(sid, {"role": "assistant", "content": "图", "charts": [up]})
loaded = [m for m in cs.get_session(sid)["messages"] if m.get("role") == "assistant"]
assert loaded and "<svg" in loaded[0]["charts"][0]
cs.delete_session(sid)
print("PASS messages render charts + persistence round-trip")

# ── 5. 提示词与 schema ──
zh = build_system_prompt("zh")
en = build_system_prompt("en")
assert "plot_chart" in zh and "画图" in zh and "K线" in zh
assert "plot_chart" in en and "candlestick" in en
names = [s["function"]["name"] for s in at.TOOL_SCHEMAS]
assert "plot_chart" in names
# 画图意图识别 + 指令注入文案
from i18n import t
assert t("chart_plot_instructions", "zh").startswith("用户正在请求画图")
assert t("chart_plot_instructions", "en").startswith("The user is asking for a chart")
from components.chat import _is_chart_request
for q in ["画一下 AAPL 的K线", "帮我画张走势图", "show me a chart of NVDA",
          "plot AAPL and MSFT", "对比图", "candlestick of TSLA"]:
    assert _is_chart_request(q), q
for q in ["AAPL 的市盈率是多少", "解释一下 RSI", "深度分析 AAPL", "你好"]:
    assert not _is_chart_request(q), q
print("PASS prompts/schema + chart intent detection")

# ── 6. 流式阶段：pending_charts 立即显示（不等最终回答）──
h2 = _messages_html(msgs, "zh", hint=["正在获取价格图表…"], pending_charts=[up])
assert "chat-pending-charts" in h2 and "chat-chart" in h2 and "<svg" in h2
assert "chat-tool-hint" in h2
print("PASS pending charts render during streaming")

# ── 7. 服务端兜底出图（模型漏调工具时）──
from components.chat import _extract_tickers, _server_chart_fallback
assert _extract_tickers("画一下 AAPL 的K线") == ["AAPL"]
assert _extract_tickers("对比 aapl 和 msft 走势") == ["AAPL", "MSFT"]
assert _extract_tickers("什么是K线") == []          # 单字母 K 不应被当成代码
assert _extract_tickers("解释一下RSI") == ["RSI"]  # 提取归提取，兜底另有动作词门槛
# RSI 是 3 位大写，会被提取，但兜底要求画图动作词，不会误触发
def _fake_plot(tickers, days=365, interval="1day", chart_type="line"):
    return {"symbol": tickers[0], "chart_type": chart_type,
            "_chart_html": "<svg>fallback</svg>"}
with mock.patch.object(chat, "tool_plot_chart", _fake_plot):
    assert _server_chart_fallback("画一下 AAPL 的K线", "zh") == ["<svg>fallback</svg>"]
    assert _server_chart_fallback("什么是K线", "zh") == []      # 解释题不触发
    assert _server_chart_fallback("解释一下RSI", "zh") == []    # 概念题不触发
print("PASS server-side chart fallback (intent + ticker extraction)")

print("\nALL V3.3.2 TESTS PASSED")
