<p align="center">
  <img src="docs/assets/logo.svg" alt="Stride28" height="64" />
</p>

<p align="center">
  AI 驱动的调研与规划助手。把分散的信息变成可执行的计划。
</p>

<p align="center">
  <a href="https://github.com/BrunonXU/Stride28"><img src="https://img.shields.io/github/stars/BrunonXU/Stride28?style=social" alt="GitHub Stars" /></a>
  <a href="https://github.com/BrunonXU/Stride28/blob/main/LICENSE"><img src="https://img.shields.io/github/license/BrunonXU/Stride28" alt="License" /></a>
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python" />
  <img src="https://img.shields.io/badge/react-18-61dafb.svg" alt="React" />
  <a href="#参与贡献"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
</p>

<p align="center">
  <strong>中文</strong> | <a href="README_EN.md">English</a>
</p>

<p align="center">
  <a href="#它解决什么问题">为什么</a> •
  <a href="#核心能力">核心能力</a> •
  <a href="#快速开始">快速开始</a> •
  <a href="#架构">架构</a> •
  <a href="#路线图">路线图</a> •
  <a href="#参与贡献">参与贡献</a>
</p>

<p align="center">
  <img src="docs/assets/全局.png" alt="Stride28 界面" width="800" />
</p>

---

## 它解决什么问题

学一个新东西，你通常要：找资料 → 筛选 → 整理 → 制定计划 → 执行 → 复盘。大多数 AI 工具只帮你做其中一步。

Stride28 把整条链路串起来，变成一个持续累积上下文的 workflow：

```
多源搜索 → 质量筛选 → 材料沉淀 → 规划生成 → 对话辅导 → 进度追踪 → 迭代调整
```

你的材料、对话历史、学习画像、完成进度——全部是 Agent 的上下文。所有输出都基于这个不断增长的上下文生成，而不是每次从零开始。

---

## 核心能力

### 🔍 多源搜索聚合

从 6 个平台并发搜索，经过两阶段质量漏斗（互动数据初筛 → LLM 质量评估），只有高质量内容进入后续链路。不是简单的 API 聚合——每个平台有独立的反爬策略、数据提取逻辑和质量评分权重。

支持平台：小红书 · 知乎 · B站 · YouTube · GitHub · Google

<p align="center">
  <img src="docs/assets/search-demo-compressed.gif" alt="多源搜索" width="800" />
</p>

### 📚 上下文沉淀

搜索结果一键添加为材料，PDF / Markdown 直接上传。所有材料进入统一上下文池，后续的规划、对话、内容生成都建立在这个持续累积的上下文之上。

### 💬 材料感知对话

两种模式：聊天区把材料拖进输入框做精准问答；Studio 用两阶段检索（embedding 召回 → Cross-Encoder reranker 精排）+ 分层注入生成内容。聊天区不做全局 RAG，只用你显式拖入的材料——避免无关内容污染回答。

<p align="center">
  <img src="docs/assets/chat-demo.gif" alt="材料感知对话" width="800" />
</p>

### 🎯 7 种结构化工具

学习指南 · 学习计划 · 闪卡 · 测验 · 思维导图 · 进度报告 · 日总结

所有工具都是上下文感知的——基于你的材料、对话历史、用户画像和完成进度动态生成，不是通用模板。Prompt 在 Python 侧按条件分支组装，LLM 收到的是明确无歧义的指令。

<p align="center">
  <img src="docs/assets/timeline.png" alt="学习计划时间线" width="800" />
</p>

### 🧠 跨会话记忆

双层记忆：Working Memory 保留最近对话原文，Episodic Memory 把历史压缩为结构化摘要。清空对话 ≠ 遗忘——你之前的困惑点、学习偏好会持续影响后续生成。

<p align="center">
  <img src="docs/assets/学习指南页面.png" alt="学习指南" width="400" />
  <img src="docs/assets/思维导图.png" alt="思维导图" width="400" />
</p>

---

## 快速开始

### 环境要求

- Python 3.10+、Node.js 18+
- LLM API Key（推荐 [DeepSeek](https://platform.deepseek.com/)，性价比最高）
- [DashScope](https://dashscope.console.aliyun.com/) API Key（Embedding 必须）

### Docker（推荐）

```bash
git clone https://github.com/BrunonXU/Stride28.git && cd Stride28
cp .env.example .env
# 编辑 .env，填入 API Key

docker compose up -d
# 前端: http://localhost  后端: http://localhost:8000
```

### 本地开发

```bash
git clone https://github.com/BrunonXU/Stride28.git && cd Stride28

# 后端
python -m venv venv && source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# 前端
cd frontend && npm install && cd ..

# 配置
cp .env.example .env  # 编辑填入 API Key

# 启动（两个终端）
uvicorn backend.main:app --port 8000
cd frontend && npm run dev
# 打开 http://localhost:3000
```

### 配置说明

| 变量 | 必须 | 说明 |
|------|:----:|------|
| `DEEPSEEK_API_KEY` | ✅ | LLM（至少配一个 provider） |
| `DASHSCOPE_API_KEY` | ✅ | Embedding（text-embedding-v2，不可切换） |
| `RERANKER_ENABLED` | — | 启用 Cross-Encoder reranker，首次启动下载 ~2.3GB 模型 |
| `GITHUB_TOKEN` | — | 提升 GitHub 搜索速率（无 token 10次/分钟） |
| `LANGSMITH_API_KEY` | — | LangSmith 全链路追踪 |
| `DEFAULT_PROVIDER` | — | 默认 `deepseek`，可选 `openai` / `zhipu` / `tongyi` |

完整配置见 [`.env.example`](.env.example)。

> 首次启动会注入示例学习规划（含搜索历史、材料、Studio 内容），可以直接体验完整流程。

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│  React + TypeScript + Zustand + TailwindCSS             │
│  三栏布局：材料 │ 对话 │ Studio                          │
└────────────────────────┬────────────────────────────────┘
                         │ REST API + SSE
┌────────────────────────┴────────────────────────────────┐
│  FastAPI                                                 │
│  plans / chat / studio / search / resource / upload /    │
│  notes / dev / provider                                  │
├──────────────────────────────────────────────────────────┤
│  agents/       TutorAgent + Episodic Memory              │
│  providers/    OpenAI-compatible 抽象（4 家 LLM）         │
│  specialists/  搜索模块（6 平台 + 两阶段漏斗）            │
│  rag/          ChromaDB + Cross-Encoder Reranker         │
├──────────────────────────────────────────────────────────┤
│  SQLite (WAL) + ChromaDB (text-embedding-v2)             │
│  LangSmith 全链路追踪                                     │
└──────────────────────────────────────────────────────────┘
```

---

## 路线图

**已完成：** NotebookLM 风格三栏 UI · 6 平台搜索聚合 · 两阶段质量漏斗 · 材料感知对话 · SQLite 持久化 · Episodic Memory · 动态 Prompt 组装 · 多 Provider 支持 · LangSmith 追踪 · RAG 分层注入 · Cross-Encoder Reranker · 覆盖优先 context budget · LangGraph Chat Orchestrator

**进行中 / 计划：**
- [ ] 7 种 Studio 工具的动态 prompt 优化
- [ ] 进度环 UI 组件
- [ ] RAG 评估 pipeline（hit@k）
- [ ] 多模态材料理解（PDF 图片 + VL 模型）
- [ ] Demo 视频 & 引导流程

---

## 参与贡献

欢迎 PR、Issue、Feature Request。

开发注意事项：
- 后端改动（Python / `.env`）需要重启服务，前端改动通过 Vite HMR 热更新
- 数据库字段 `snake_case`，API 返回 `camelCase`（自动转换）
- Embedding 模型固定为 `text-embedding-v2`，切换会导致向量不兼容

---

## License

[MIT](LICENSE)

---

<p align="center">
  如果 Stride28 对你有帮助，欢迎给个 ⭐
</p>
