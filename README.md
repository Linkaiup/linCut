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

## Quality eval (real API)

End-to-end quality evaluation runs the **full agent pipeline** against MiniMax + ffmpeg (costs API credits and time).

```bash
pip install -r backend/requirements.txt
cp .env.example .env   # MINIMAX_API_KEY required
brew install ffmpeg    # macOS

# Daily regression — 2 × 12s cases (~8–15 min depending on Hailuo queue)
python -m backend.eval.run_eval

# Include 60s / 10-clip case (expensive)
python -m backend.eval.run_eval --tag quick --tag full

# Single case + LLM judge on blueprint quality
python -m backend.eval.run_eval --case product_intro --judge

# Compare against a previous run
python -m backend.eval.run_eval --compare eval_runs/20250624_120000/report.json
```

Reports are written to `eval_runs/{run_id}/`:

| File | Content |
|------|---------|
| `report.json` | Summary scores, pass/fail, all checks |
| `{case_id}/trace.json` | Planner/Writer/Media artifact paths |
| `{case_id}/events.json` | Agent SSE-style event log |
| `{case_id}/metrics.json` | Per-case checks |

**Metrics (rule-based):** segment counts, blueprint/plan field completeness, clip & voice file presence, SRT entry count, deliverable duration vs Hailuo 6s cap, ffprobe video+audio streams, retry/complete events. Optional `--judge` adds an LLM 1–5 relevance score on the blueprint.

Edit cases in `backend/eval/prompts.json` (`quick` tag = 12s/2 clips, `full` = 60s/10 clips).

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

浏览器打开 http://localhost:8000
生成的视频保存在 `data/workspace/` 目录。

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
  eval/         real-API quality eval (prompts.json, metrics, run_eval)
  studio.py     agent orchestrator
  api/app.py    FastAPI routes
eval_runs/      eval reports (gitignored)
frontend/
  index.html
```

## License

[MIT](LICENSE)
