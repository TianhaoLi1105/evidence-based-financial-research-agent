# 📊 Evidence-Based Financial Research Agent

**English** | [中文](README.zh-CN.md)

[![Regression Tests](https://github.com/TianhaoLi1105/evidence-based-financial-research-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/TianhaoLi1105/evidence-based-financial-research-agent/actions/workflows/tests.yml)

A Python financial research application that combines market-data APIs with an LLM tool-calling agent.

I built it to explore how an LLM can answer financial questions using retrieved data instead of relying only on model knowledge. The application uses free data sources and falls back to alternate providers when one is unavailable.

> ⚠️ This project is for learning and research only. Nothing here constitutes investment advice.

---

## Highlights

### Market Analytics
- Candlestick charts for any US stock (daily / weekly / monthly) with time-range switching
- Technical indicators: MA20 / MA60 / EMA12/26 / MACD / BOLL / RSI14
- Company profiles: description, industry, sector, CEO, employee count, website (free-source fallback)
- Fundamentals: revenue, net income, gross margin, debt ratio, cash flow, EPS, ROE, etc. (four-source fallback)
- Multi-stock comparison: normalized trend chart + valuation/fundamental comparison table + watchlist
- Market overview (three major indices) and K-line CSV export

### AI Agent
- Floating chat window with streaming output and multi-topic conversations
- **9 data tools**: real-time quotes, historical K-lines, deep fundamentals, company profile, technical indicators, multi-stock comparison, valuation assessment, news sentiment, in-chat charting
- **Research report**: runs the relevant tools and outputs a structured report, downloadable as HTML or Markdown
- **Source attribution**: key numbers carry their data source; missing values are shown as N/A
- **Analyst → Risk review** (optional): an independent risk-review role re-checks data support and flags gaps or missed risks
- **Valuation check**: ask "Is AAPL expensive right now?" → compares against industry peers and the 52-week price position
- **News & sentiment**: fetches company news and scores headline sentiment
- In-chat chart generation (K-line / line / multi-stock comparison)
- Personalized memory: remembers frequently viewed tickers and topics, injected into conversation context

### Experience
- One-click Chinese / English switching (language preference remembered)
- Dark UI with Chinese and English support
- Switch between multiple models: DeepSeek / Qwen / GLM / OpenAI / Ollama / custom endpoint

---

## Screenshots

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

## Quick Start

### 1. Requirements
- Python **3.10+**
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

By default, API keys, model profiles, and chat history are kept only in server memory for the current browser session. Refreshing or restarting requires setup again. This prevents visitors from sharing credentials and conversations. For trusted single-user local use, restore disk persistence with `AGENT_LOCAL_PERSISTENCE=1 streamlit run app.py`. Do not use that mode for multi-user access.

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

### 5. Docker

With Docker Desktop installed, build and start the application with one command:

```bash
docker compose up --build
```

Open `http://localhost:8501`; stop it with `docker compose down`.

---

## Architecture

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

Results carry a `source` field where available, and missing fields are shown as N/A.

---

## Testing

The project maintains 18 regression test groups (tool layer, fallback chains, AI event stream, rendering, memory, and evaluation — all with **mocked data sources, no network needed**):

```bash
bash tests/run_all.sh        # run all 18 groups at once
python tests/test_valuation.py  # run one group
```

| Test files | Coverage |
| --- | --- |
| `tests/test_agent_*.py` / `test_app_integration.py` | LLM client, message assembly, tools, i18n, app flow |
| `tests/test_chart_*.py` / `test_chat_charts.py` | chart generation, rendering, persistence, and fallback |
| `tests/test_fundamentals.py` / `test_news.py` / `test_valuation.py` | data parsing, provider fallback, sentiment, and valuation |
| `tests/test_deep_analysis.py` / `test_risk_review.py` | research flow, report export, and risk review |
| `tests/test_comparison_context.py` / `test_preferences.py` | comparison context and personalized memory |
| `tests/test_lang_mem.py` / `test_chat_store.py` | language memory, multi-topic storage |
| `tests/test_security_provenance.py` / `test_evaluation.py` | session isolation, provenance, evaluation data and metrics |

### Real agent evaluation

`evals/tool_routing_cases.jsonl` contains 54 Chinese and English questions: six for each of nine tools, with `expected_tools` annotated on every case. Run it against the locally configured model and real data tools:

**Evaluation protocol:** DeepSeek Chat answers 54 bilingual queries covering nine tools. Tool routing accuracy uses strict exact match: the actual tool set must equal `expected_tools`, and every additional tool call counts as a routing failure.

```bash
AGENT_LOCAL_PERSISTENCE=1 python3 scripts/evaluate_agent.py
```

See [`docs/EVALUATION.md`](docs/EVALUATION.md) for the latest real run. Full per-case results are stored in `evals/results/latest.json`.

GitHub Actions runs all 18 offline regression groups and builds the Docker image on every push and pull request. The real evaluation is excluded from CI because it calls live LLM/API services, costs money, and may have stochastic results.

---

## Privacy & Security

- **Session isolation by default**: API keys, model profiles, and chat history live only in the current Streamlit session's server memory, isolated from other visitors
- **Optional single-user persistence**: `AGENT_LOCAL_PERSISTENCE=1` uses `.agent_config.json` and `chat_history.json` (both gitignored)
- **No third-party tracking**: the app collects and uploads nothing
- **Public free endpoints only**: no user privacy data involved
- **Keys never appear in logs or code**

---

## Disclaimer

For **learning and research** purposes only. All data comes from public free endpoints and may be delayed or incomplete; AI-generated content is for reference only and **does not constitute investment advice**. Markets involve risk — invest carefully.

---

## Roadmap

- [x] Basic market analytics
- [x] Multi-stock comparison, company profiles, and CSV export
- [x] Tool-calling agent, multi-topic chat, charting, fundamentals, news, valuation, and risk review
- [ ] More backup data sources, multi-stock comparison Q&A, and PDF report export

---

## License

[MIT](LICENSE) © 2026 Evidence-Based Financial Research Agent contributors
