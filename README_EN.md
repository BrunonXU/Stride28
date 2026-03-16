<p align="center">
  <!-- TODO: 替换为项目 Logo -->
  <img src="docs/assets/logo.png" alt="Stride28 Logo" width="120" />
</p>

<h1 align="center">Stride28</h1>

<p align="center">
  <strong>Master anything in 28 days.</strong><br/>
  An AI-powered learning assistant that turns any topic into a structured daily plan — with smart resource discovery, adaptive tutoring, and daily check-ins to keep you on track.
</p>

<p align="center">
  <!-- TODO: 替换为实际 GitHub 地址 -->
  <a href="#"><img src="https://img.shields.io/github/stars/BrunonXU/Stride28?style=social" alt="GitHub Stars" /></a>
  <a href="#"><img src="https://img.shields.io/github/license/BrunonXU/Stride28" alt="License" /></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/react-18-61dafb.svg" alt="React" /></a>
  <a href="#"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
</p>

<p align="center">
  <a href="README.md">中文</a> | <strong>English</strong>
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-user-journey">User Journey</a> •
  <a href="#-features">Features</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-roadmap">Roadmap</a> •
  <a href="#-contributing">Contributing</a>
</p>

---

<!-- TODO: 替换为产品全貌截图或 GIF -->
<p align="center">
  <img src="docs/assets/hero-screenshot.png" alt="Stride28 三栏布局全貌" width="900" />
</p>

## 💡 Why Stride28?

Most AI learning tools stop at "chat with your docs." Stride28 goes further — it gives your learning a **deadline, a structure, and a daily rhythm**.

| Pain Point | How Stride28 Solves It |
|---|---|
| 🗓️ "I'll learn it someday" syndrome | **3–28 day bounded plans** — pick a deadline, AI generates a daily roadmap |
| 📚 Scattered resources everywhere | **6-platform search aggregation** — Xiaohongshu, Bilibili, YouTube, GitHub, Google, Zhihu, filtered by a two-stage quality funnel |
| 🤖 Generic AI responses | **Material-aware chat** — drag your PDFs into the conversation, AI answers grounded in YOUR materials |
| 🧠 AI forgets what you discussed | **Episodic Memory** — AI remembers your confusion points across sessions, even after clearing chat |
| 📊 No sense of progress | **Daily check-ins + AI summaries** — complete today's tasks, get encouragement and cross-day knowledge connections |


## 🎬 User Journey

> Meet **小明**, a junior developer preparing for frontend interviews. He gives himself **14 days** to master React.

### Day 0 — Setup (2 minutes)

小明 creates a new learning plan, sets his profile: "14-day cycle, 2 hours/day, intermediate level, goal: job interview prep." He uploads the React official docs PDF and searches for top-rated React tutorials across Bilibili and YouTube.

<!-- TODO: 替换为创建计划 + 设置画像的截图 -->
<p align="center">
  <img src="docs/assets/journey-01-setup.png" alt="创建学习计划" width="700" />
</p>

### Day 1 — First Learning Session

AI generates a 14-day learning plan tailored to his profile. Day 1: JSX fundamentals. 小明 reads the materials, chats with AI when confused about JSX expressions vs statements. After completing the day's tasks, he clicks "Day Summary" — AI generates a personalized recap with encouragement:

> *"Day 1 done — you've nailed JSX syntax. Tomorrow's Component composition will build directly on what you learned today."*

<!-- TODO: 替换为 Day 1 学习界面截图（三栏布局：材料 | 聊天 | Studio） -->
<p align="center">
  <img src="docs/assets/journey-02-day1.png" alt="Day 1 学习界面" width="700" />
</p>

### Day 7 — Mid-cycle Review

Halfway through. 小明 generates a progress report — AI analyzes his completion rate, identifies weak spots (he struggled with `useEffect` cleanup on Day 5), and suggests focused review. He generates flashcards — AI automatically weights more cards toward his confusion points from chat history.

<!-- TODO: 替换为进度报告 + 闪卡截图 -->
<p align="center">
  <img src="docs/assets/journey-03-midreview.png" alt="中期回顾" width="700" />
</p>

### Day 14 — Completion

小明 finishes all 14 days. He generates a mind map to visualize the full knowledge structure, takes a comprehensive quiz where AI targets his historically weak areas, and exports his study guide as interview prep material.

<!-- TODO: 替换为完成状态截图（思维导图 + 测验） -->
<p align="center">
  <img src="docs/assets/journey-04-complete.png" alt="学习完成" width="700" />
</p>

---

## ✨ Features

### 📋 Structured Learning Plans
AI generates day-by-day learning plans (3–28 days) based on your profile, materials, and available time. Short cycles (3–7 days) focus on core concepts; longer cycles (15–28 days) include review days and practice sessions.

### 🔍 Multi-Source Search Aggregation
Search across 6 platforms simultaneously with a **two-stage quality funnel**:
1. **Engagement ranking** — filter by likes, comments, and relevance
2. **LLM quality assessment** — AI scores and summarizes each result

Supported platforms: Xiaohongshu · Bilibili · YouTube · GitHub · Google · Zhihu

<!-- TODO: 替换为搜索界面截图 -->
<p align="center">
  <img src="docs/assets/feature-search.png" alt="多源搜索" width="700" />
</p>

### 💬 Material-Aware Chat
Drag materials into the chat input — AI answers grounded in YOUR documents, not generic knowledge. Studio tools use global RAG for comprehensive content generation.

### 🧠 Episodic Memory
AI compresses long conversations into episodic summaries. Clear your chat, start fresh — but AI still remembers what confused you last time. This powers smarter flashcards, quizzes, and study guides.

### 🎯 7 Studio Tools

| Tool | What It Does |
|------|-------------|
| 📖 Study Guide | Strategic learning roadmap with knowledge structure |
| 📅 Learning Plan | Day-by-day task breakdown (strict JSON, rendered as timeline) |
| 🃏 Flashcards | Q&A cards weighted toward your confusion points |
| 📝 Quiz | Multi-format tests targeting your weak areas |
| 🗺️ Mind Map | Knowledge structure visualization (markmap.js) |
| 📊 Progress Report | Data-driven analysis of your learning journey |
| 📓 Day Summary | Daily recap with AI encouragement and cross-day knowledge connections |

All tools are **context-aware** — they adapt based on your chat history, episodic memory, learner profile, and current progress.

### 🔌 Multi-Provider Support
Swap LLM providers without changing code. One `OpenAICompatibleProvider` class covers all:

| Provider | Default Model |
|----------|--------------|
| DeepSeek | deepseek-chat (V3, 64K context) |
| OpenAI | gpt-4o-mini |
| Zhipu (GLM) | glm-4-flash |
| Moonshot | moonshot-v1-8k |


---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend: React + TypeScript + Zustand + TailwindCSS       │
│  Three-panel layout: Resources | Chat | Studio              │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API + SSE (streaming)
┌──────────────────────────┴──────────────────────────────────┐
│  Backend API: FastAPI                                        │
│  Routes: plans / chat / studio / search / resource / upload  │
├──────────────────────────────────────────────────────────────┤
│  Core Logic (src/)                                           │
│  ├── agents/       TutorAgent + Episodic Memory              │
│  ├── providers/    OpenAI-compatible abstraction (4 vendors)  │
│  ├── specialists/  Search module (6 platforms + 2-stage funnel)│
│  └── rag/          ChromaDB vector store                      │
├──────────────────────────────────────────────────────────────┤
│  Persistence                                                  │
│  ├── SQLite (WAL mode) — 8 tables, cascade delete             │
│  └── ChromaDB — text-embedding-v2 (DashScope)                 │
├──────────────────────────────────────────────────────────────┤
│  Observability: LangSmith (@traceable)                        │
└──────────────────────────────────────────────────────────────┘
```

<!-- TODO: 替换为更精美的架构图（draw.io / Excalidraw 导出） -->

### Search Pipeline Deep Dive

The search module is the most complex part of the system:

```
User query + platform selection
  → SearchOrchestrator (3-batch concurrent execution)
    → Batch 1: API platforms (Bilibili, Zhihu) — parallel
    → Batch 2: Authenticated platforms (Xiaohongshu) — serial
    → Batch 3: Browser platforms (YouTube, GitHub, Google) — Playwright headless
  → EngagementRanker (interaction-based initial filter)
  → PipelineExecutor (detail extraction → LLM quality assessment)
  → SlotAllocator (proportional top-k selection)
  → SSE progress streaming to frontend
```

### Prompt Strategy

Every Studio tool uses **dynamic instruction assembly** instead of static templates:

```python
# Python-side conditional branching — LLM receives clear, unambiguous instructions
def _build_study_guide_instruction(self, all_days, rag_context, profile_text, 
                                     chat_history, current_day_number, episodic_summary):
    parts = [BASE_INSTRUCTION]
    
    if rag_context:
        parts.append("Materials are your backbone — structure the guide around them.")
    else:
        parts.append("No materials uploaded — generate a general guide.")
    
    if chat_history and episodic_summary:
        parts.append("Use both recent chat and long-term memory as context clues.")
    elif episodic_summary:
        parts.append("No recent chat, but use episodic memory for continuity.")
    # ... more branches for profile, progress, scene detection
    
    return "\n".join(parts)
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- At least one LLM API key (DeepSeek recommended)
- DashScope API key (for text-embedding-v2)

### 1. Clone & Install

```bash
git clone https://github.com/BrunonXU/Stride28.git
cd Stride28

# Backend
python -m venv venv
# Windows: .\venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend
npm install
cd ..
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — fill in your API keys:
#   DEEPSEEK_API_KEY=sk-xxx
#   DASHSCOPE_API_KEY=sk-xxx
#   LANGSMITH_API_KEY=lsv2-xxx (optional, for tracing)
```

### 3. Run

```powershell
# Windows (one-click)
.\start_dev.ps1

# Or manually:
# Terminal 1 — Backend
uvicorn backend.main:app --port 8000 --reload

# Terminal 2 — Frontend
cd frontend && npm run dev
```

Open `http://localhost:5173` and create your first learning plan.

---

## 🗺️ Roadmap

- [x] NotebookLM-style three-panel UI
- [x] Multi-source search aggregation (6 platforms)
- [x] Two-stage quality funnel (engagement + LLM)
- [x] Material-aware chat (explicit attachment mode)
- [x] SQLite unified persistence (8 tables + WAL)
- [x] Episodic Memory (working memory + episodic summary)
- [x] PromptBuilder with dynamic instruction assembly
- [x] Multi-provider support (4 LLM vendors)
- [x] LangSmith full-chain tracing
- [ ] Dynamic prompt optimization for all 7 Studio tools
- [ ] Progress ring UI component (Day X/N visualization)
- [ ] LangGraph-based chat orchestrator
- [ ] RAG evaluation pipeline (hit@k metrics)
- [ ] Multi-modal material understanding (PDF images + VL models)
- [ ] Demo video & polished onboarding

---

## 🧪 Testing

```bash
# Backend (Pytest + Hypothesis property-based testing)
pytest tests/ -v

# Frontend (Vitest)
cd frontend && npx vitest --run
```

The project uses **property-based testing** (Hypothesis) for core modules like search slot allocation, episodic memory compression, and resource aggregation.

---

## 🤝 Contributing

Contributions are welcome! Whether it's a bug report, feature request, or pull request.

<!-- TODO: 创建 CONTRIBUTING.md 后取消注释 -->
<!-- See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. -->

### Development Notes

- Backend changes (Python / `.env`) require server restart
- Frontend changes hot-reload via Vite HMR
- Database: SQLite with snake_case fields, API returns camelCase (auto-converted)
- Embedding model is **fixed** (text-embedding-v2) — changing it breaks ChromaDB vector compatibility

---

## 📜 License

[MIT](LICENSE)

---

## 🙏 Acknowledgments

- [LangChain](https://langchain.com) — LLM framework
- [LangSmith](https://smith.langchain.com) — Observability
- [ChromaDB](https://www.trychroma.com/) — Vector store
- [markmap](https://markmap.js.org/) — Mind map rendering
- [Yixiang-Wu/LearningAgent](https://github.com/Lorry-LY/LearningAgent) — Architecture inspiration

---

<p align="center">
  <strong>Give learning a deadline. Give yourself a rhythm.</strong><br/>
  If Stride28 helps you learn something new, consider giving it a ⭐
</p>
