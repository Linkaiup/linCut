"""HTTP API for linCut video projects."""
import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from backend.core.settings import WORKSPACE_ROOT, bootstrap
from backend.agents.base import AgentEvent
from backend.studio import produce

logger = logging.getLogger("lincut")

bootstrap()

app = FastAPI(title="linCut", description="Agent-driven prompt-to-video studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_projects: dict = {}


class CreateProjectBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000)
    duration: int = Field(default=30, ge=18, le=60)
    segment_count: int = Field(default=3, ge=1, le=10)
    with_score: bool = True

    @model_validator(mode="after")
    def check_sixty_second_plan(self):
        if self.duration == 60 and self.segment_count != 10:
            raise ValueError("60-second videos require segment_count=10 (10×6s clips)")
        return self


@app.post("/api/projects")
async def create_project(body: CreateProjectBody):
    project_id = str(uuid.uuid4())[:8]
    logger.info(
        "Project %s queued (prompt=%r, duration=%d, segments=%d, score=%s)",
        project_id, body.prompt[:60], body.duration, body.segment_count, body.with_score,
    )
    _projects[project_id] = {
        "status": "queued",
        "progress": 0.0,
        "events": [],
        "deliverable": None,
        "error": None,
        "created_at": time.time(),
    }
    asyncio.get_event_loop().run_in_executor(
        None,
        _execute_project,
        project_id,
        body.prompt,
        body.duration,
        body.segment_count,
        body.with_score,
    )
    return {"project_id": project_id}


def _execute_project(
    project_id: str,
    prompt: str,
    duration: int,
    segment_count: int,
    with_score: bool,
):
    record = _projects[project_id]
    record["status"] = "running"
    started = time.time()
    logger.info("Project %s: agents started", project_id)

    def on_event(event: AgentEvent):
        record["progress"] = event.progress
        record["events"].append({
            "agent": event.agent,
            "message": event.message,
            "progress": event.progress,
            "data": event.data,
            "timestamp": event.timestamp,
        })

    try:
        result = produce(
            prompt,
            runtime=duration,
            segment_count=segment_count,
            with_score=with_score,
            on_event=on_event,
            project_id=project_id,
        )
        record["status"] = "done"
        record["progress"] = 1.0
        record["deliverable"] = result["deliverable"]
        logger.info(
            "Project %s done in %.1fs → %s",
            project_id, time.time() - started, result["deliverable"],
        )
    except Exception as exc:
        record["status"] = "error"
        record["error"] = str(exc)
        logger.error(
            "Project %s failed after %.1fs: %s",
            project_id, time.time() - started, exc, exc_info=True,
        )


@app.get("/api/projects/{project_id}")
async def project_status(project_id: str):
    if project_id not in _projects:
        raise HTTPException(status_code=404, detail="Project not found")
    return _projects[project_id]


@app.get("/api/projects/{project_id}/events")
async def project_events(project_id: str):
    if project_id not in _projects:
        raise HTTPException(status_code=404, detail="Project not found")

    async def stream() -> AsyncGenerator[str, None]:
        cursor = 0
        while True:
            record = _projects[project_id]
            events = record["events"]
            while cursor < len(events):
                yield f"data: {json.dumps(events[cursor])}\n\n"
                cursor += 1

            if record["status"] in ("done", "error"):
                terminal = {
                    "agent": "closed",
                    "message": "Agents finished" if record["status"] == "done" else f"Error: {record['error']}",
                    "progress": record["progress"],
                    "data": {
                        "status": record["status"],
                        "deliverable": record.get("deliverable"),
                    },
                }
                yield f"data: {json.dumps(terminal)}\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/projects/{project_id}/file")
async def project_file(project_id: str):
    if project_id not in _projects:
        raise HTTPException(status_code=404, detail="Project not found")
    record = _projects[project_id]
    if record["status"] != "done" or not record["deliverable"]:
        raise HTTPException(status_code=400, detail="Video not ready")
    return FileResponse(
        record["deliverable"],
        media_type="video/mp4",
        filename="linCut_video.mp4",
    )


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "linCut"}


async def _purge_stale_projects():
    while True:
        await asyncio.sleep(600)
        cutoff = time.time() - 3600
        stale = [
            pid for pid, rec in _projects.items()
            if rec.get("created_at", 0) < cutoff and rec["status"] in ("done", "error")
        ]
        for pid in stale:
            folder = os.path.join(WORKSPACE_ROOT, f"project_{pid}")
            if os.path.isdir(folder):
                shutil.rmtree(folder, ignore_errors=True)
            del _projects[pid]
        if stale:
            logger.info("Purged %d stale projects", len(stale))


@app.on_event("startup")
async def _on_startup():
    asyncio.create_task(_purge_stale_projects())


_frontend = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
