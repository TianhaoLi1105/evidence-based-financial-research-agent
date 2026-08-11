"""V3.2.3 深度分析回归：意图识别 / 轨迹布局 / 双格式下载 / 轮数提升 / 快捷按钮"""
import base64, json, os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.storage as storage
import data.chat_store as chat_store
from components.chat import (_is_deep_request, _messages_html,
                             _report_download_html, _report_html, _md_to_html,
                             _DEEP_ROUNDS, _panel_args)
import components.chat as chat
from agent.executor import MAX_ROUNDS
import agent.executor as ex
import types

# ── 1. 深度分析意图识别（中/英）──
assert _is_deep_request("深度分析 AAPL")
assert _is_deep_request("帮我写一份 AAPL 的研报")
assert _is_deep_request("Deep analysis of MSFT")
assert _is_deep_request("give me a research report on TSLA")
assert not _is_deep_request("AAPL 现在多少钱")
assert not _is_deep_request("什么是 RSI")
assert not _is_deep_request("")
print("PASS deep request detection")

# ── 2. 消息区：工具轨迹多行 + 布局（轨迹贴近视口底部）──
MSGS = [{"role": "user", "content": "深度分析 AAPL"}]
h = _messages_html(MSGS, "zh", hint=["正在获取 AAPL 的实时行情…",
                                      "正在获取 AAPL 的财务数据…"])
assert h.count('class="chat-tool-step"') == 2, h
assert "实时行情" in h and "财务数据" in h
# 布局：disclaimer → 轨迹 → 气泡（DOM 靠前 = 视觉靠下）
assert h.index('class="chat-disclaimer"') < h.index("chat-tool-hint")
assert h.index("chat-tool-hint") < h.index("chat-bubble")
# 单条 str 兼容
h2 = _messages_html(MSGS, "zh", hint="正在获取 AAPL 的实时行情…")
assert h2.count('class="chat-tool-step"') == 1
# 无轨迹时无提示块
assert 'chat-tool-hint' not in _messages_html(MSGS, "zh")
print("PASS multi-line tool trace")

# ── 3. 研报下载：HTML 精美报告 + Markdown 双格式 ──
d = _report_download_html("zh", "## 公司概况\n\nAAPL\n\n## 结论\n\n数据来源：twelvedata")
assert d.count('class="chat-report-download"') == 2, d
assert 'href="data:text/html;base64,' in d
assert 'href="data:text/markdown;base64,' in d
assert "HTML 报告" in d and "Markdown" in d
html_b64 = d.split('data:text/html;base64,', 1)[1].split('"', 1)[0]
html_out = base64.b64decode(html_b64).decode("utf-8")
assert "<!DOCTYPE html>" in html_out and "深度分析报告" in html_out
assert "## 公司概况" not in html_out  # markdown 已转 HTML
assert "<h3>公司概况</h3>" in html_out
assert "仅供参考" in html_out
md_b64 = d.split('data:text/markdown;base64,', 1)[1].split('"', 1)[0]
assert base64.b64decode(md_b64).decode("utf-8").startswith("## 公司概况")
assert _report_download_html("zh", "   ") == ""
assert _report_html("x", "en").startswith("<!DOCTYPE html>")
print("PASS dual-format report download")

# ── 3b. markdown 表格 → HTML（报告排版用）──
tbl = _md_to_html("| 指标 | 数值 |\n| --- | --- |\n| PE | 31.2 |")
assert "overflow-x:auto" in tbl and "white-space:nowrap" in tbl, tbl  # 横向滚动 + 横排
assert "<table" in tbl and "<th" in tbl and "指标" in tbl and "31.2" in tbl, tbl
print("PASS markdown table")

# ── 3c. 快捷按钮：深度分析自动带当前股票 ──
class FakeSS(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v
ss = FakeSS(mode="single", show_chat=True, show_threads=False,
            show_mini=False, chat_messages=[],
            cached={"ticker": "AAPL"}, chat_session_id="s1")
with mock.patch.object(chat.st, "session_state", ss):
    args = _panel_args("zh", True)
    assert args["quick_labels"][0] == "深度分析 AAPL", args["quick_labels"]
    assert args["deep_quick_label"] == "深度分析 AAPL"
    assert len(args["quick_labels"]) == 5  # deep + 4 个概念问题
ss2 = FakeSS(mode="single", show_chat=True, show_threads=False,
             show_mini=False, chat_messages=[], cached={}, chat_session_id="s1")
with mock.patch.object(chat.st, "session_state", ss2):
    assert _panel_args("zh", True)["quick_labels"][0] == "深度分析"
print("PASS deep quick label")

# ── 4. executor：一轮并行多个工具 + max_rounds 生效 ──
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

def tool_call(i, name, args):
    return FakeToolDelta(i, id=f"c{i}", name=name, args=args)

tools_resp = FakeResp([FakeDelta(content=None, tool_calls=[
    tool_call(0, "get_profile", '{"ticker": "AAPL"}'),
    tool_call(1, "get_financials", '{"ticker": "AAPL"}'),
    tool_call(2, "get_time_series", '{"ticker": "AAPL", "days": 365}'),
    tool_call(3, "get_indicators", '{"ticker": "AAPL"}'),
])])
text_resp = FakeResp([FakeDelta(content="## 公司概况"), FakeDelta(content="\nAAPL 简介")])
orig = ex.openai.OpenAI
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
    ex.openai.OpenAI = lambda **kw: FakeClient([tools_resp, text_resp])
    from agent.prompts import build_messages
    profile = {"api_key": "sk-x", "base_url": "http://x/v1", "model": "gpt-4o-mini"}
    events = list(ex.run_agent(profile, build_messages("zh", [
        {"role": "user", "content": "深度分析 AAPL"}]), "zh", max_rounds=_DEEP_ROUNDS))
finally:
    ex.openai.OpenAI = orig

tool_hints = [ev["c"] for ev in events if ev["t"] == "tool"]
assert len(tool_hints) == 4, tool_hints
assert "AAPL" in "".join(tool_hints)
full = "".join(ev["c"] for ev in events if ev["t"] == "text")
assert "## 公司概况" in full
# 第二轮才发模型请求 → 证明多工具并行只用了一轮工具调用
assert len(calls) == 2, len(calls)
print("PASS executor 4-tool parallel round")

# ── 5. AppTest：深度分析端到端（下载入口 + 轮数 + 指令注入）──
from streamlit.testing.v1 import AppTest
tmp_cfg = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
tmp_cfg.write('{"api_key": "test-demo-key", "watchlist": ["AAPL"]}')
tmp_cfg.close()
tmp_chat = os.path.join(tempfile.mkdtemp(), "chat_history.json")

def fake_fetch_data(ticker, period_days, interval="1day"):
    return ({"symbol": ticker}, {}, [], {}, {}, "cache", "twelvedata")

captured = {}
def fake_agent(profile, messages, lang="en", max_rounds=3):
    captured["max_rounds"] = max_rounds
    captured["deep_instr"] = any(("## 公司概况" in str(m.get("content", ""))
                                  or "## Company Overview" in str(m.get("content", "")))
                                 for m in messages)
    yield {"t": "tool", "c": f"正在获取 AAPL 的实时行情…"}
    yield {"t": "tool", "c": f"正在获取 AAPL 的财务数据…"}
    yield {"t": "text", "c": "## 公司概况\nAAPL 是全球领先科技公司。\n\n"
                             "## 财务与估值\n市值 3.2 万亿美元。\n\n"
                             "## 技术面\nRSI 处于中性区间。\n\n"
                             "## 主要风险\n竞争加剧。\n\n"
                             "## 结论\n数据来源：twelvedata。"}

with mock.patch.object(storage, "CONFIG_PATH", tmp_cfg.name), \
     mock.patch.object(chat_store, "CHAT_PATH", tmp_chat), \
     mock.patch("services.stock_service.fetch_data", fake_fetch_data), \
     mock.patch("components.chat.run_agent", fake_agent):
    storage.save_llm_profiles([{
        "id": "p1", "name": "DeepSeek", "provider": "deepseek",
        "model": "deepseek-chat", "api_key": "sk-preset",
        "base_url": "https://api.deepseek.com/v1"}])
    storage.set_active_llm_profile_id("p1")
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    at.session_state["show_chat"] = True
    at.run()
    at.session_state["chat_messages"] = [{"role": "user", "content": "深度分析 AAPL"}]
    at.run()
    assert not at.exception, str(at.exception)
    assert captured["max_rounds"] == 4, captured
    assert captured["deep_instr"] is True, captured
    md = " ".join(str(m.value) for m in at.markdown)
    assert 'class="chat-report-download"' in md, "下载入口缺失"
    assert "data:text/html;base64," in md
    assert "data:text/markdown;base64," in md
    assert ("HTML 报告" in md or "HTML Report" in md)
    # 布局：下载入口嵌入 AI 回答气泡内，且轨迹在气泡下方（视觉底部）
    assert md.index("chat-report-downloads") > md.index("chat-bubble chat-bubble-assistant")
    # 工具轨迹是过程提示：生成完成后不再显示
    assert "正在获取 AAPL 的实时行情" not in md, "完成后不应残留工具轨迹"
    assert 'class="chat-tool-step"' not in md, "完成后不应残留工具轨迹步骤"

    # 对照：普通问题不触发深度模式
    captured.clear()
    at.session_state["chat_messages"] = [{"role": "user", "content": "什么是 RSI"}]
    at.run()
    assert captured["max_rounds"] == MAX_ROUNDS, captured
    md2 = " ".join(str(m.value) for m in at.markdown)
    # CSS 选择器始终存在，需检查的是下载链接本体（data URI）不出现
    assert "data:text/markdown;base64," not in md2
    print("PASS AppTest deep analysis e2e")

print("\nALL V3.2.3 TESTS PASSED")
