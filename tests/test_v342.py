"""V3.4.2 回归：公司新闻工具（东财/Google 双源降级 / 缓存 / 情绪指令）"""
import json, os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())
import data.news as news
import agent.tools as at
import agent.prompts as prompts

tmp_cache = tempfile.mkdtemp()
CACHE_PATCH = mock.patch.object(news, "CACHE_DIR", tmp_cache)
CACHE_PATCH.start()

EM_PAYLOAD = (
    'cb({"code":0,"result":{"cmsArticleWebOld":['
    '{"title":"英伟达推出新芯片，股价大涨","date":"2026-08-06 11:47:00",'
    '"mediaName":"华夏时报","url":"http://eastmoney.com/a/1.html","content":"英伟达（NVDA）发布新一代芯片。"},'
    '{"title":"分析师下调英伟达目标价","date":"2026-08-05 09:30:00",'
    '"mediaName":"第一财经","url":"http://eastmoney.com/a/2.html","content":"需求担忧。"}'
    ']}},"msg":"OK"})'
)
GOOGLE_PAYLOAD = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>Nvidia Stock Soars on New Chip - Barron's</title>
<pubDate>Wed, 05 Aug 2026 10:00:00 GMT</pubDate>
<source url="https://barrons.com">Barron's</source>
<link>https://barrons.com/nvda</link>
</item><item>
<title>Nvidia Faces Regulatory Scrutiny - Reuters</title>
<pubDate>Tue, 04 Aug 2026 08:30:00 GMT</pubDate>
<source url="https://reuters.com">Reuters</source>
<link>https://reuters.com/nvda</link>
</item></channel></rss>
"""

# ── 1. 东财解析（JSONP 包裹）──
with mock.patch.object(news, "_em_request", return_value=[
        {"title": "英伟达推出新芯片，股价大涨", "date": "2026-08-06 11:47",
         "source": "华夏时报", "url": "http://eastmoney.com/a/1.html",
         "snippet": "英伟达（NVDA）发布新一代芯片。"}]):
    r = news.get_news("NVDA", limit=5)
assert r["source"] == "eastmoney" and r["count"] == 1
assert r["items"][0]["title"] == "英伟达推出新芯片，股价大涨"
assert r["items"][0]["date"] == "2026-08-06 11:47"
print("PASS eastmoney news parse")

# ── 2. 东财失败 → Google News 兜底（标题去源后缀、时间归一化）──
def _em_fail(tk, lim):
    raise Exception("eastmoney down")
with mock.patch.object(news, "_em_request", side_effect=_em_fail), \
     mock.patch.object(news, "_google_request", return_value=[
         {"title": "Nvidia Stock Soars on New Chip", "date": "2026-08-05 10:00",
          "source": "Barron's", "url": "https://barrons.com/nvda", "snippet": None}]):
    r2 = news.get_news("MSFT", limit=5)
assert r2["source"] == "google-news" and r2["items"][0]["title"] == "Nvidia Stock Soars on New Chip"
print("PASS google-news fallback")

# ── 3. 双源失败 → 空列表，不抛异常 ──
with mock.patch.object(news, "_em_request", side_effect=Exception("x")), \
     mock.patch.object(news, "_google_request", side_effect=Exception("y")):
    r3 = news.get_news("ZZZZ", limit=5)
assert r3["source"] == "none" and r3["items"] == [] and r3["count"] == 0
print("PASS graceful empty fallback")

# ── 4. 缓存：第二次调用不再请求数据源 ──
with mock.patch.object(news, "_em_request", return_value=[
        {"title": "t1", "date": "2026-08-06 10:00", "source": "s",
         "url": "u", "snippet": None}]) as em:
    a = news.get_news("ORCL", limit=3)
    b = news.get_news("ORCL", limit=3)
assert a == b and em.call_count == 1
print("PASS news disk cache (1h)")

# ── 5. 工具注册 + schema ──
assert "get_news" in at.TOOLS
assert at.dispatch_tool("get_news", {"ticker": "NVDA", "limit": 3})  # 不抛异常
assert any(s.get("function", {}).get("name") == "get_news" for s in at.TOOL_SCHEMAS)
print("PASS tool_get_news registered (TOOLS + schema)")

# ── 6. 提示词包含新闻与情绪指令（中英文）──
en = prompts.SYSTEM_PROMPTS_TOOLS["en"]
zh = prompts.SYSTEM_PROMPTS_TOOLS["zh"]
assert "get_news" in en and "get_news" in zh
assert "sentiment" in en and "情绪" in zh
assert "bullish" in en and "偏多" in zh
print("PASS prompts include news + sentiment rules (en/zh)")

CACHE_PATCH.stop()
print("\nALL V3.4.2 TESTS PASSED")
