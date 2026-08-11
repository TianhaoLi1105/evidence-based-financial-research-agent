# 📊 Evidence-Based Financial Research Agent

**[English](README.en.md) | 中文**

**一个基于真实数据的金融研究助手** —— 输入股票代码，获取行情、财务、新闻与 AI 深度研报。

基于 [Streamlit](https://streamlit.io) 构建，全部数据来自**免费数据源**（多源自动降级），内置可对话的 **AI Agent**（支持 DeepSeek / 通义千问 / 智谱 GLM / OpenAI / Ollama），生成带数据来源标注与风险复核的专业研报。

> ⚠️ 本项目仅供学习与研究，不构成任何投资建议。

---

## ✨ 功能亮点

### 📈 行情分析（V1–V2）
- 任意美股 K 线图（日 / 周 / 月），支持时间范围切换
- 技术指标：MA20 / MA60 / EMA12/26 / MACD / BOLL / RSI14
- 公司概况：简介、行业、板块、CEO、员工数、官网（免费源兜底）
- 财务数据：营收、净利、毛利率、负债率、现金流、EPS、ROE 等（四源降级）
- 多股对比：归一化走势图 + 估值/财务指标对比表 + 自选股
- 市场概览（三大指数）与 K 线 CSV 下载

### 🤖 AI 智能 Agent（V3）
- 右下角悬浮对话窗，流式输出，支持多话题会话（本地持久化）
- **9 个数据工具**：实时报价、历史 K 线、财务深度、公司概况、技术指标、多股对比、估值判断、新闻情绪、对话内出图
- **深度分析研报**：自动调用完整工具链，输出 6 章节结构化报告（公司概况 / 财务与估值 / 技术面 / 主要风险 / **数据自检** / 结论），可下载 HTML / Markdown
- **数据来源逐条标注**：每个关键数字标注来源，拒绝编造
- **分析师 → 风控二次审阅**（可选开关）：独立风控角色复核数据支撑、指出缺口与遗漏风险
- **估值贵贱判断**：问「AAPL 现在贵不贵」→ 对比行业同行中位数 + 52 周价格位置
- **新闻与情绪**：抓取公司新闻并对标题做情绪打分
- 对话内直接出图（K 线 / 折线 / 多股对比）
- 个性化记忆：记住常看股票与关注话题，注入对话上下文

### 🌍 体验
- 中英双语一键切换（语言记忆）
- Apple 风格深色 UI，无第三方追踪
- 多模型自由切换：DeepSeek / Qwen / GLM / OpenAI / Ollama / 自定义端点

---

## 📸 功能截图

截图位于 `docs/screenshots/`（首次运行可执行下方脚本一键生成）：

```bash
python scripts/capture_screenshots.py   # 需要先安装 playwright
```

| 单股分析 | AI 对话与深度研报 |
| --- | --- |
| ![单股分析](docs/screenshots/single.png) | ![AI 对话](docs/screenshots/chat.png) |

| 多股对比 | 深度研报（下载） |
| --- | --- |
| ![多股对比](docs/screenshots/compare.png) | ![深度研报](docs/screenshots/report.png) |

---

## 🚀 快速开始

### 1. 环境要求
- Python **3.9+**
- 一个 LLM API Key（可选，不配置也能用行情分析；配置后解锁 AI Agent）

### 2. 安装依赖

```bash
git clone https://github.com/TianhaoLi1105/evidence-based-financial-research-agent.git
cd evidence-based-financial-research-agent
pip install -r requirements.txt
```

### 3. 运行

```bash
streamlit run app.py
```

浏览器打开 `http://localhost:8501`。

### 4. 配置
- **数据 API（可选）**：点击右上角 `KEY` → 填写 [Twelve Data](https://twelvedata.com) 免费 Key。不填时自动使用免费备用源（腾讯财经 / stockanalysis.com / 东财），数据略少但功能可用。
- **AI 模型（可选）**：点击右上角 `KEY` → `AI 模型` 标签页 → 选择服务商并填入 API Key。支持：

| 服务商 | Base URL | 默认模型 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问 (Qwen) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama（本地） | `http://localhost:11434/v1` | `qwen2.5` |
| 自定义 | 任意 OpenAI 兼容端点 | — |

---

## 🏗 架构

```
app.py                    # Streamlit 入口：单股分析 / 多股对比 / 市场概览
├── agent/                # AI Agent 层
│   ├── tools.py          #   9 个数据工具（Function Calling）
│   ├── executor.py       #   工具调用循环 + 风控复核
│   ├── prompts.py        #   系统提示词（13 条规则 + 风控角色）
│   └── llm_client.py     #   多提供商 OpenAI 兼容客户端
├── data/                 # 数据层（全部免费源 + 24h 缓存）
│   ├── fundamentals.py   #   四源降级财务深度
│   ├── news.py           #   东财 → Google News
│   ├── valuation.py      #   估值相对位置（同行对比）
│   ├── chat_store.py     #   多话题会话持久化
│   └── preferences.py    #   个性化记忆
├── services/             # 行情/报价降级链路
├── components/           # 页面组件（K线/对比/卡片/AI 聊天窗）
└── i18n.py               # 中英双语（215 键）
```

**数据源降级链（免费优先）**

| 能力 | 降级链 |
| --- | --- |
| 实时报价 | Twelve Data → 腾讯财经 |
| 财务深度 | Twelve Data → stockanalysis.com → yfinance → 新浪 |
| 公司概况 | Twelve Data → stockanalysis.com |
| 新闻 | 东方财富 → Google News |
| 估值对比 | 腾讯/stockanalysis + 本地计算（同行映射 + 52 周分位） |

所有结果带 `source` 字段标注来源；失败静默降级，字段缺失显示 N/A，**绝不编造**。

---

## ✅ 测试

项目维护 16 组回归测试（覆盖工具层、降级链路、AI 事件流、渲染、记忆等，全部 **mock 数据源、无需网络**）：

```bash
bash tests/run_all.sh        # 一键运行全部 16 组
python tests/test_v343.py    # 运行单组（如估值）
```

| 测试文件 | 覆盖范围 |
| --- | --- |
| `tests/test_v31_*.py` | LLM 客户端、消息组装、i18n、应用流程 |
| `tests/test_v32_*.py` | 工具层、深度分析、图表、出图兜底 |
| `tests/test_v33_*.py` | 上下文增强、出图持久化、个性化记忆 |
| `tests/test_v341.py` ~ `test_v345.py` | 财务深度、新闻情绪、估值、报告/风控、收尾增强 |
| `tests/test_lang_mem.py` / `test_chat_store.py` | 语言记忆、多话题存储 |


---

## 🔒 隐私与安全

- **API Key 仅存本地**：`.agent_config.json`（已被 `.gitignore` 排除，不会提交到仓库）
- **聊天历史与个性化档案仅存本地**：`chat_history.json`、`.cache/`（均已排除）
- **无第三方追踪**：应用不收集、不上传任何用户数据
- **数据源均为公开免费接口**：不涉及用户隐私信息
- **密钥永不出现在日志或代码中**

---

## 📄 免责声明

本项目仅供**学习与研究**目的。所有数据来自公开免费接口，可能延迟或不完整；AI 生成内容仅供参考，**不构成任何投资建议**。股市有风险，投资需谨慎。

---

## 🗺 Roadmap

- [x] V1 基础行情网站
- [x] V2 多股对比 + 公司概况 + CSV 导出
- [x] V3 AI Agent（工具层 / 多话题 / 出图 / 财务深度 / 新闻情绪 / 估值 / 风险复核）
- [ ] V4：更多数据源（备用 API）、多股票对比问答、PDF 研报导出

---

## 📄 License

[MIT](LICENSE) © 2026 Evidence-Based Financial Research Agent contributors
