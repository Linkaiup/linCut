# linCut

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](Dockerfile)

**linCut** turns a creative brief into a finished MP4 using six cooperating **agents**, each with its own responsibility and built-in retry logic.

<p align="center">
  <em>linCut — Lin's AI Video Studio</em>
</p>

## Agent pipeline

```
Brief (text)
    │
    ▼
Planner Agent ──► Writer Agent
    │
    ├── Footage Agent   (Hailuo clips, per-segment retry)
    ├── Narrator Agent  (TTS)
    └── Composer Agent  (optional score, soft-fail)
    │
    ▼
Assembler Agent (ffmpeg mux + captions)
    │
    ▼
deliverable.mp4
```

Footage, Narrator, and Composer run **in parallel** after the Writer finishes. The **60s** option generates **10 clips × 6s** and stitches them into one minute.

## Agent responsibilities

| Agent | Role | Retry |
|-------|------|-------|
| **Planner** | Brief → blueprint JSON | 2× on LLM / parse errors |
| **Writer** | Blueprint → render specs | 2× on LLM / parse errors |
| **Footage** | Hailuo clip per segment | 2× per clip + parallel pool |
| **Narrator** | TTS voiceover per segment | 2× per track |
| **Composer** | Background score | 2×, optional — skips on failure |
| **Assembler** | ffmpeg mux + captions | 1× |

All agents inherit from `BaseAgent` (`backend/agents/base.py`) which provides `invoke()` with configurable retries and SSE progress events.

## Quick start

```bash
git clone https://github.com/Linkaiup/linCut.git
cd linCut
pip install -r backend/requirements.txt
cp .env.example .env   # add MINIMAX_API_KEY
python -m backend.main
```

Open http://localhost:8000

## Docker 一键运行（推荐）

无需安装 Python，只需 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。

```bash
git clone https://github.com/Linkaiup/linCut.git
cd linCut
./start.sh          # macOS / Linux
# start.bat         # Windows
```

首次运行会自动从 `.env.example` 创建 `.env`，填入 `MINIMAX_API_KEY` 后再次执行 `./start.sh` 即可。

浏览器打开 **http://localhost:8000**。生成的视频保存在 `data/workspace/` 目录。

### 常用命令

```bash
docker compose logs -f    # 查看日志
docker compose down       # 停止服务
docker compose up -d      # 后台启动（已构建过可跳过 --build）
```

修改端口：在 `.env` 中添加 `LINCUT_PORT=9000`，然后 `docker compose up -d`。

### 手动 Docker 方式

```bash
cp .env.example .env      # 编辑 MINIMAX_API_KEY
mkdir -p data/workspace
docker compose up --build -d
```

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/projects` | Start production |
| GET | `/api/projects/{id}` | Status |
| GET | `/api/projects/{id}/events` | SSE agent events |
| GET | `/api/projects/{id}/file` | Download MP4 |

## Layout

```
backend/
  agents/       base + planner, writer, footage, narrator, composer, assembler
  core/         settings, llm helper
  studio.py     agent orchestrator
  api/app.py    FastAPI routes
frontend/
  index.html
```

## License

[MIT](LICENSE)
