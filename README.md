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

Footage, Narrator, and Composer run **in parallel** after the Writer finishes.

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
