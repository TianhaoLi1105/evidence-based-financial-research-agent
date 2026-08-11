# 📊 Evidence-Based Financial Research Agent

**English** | [中文](README.md)

**A real-data financial research assistant** — enter a ticker to get quotes, fundamentals, news, and AI-generated deep research reports.

Built with [Streamlit](https://streamlit.io). All data comes from **free data sources** with automatic multi-source fallback. It ships with a conversational **AI Agent** (DeepSeek / Qwen / Zhipu GLM / OpenAI / Ollama) that produces professional research reports with per-claim source citations and an independent risk-review pass.

> ⚠️ This project is for learning and research only. Nothing here constitutes investment advice.

---

## ✨ Highlights

### 📈 Market Analytics (V1–V2)
- Candlestick charts for any US stock (daily / weekly / monthly) with time-range switching
- Technical indicators: MA20 / MA60 / EMA12/26 / MACD / BOLL / RSI14
- Company profiles: description, industry, sector, CEO, employee count, website (free-source fallback)
- Fundamentals: revenue, net income, gross margin, debt ratio, cash flow, EPS, ROE, etc. (four-source fallback)
- Multi-stock comparison: normalized trend chart + valuation/fundamental comparison table + watchlist
- Market overview (three major indices) and K-line CSV export

### 🤖 AI Agent (V3)
- Floating chat window with streaming output and multi-topic conversations (persisted locally)
- **9 data tools**: real-time quotes, historical K-lines, deep fundamentals, company profile, technical indicators, multi-stock comparison, valuation assessment, news sentiment, in-chat charting
- **Deep research report**: automatically runs the full tool chain and outputs a 6-chapter structured report (company overview / financials & valuation / technicals / key risks / data self-check / conclusion), downloadable as HTML or Markdown
- **Per-claim source citation**: every key number is attributed to its source — no fabrication
- **Analyst → Risk review** (optional): an independent risk-review role re-checks data support and flags gaps or missed risks
- **Valuation check**: ask "Is AAPL expensive right now?" → compares against industry peers and the 52-week price position
- **News & sentiment**: fetches company news and scores headline sentiment
- In-chat chart generation (K-line / line / multi-stock comparison)
- Personalized memory: remembers frequently viewed tickers and topics, injected into conversation context

### 🌍 Experience
- One-click Chinese / English switching (language preference remembered)
- Apple-style dark UI, no third-party tracking
- Switch between multiple models: DeepSeek / Qwen / GLM / OpenAI / Ollama / custom endpoint

---

## 📸 Screenshots

Screenshots live in `docs/screenshots/` (regenerate with the bundled script on first run):

```bash
python scripts/capture_screenshots.py   # requires playwright
```

| Single-stock analysis | AI chat & deep research |
| --- | --- |
| ![Single-stock analysis](docs/screenshots/single.png) | ![AI chat](docs/screenshots/chat.png) |

| Multi-stock comparison | Deep research report (download) |
| --- | --- |
| ![Multi-stock comparison](docs/screenshots/compare.png) | ![Deep research report](docs/screenshots/report.png) |

---

## 🚀 Quick Start

### 1. Requirements
- Python **3.9+**
- An LLM API Key (optional — charting works without it; the AI Agent is unlocked once configured)

### 2. Install dependencies

```bash
git clone https://github.com/TianhaoLi1105/evidence-based-financial-research-agent.git
cd evidence-based-financial-research-agent
pip install -r requirements.txt
```

### 3. Run

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

### 4. Configuration
- **Data API (optional)**: click `KEY` in the top-right corner → enter a free [Twelve Data](https://twelvedata.com) key. Without one, the app automatically falls back to free sources (Tencent Finance / stockanalysis.com / East Money) — slightly fewer fields, but everything still works.
- **AI model (optional)**: click `KEY` → the `AI Model` tab → pick a provider and enter your API key. Supported:

| Provider | Base URL | Default model |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| Zhipu GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen2.5` |
| Custom | any OpenAI-compatible endpoint | — |

---

## 🏗 Architecture

```
app.py                    # Streamlit entry: single-stock / compare / market overview
├── agent/                # AI Agent layer
│   ├── tools.py          #   9 data tools (function calling)
│   ├── executor.py       #   tool-call loop + risk review
│   ├── prompts.py        #   system prompts (13 rules + risk-review role)
│   └── llm_client.py     #   multi-provider OpenAI-compatible client
├── data/                 # data layer (free sources + 24h cache)
│   ├── fundamentals.py   #   four-source deep fundamentals
│   ├── news.py           #   East Money → Google News
│   ├── valuation.py      #   relative valuation (peer comparison)
│   ├── chat_store.py     #   multi-topic session persistence
│   └── preferences.py    #   personalized memory
├── services/             # quote/fallback chains
├── components/           # UI components (K-line, compare, cards, AI chat)
└── i18n.py               # Chinese/English UI strings (215 keys)
```

**Source fallback chains (free-first)**

| Capability | Fallback chain |
| --- | --- |
| Real-time quotes | Twelve Data → Tencent Finance |
| Fundamentals | Twelve Data → stockanalysis.com → yfinance → Sina |
| Company profile | Twelve Data → stockanalysis.com |
| News | East Money → Google News |
| Valuation | Tencent/stockanalysis + local computation (peer mapping + 52-week percentile) |

Every result carries a `source` field; failures degrade silently, missing fields show as N/A — **nothing is ever fabricated**.

---

## ✅ Testing

The project maintains 16 regression test groups (tool layer, fallback chains, AI event stream, rendering, memory — all with **mocked data sources, no network needed**):

```bash
bash tests/run_all.sh        # run all 16 groups at once
python tests/test_v343.py    # run a single group (e.g. valuation)
```

| Test files | Coverage |
| --- | --- |
| `tests/test_v31_*.py` | LLM client, message assembly, i18n, app flow |
| `tests/test_v32_*.py` | tool layer, deep analysis, charts, chart fallback |
| `tests/test_v33_*.py` | context enhancement, chart persistence, personalized memory |
| `tests/test_v341.py` – `test_v345.py` | fundamentals, news sentiment, valuation, report/risk review, wrap-up |
| `tests/test_lang_mem.py` / `test_chat_store.py` | language memory, multi-topic storage |

---

## 🔒 Privacy & Security

- **API keys stay local**: `.agent_config.json` (gitignored — never committed)
- **Chat history & personal profile stay local**: `chat_history.json`, `.cache/` (both gitignored)
- **No third-party tracking**: the app collects and uploads nothing
- **Public free endpoints only**: no user privacy data involved
- **Keys never appear in logs or code**

---

## 📄 Disclaimer

For **learning and research** purposes only. All data comes from public free endpoints and may be delayed or incomplete; AI-generated content is for reference only and **does not constitute investment advice**. Markets involve risk — invest carefully.

---

## 🗺 Roadmap

- [x] V1 Basic market analytics site
- [x] V2 Multi-stock comparison + company profiles + CSV export
- [x] V3 AI Agent (tool layer / multi-topic chat / charting / deep fundamentals / news sentiment / valuation / risk review)
- [ ] V4: More data sources (backup APIs), multi-stock comparison Q&A, PDF report export

---

## 📄 License

[MIT](LICENSE) © 2026 Evidence-Based Financial Research Agent contributors
