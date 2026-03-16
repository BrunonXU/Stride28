# ============================================
# Stride28 后端 Dockerfile
# 基于 Playwright 官方镜像，内置 Chromium
# ============================================

FROM mcr.microsoft.com/playwright/python:v1.49.0-noble AS backend

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium --with-deps

# 复制后端 + 核心逻辑代码
COPY backend/ ./backend/
COPY src/ ./src/
COPY .env.example ./.env.example

# 数据目录（SQLite + ChromaDB）
RUN mkdir -p /app/data /app/data/chroma /app/browser_data

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# 启动 FastAPI
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
