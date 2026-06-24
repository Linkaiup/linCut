# CLAUDE.md

Guidance for working in the **linCut** repository.

## Commands

```bash
python -m backend.main
pip install -r backend/requirements.txt
python backend/smoke_test.py
docker compose up                   # requires .env with MINIMAX_API_KEY
./start.sh                          # recommended one-click Docker launcher
```

ffmpeg required.

## Architecture

```
POST /api/projects → studio.produce() → SSE /api/projects/{id}/events

Agents (sequential then parallel):
  PlannerAgent  (LLM) → blueprint
  WriterAgent   (LLM) → production plan
  FootageAgent + NarratorAgent + ComposerAgent (parallel)
  AssemblerAgent (ffmpeg) → deliverable.mp4
```

Each agent extends `BaseAgent` in `backend/agents/base.py`:
- `invoke(ctx)` wraps `run(ctx)` with retries (`max_retries`, backoff)
- `optional=True` on ComposerAgent — failures become skip, not fatal
- `retry_call()` for sub-operations (single clip, single voice track)

**Context:** `ProductionContext` carries shared state between agents.

**Parallelism:** `studio.py` ThreadPoolExecutor for media agents. FootageAgent uses inner pool for clips.

**Hailuo:** create task → poll 10s → download (in FootageAgent).

**Frontend:** SSE events use `agent` field — must match agent `name` constants.

## Conventions

- Public entry per agent: class with `run(ctx)`; call via `AgentClass(on_event).invoke(ctx)`
- Check `base_resp.status_code != 0` on MiniMax responses
- Media in `backend/workspace/project_{id}/`
- StaticFiles mounted last in `api/app.py`

## Mistakes Log

| Mistake | Fix |
|---------|-----|
| Empty `choices` on balance error | Check `base_resp.status_code` first |
| Hailuo async | create → poll → download |
| Static mount before routes | Register API routes first |
