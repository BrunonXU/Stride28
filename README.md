<p align="center">
  <img src="docs/assets/logo.svg" alt="Stride28" height="64" />
</p>

<p align="center">
  <strong>A stateful multi-source research and planning agent.</strong><br/>
  一个有状态的多源调研与规划 Agent。
</p>

<p align="center">
  28 = 四周。用一个月的时间，围绕一个目标完成从调研到执行的完整闭环。<br/>
  通过<strong>搜索、筛选、上下文沉淀与规划生成</strong>，将分散信息转化为可执行流程。<br/>
  当前版本优先面向<strong>学习与面试准备场景</strong>进行设计与优化。
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
  <a href="#快速开始">快速开始</a> •
  <a href="#核心能力">核心能力</a> •
  <a href="#系统架构">系统架构</a> •
  <a href="#开发路线">开发路线</a> •
  <a href="#参与贡献">参与贡献</a>
</p>

<p align="center">
  <img src="docs/assets/全局.png" alt="Stride28 三栏布局全局界面" width="800" />
</p>

---

## 它解决什么问题

真实任务很少是一次性完成的。你通常需要：找资料 → 比较筛选 → 沉淀关键信息 → 形成计划 → 执行中持续调整。

大多数 AI 工具只做其中一步。Stride28 把这条链路串成一个有状态的 Agent workflow：

```
目标设定 → 多源搜索 → 筛选评估 → 材料沉淀 → 规划生成 → 对话辅导 → 进度追踪 → 迭代调整
```

Agent 的上下文 = 你的材料 + 对话历史 + 用户画像 + 完成进度。所有输出都基于这个持续累积的上下文，而不是通用模板。

---

## 核心能力

### 多源调研（Multi-source Research）

围绕同一个目标，从多个平台聚合候选信息。当前已接入：

- 小红书（签名 + httpx 直连）
- 知乎（API 直连）
- GitHub（Playwright 浏览器代理）

更多来源（B站、YouTube、Google 等）正在接入中。搜索结果经过两阶段漏斗：

1. **互动数据初筛**（EngagementRanker）：按点赞、收藏、评论比例打分，广告内容自动降权
2. **LLM 质量评估**（QualityAssessor）：批量评估，生成评分、推荐理由、内容摘要、评论区结论

进入后续链路的不是"所有搜索结果"，而是经过筛选的高质量内容。

<p align="center">
  <img src="docs/assets/search-demo-compressed.gif" alt="多源搜索聚合演示" width="800" />
</p>

### 上下文沉淀（Context Building）

搜索结果可一键添加为材料，PDF / Markdown 可直接上传。所有材料进入统一的上下文池，后续的规划、对话、内容生成都建立在这个持续累积的上下文之上。

对话也分两种模式：
- **聊天区**：把材料拖进输入框，基于指定文档问答（显式附加）
- **Studio**：自动检索所有已有材料（RAG），生成内容基于完整知识库

<p align="center">
  <img src="docs/assets/chat-demo.gif" alt="材料感知对话" width="800" />
</p>

### 规划生成（Planning & Structured Output）

基于上下文生成结构化输出，当前版本支持 7 种工具：

| 工具 | 做什么 |
|------|--------|
| 学习指南 | 知识体系路线图，标注重点和前置依赖 |
| 学习计划 | 逐日任务分解，渲染为可交互时间线 |
| 闪卡 | 问答卡片，自动加权困惑点 |
| 测验 | 多题型（单选/多选/判断），针对薄弱点出题 |
| 思维导图 | 知识结构可视化（markmap.js） |
| 进度报告 | 完成率、知识覆盖度、薄弱环节分析 |
| 日总结 | 当天回顾 + 跨天知识关联 |

计划不是生成一次就不变——当你添加了新材料、讨论了新概念、或完成/跳过了任务，下次生成会综合这些信号调整。

<p align="center">
  <img src="docs/assets/timeline.png" alt="结构化学习计划时间线" width="800" />
</p>

### 跨会话记忆（Cross-session Memory）

双层记忆机制保持上下文连续性：

- **Working Memory**：最近 12 条消息保留原文，保证当前对话连贯
- **Episodic Memory**：超出窗口的历史压缩为结构化摘要（困惑点、已掌握概念、偏好），注入后续对话

清空对话 ≠ 遗忘。上周聊过的问题，这周继续问时 Agent 还记得。

### 生成后校验（Post-generation Validation）

对学习计划、闪卡、测验等结构化内容，系统会做格式校验、字段修正和结果清洗，确保输出不仅"看起来对"，而且可消费、可执行。

<p align="center">
  <img src="docs/assets/学习指南页面.png" alt="学习指南" width="800" />
</p>

<p align="center">
  <img src="docs/assets/思维导图.png" alt="思维导图" width="800" />
</p>

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│  前端：React 18 + TypeScript + Zustand + TailwindCSS         │
│  三栏布局：资源面板 | 聊天区 | Studio 面板                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API + SSE
┌──────────────────────────┴──────────────────────────────────┐
│  后端：FastAPI                                               │
│  路由：plans / chat / studio / search / resource / upload /    │
│        notes / dev / provider                                 │
├──────────────────────────────────────────────────────────────┤
│  核心逻辑（src/）                                             │
│  ├── agents/       TutorAgent + Episodic Memory               │
│  ├── providers/    LLM 抽象层（4 家服务商热切换）              │
│  ├── specialists/  搜索模块（6 平台 + 两阶段漏斗）             │
│  └── rag/          ChromaDB 向量检索                           │
├──────────────────────────────────────────────────────────────┤
│  持久化：SQLite（WAL 模式）+ ChromaDB                         │
├──────────────────────────────────────────────────────────────┤
│  可观测：LangSmith 全链路追踪                                  │
└──────────────────────────────────────────────────────────────┘
```

### 技术选型

| 层 | 技术 | 为什么选它 |
|----|------|-----------|
| 前端 | React 18 + Zustand | 轻量状态管理，6 个 Store 职责清晰 |
| 样式 | TailwindCSS | 原子化 CSS，组件级样式隔离 |
| 后端 | FastAPI | 异步原生，SSE 流式响应开箱即用 |
| 搜索 | Playwright + httpx | 浏览器渲染 + API 直连混合策略 |
| 向量存储 | ChromaDB | 嵌入式，零运维，适合单用户场景 |
| 数据库 | SQLite (WAL) | 9 张表 + 级联删除，单文件部署 |
| LLM | OpenAI 兼容协议 | 一套接口接 DeepSeek / OpenAI / 智谱 / 通义千问 |
| 可观测 | LangSmith | Prompt 调试 + 链路追踪，开发期必备 |

### 支持的 LLM Provider

通过 OpenAI 兼容协议，一套接口覆盖多家服务商。Embedding 固定使用 DashScope text-embedding-v2（必须配置 DashScope API Key）。

| Provider | 默认模型 | 说明 |
|----------|---------|------|
| 通义千问 (tongyi) | qwen-turbo | 需要 DASHSCOPE_API_KEY |
| DeepSeek（推荐） | deepseek-chat (V3) | 性价比高，中文效果好 |
| OpenAI | gpt-4o-mini | 英文场景或需要 GPT 系列时 |
| 智谱 (zhipu) | glm-4.7-flash | 国内免翻，速度快 |

LLM Provider 可在前端设置页热切换，不需要重启。

---

## 配置说明

复制 `.env.example` 为 `.env`，至少需要配置：

```env
# LLM（推荐 DeepSeek，性价比最高）
DEEPSEEK_API_KEY=sk-your-deepseek-api-key

# Embedding（必须，DashScope text-embedding-v2）
DASHSCOPE_API_KEY=sk-your-dashscope-api-key

# 默认 Provider（可选值：deepseek / openai / zhipu / tongyi）
DEFAULT_PROVIDER=deepseek
DEFAULT_MODEL=deepseek-chat
```

Embedding 模型固定为 `text-embedding-v2`，不可切换（切换会导致 ChromaDB 向量不兼容）。LLM Provider 可在前端设置页随时切换。

---

## 快速开始

### 环境要求

- Python 3.10+、Node.js 18+
- LLM API Key（推荐 [DeepSeek](https://platform.deepseek.com/)）
- [DashScope](https://dashscope.console.aliyun.com/) API Key（Embedding 用，必须）

### 方式一：Docker（推荐）

```bash
git clone https://github.com/BrunonXU/Stride28.git
cd Stride28
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 和 DASHSCOPE_API_KEY

docker compose up -d
```

打开 `http://localhost`。

```bash
# 查看日志
docker compose logs -f

# 停止服务（数据不会丢失，持久化在 Docker named volume 中）
docker compose down
```

> **注意**：Docker 部署下，基于浏览器代理的搜索（小红书、知乎等需要 cookie 的平台）可能受限。API 直连的平台（B站等）和 Playwright headless 搜索（YouTube、GitHub、Google）正常工作。如需完整搜索功能，建议使用本地开发方式部署。

### 方式二：本地开发

```bash
git clone https://github.com/BrunonXU/Stride28.git
cd Stride28

# 后端
python -m venv venv && source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# 前端
cd frontend && npm install && cd ..

# 配置
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 和 DASHSCOPE_API_KEY

# 启动
uvicorn backend.main:app --port 8000  # 终端 1
cd frontend && npm run dev                       # 终端 2
```

打开 `http://localhost:3000`。

首次启动会自动注入一个示例学习规划（"Agent 开发"），包含完整的搜索历史、材料、对话记录和 Studio 生成内容，方便你直接体验所有功能。

---

## 开发路线

- [x] 6 平台搜索聚合 + 两阶段质量漏斗
- [x] NotebookLM 风格三栏布局
- [x] 材料感知对话（显式附加 + RAG 双模式）
- [x] SQLite 持久化（9 张表 + 级联删除 + WAL）
- [x] Episodic Memory 跨会话记忆
- [x] 7 种 Studio 工具 + PromptBuilder 动态指令
- [x] 多 Provider 热切换
- [x] LangSmith 全链路追踪
- [x] Docker 一键部署
- [x] LangGraph 聊天编排器
- [ ] RAG 评测流水线
- [ ] 多模态材料理解（图片/音频）

---

## 参与贡献

欢迎 PR。如果你对以下方向感兴趣，非常欢迎交流：

- Agent workflow 设计与编排
- 多源搜索与排序策略
- RAG 与上下文工程
- 结构化内容生成与校验

### 项目结构

```
Stride28/
├── backend/            # FastAPI 后端（路由 + 数据库 + Prompt 构建）
├── frontend/           # React 前端（6 个 Zustand Store + 三栏布局）
├── src/                # 核心逻辑（Agent + Provider + 搜索 + RAG）
├── .env.example        # 环境变量模板
├── docker-compose.yml  # Docker 编排
└── requirements.txt    # Python 依赖
```

---

## License

[MIT](LICENSE)

---

<p align="center">
  把分散的信息变成可执行的流程。<br/>
  如果 Stride28 对你有帮助，考虑给个 ⭐
</p>
