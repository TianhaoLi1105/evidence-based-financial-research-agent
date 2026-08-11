"""V3.4.4 报告增强与风险复核回归测试（mock LLM，无需网络）"""
import os, sys
sys.path.insert(0, os.getcwd())

import agent.llm_client as llmc
from agent.executor import run_review
from agent.prompts import (SYSTEM_PROMPTS_TOOLS, REVIEW_SYSTEM_PROMPTS,
                           build_review_messages)
from i18n import t
from components.chat import _inline
from data.preferences import get_deep_review, set_deep_review

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


# ─── 1) 偏好开关读写 ────────────────────────────────────
set_deep_review(True)
check("review toggle set True", get_deep_review() is True)
set_deep_review(False)
check("review toggle set False", get_deep_review() is False)

# ─── 2) 提示词：规则 8 强化 ─────────────────────────────
en, zh = SYSTEM_PROMPTS_TOOLS["en"], SYSTEM_PROMPTS_TOOLS["zh"]
check("rule8 en has Data Check section", "## Data Check" in en)
check("rule8 en source tag rule", "(source: stockanalysis)" in en)
check("rule8 en risk backed by data", "back each risk with the specific data" in en)
check("rule8 en confidence rating", "high / medium / low" in en)
check("rule8 zh has 数据自检", "## 数据自检" in zh)
check("rule8 zh source tag rule", "（来源：stockanalysis）" in zh)
check("rule8 zh risk backed by data", "每条风险必须用对应的数据支撑" in zh)
check("rule8 zh confidence rating", "高 / 中 / 低" in zh)

# ─── 3) 风控复核提示词 ──────────────────────────────────
rev_en, rev_zh = REVIEW_SYSTEM_PROMPTS["en"], REVIEW_SYSTEM_PROMPTS["zh"]
check("review prompt en exists", "## Risk Review" in rev_en)
check("review prompt en has 4 checks", all(k in rev_en for k in (
    "Data support check", "Data gaps", "Missed risks", "Rating")))
check("review prompt en no invent", "never invent numbers" in rev_en)
check("review prompt zh exists", "## 风险复核意见" in rev_zh)
check("review prompt zh has 4 checks", all(k in rev_zh for k in (
    "数据支撑检查", "数据缺口", "遗漏风险", "复核结论")))
msgs = build_review_messages("zh", "研报正文")
check("review msgs roles", [m["role"] for m in msgs] == ["system", "user"])
check("review msgs carry report", "研报正文" in msgs[1]["content"])
msgs_en = build_review_messages("fr", "Report body")   # 未知语言回退 en
check("review lang fallback", "Report to review" in msgs_en[1]["content"])

# ─── 4) i18n 文案 ───────────────────────────────────────
for k in ("deep_review_toggle", "deep_review_hint", "deep_review_heading",
          "deep_review_running"):
    check(f"i18n {k} en", bool(t(k, "en")))
    check(f"i18n {k} zh", bool(t(k, "zh")))
check("i18n heading zh is markdown h2", t("deep_review_heading", "zh").startswith("## "))
check("i18n deep instructions has Data Check",
      "## Data Check" in t("deep_analysis_instructions", "en"))
check("i18n deep instructions zh has 数据自检",
      "## 数据自检" in t("deep_analysis_instructions", "zh"))

# ─── 5) executor run_review 流程（mock stream_chat）──────
calls = {}


def fake_stream(profile, msgs, lang, temperature=0.7, max_tokens=None):
    calls["profile"] = profile
    calls["system"] = msgs[0]["content"]
    calls["lang"] = lang
    calls["temp"] = temperature
    for piece in ("结论一：有数据支撑，通过。", "结论二：PE 缺失，建议谨慎。",
                  "评定：有条件通过。"):
        yield piece


llmc.stream_chat = fake_stream
out = list(run_review({"api_key": "k", "model": "m"}, "分析师研报正文", "zh"))
check("run_review streams text events",
      out and all(ev.get("t") == "text" for ev in out))
check("run_review collects chunks",
      "".join(ev["c"] for ev in out) == "结论一：有数据支撑，通过。结论二：PE 缺失，建议谨慎。评定：有条件通过。")
check("run_review lang passed", calls.get("lang") == "zh")
check("run_review lower temp", calls.get("temp") == 0.4)
check("run_review system is risk role", "风控复核员" in calls.get("system", ""))
check("run_review empty profile -> []", list(run_review({}, "报告", "zh")) == [])
check("run_review empty report -> []", list(run_review({"api_key": "k"}, "", "zh")) == [])


def err_stream(profile, msgs, lang, temperature=0.7, max_tokens=None):
    yield "模型调用失败（模拟）"


llmc.stream_chat = err_stream
out = list(run_review({"api_key": "k", "model": "m"}, "报告", "en"))
check("run_review error surfaces text", out and "模拟" in out[0]["c"])

# ─── 6) 来源标签渲染 ────────────────────────────────────
h = _inline("PE 36.2（来源：stockanalysis），52周高位 (Source: tencent)")
check("zh source tag rendered", '<span class="src-tag">来源：stockanalysis</span>' in h)
check("en source tag rendered", '<span class="src-tag">Source: tencent</span>' in h)
check("normal parens untouched", "(1.5x)" in _inline("溢价 (1.5x)"))

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL V3.4.4 TESTS PASSED")

# ─── 7) 修复回归：标题去重 + 弹窗开关 ────────────────────
from components.chat import _merge_review
check("merge: model title not duplicated",
      _merge_review("研报", "## 风险复核意见\n\n1. 通过。", "zh").count("## 风险复核意见") == 1)
check("merge: no title -> added once",
      _merge_review("研报", "1. 通过。", "zh").count("## 风险复核意见") == 1)
check("merge: en title respected",
      _merge_review("report", "## Risk Review\n\n1. ok.", "en").count("## Risk Review") == 1)
check("merge: empty review unchanged",
      _merge_review("研报", "", "zh") == "研报")
check("merge: whitespace review unchanged",
      _merge_review("研报", "   ", "zh") == "研报")

src = open(os.path.join(os.getcwd(), "components", "header.py"), encoding="utf-8").read()
check("header: close btn uses on_click",
      "key=\"modal_close\"," in src and "on_click=lambda: setattr(st.session_state, \"show_api\", False)" in src)
check("header: key btn is toggle",
      "not st.session_state.get(\"show_api\", False)" in src)
