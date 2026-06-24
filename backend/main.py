"""FastAPI server for linCut — Lin's AI Video Studio."""
import logging
import os
import json
import shutil
import time
import uuid
import asyncio
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.pipeline import run_pipeline, PipelineEvent
from backend.config import OUTPUT_DIR, validate_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lincut")

validate_config()

app = FastAPI(title="linCut", description="Lin's AI Video Studio — Multi-Agent Video Production")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job storage
jobs: dict = {}


class CreateVideoRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000)
    duration: int = Field(default=30, ge=18, le=30)
    num_shots: int = Field(default=3, ge=1, le=5)
    include_music: bool = True


class JobStatus(BaseModel):
    job_id: str
    status: str  # "pending", "running", "completed", "failed"
    progress: float
    events: list
    output_path: str = None
    error: str = None


@app.post("/api/create")
async def create_video(req: CreateVideoRequest):
    """Start a new video production job."""
    job_id = str(uuid.uuid4())[:8]
    logger.info("Job %s: created (prompt=%r, duration=%d, shots=%d, music=%s)",
                job_id, req.prompt[:60], req.duration, req.num_shots, req.include_music)
    jobs[job_id] = {
        "status": "pending",
        "progress": 0.0,
        "events": [],
        "output_path": None,
        "error": None,
        "created_at": time.time(),
    }

    # Run pipeline in background
    asyncio.get_event_loop().run_in_executor(
        None, _run_job, job_id, req.prompt, req.duration, req.num_shots, req.include_music,
    )

    return {"job_id": job_id}


def _run_job(job_id: str, prompt: str, duration: int, num_shots: int, include_music: bool):
    """Execute the pipeline in a background thread."""
    jobs[job_id]["status"] = "running"
    start_time = time.time()
    logger.info("Job %s: pipeline started", job_id)

    def on_event(event: PipelineEvent):
        jobs[job_id]["progress"] = event.progress
        jobs[job_id]["events"].append({
            "stage": event.stage,
            "message": event.message,
            "progress": event.progress,
            "data": event.data,
            "timestamp": event.timestamp,
        })

    try:
        result = run_pipeline(
            prompt, duration, num_shots, include_music, on_event=on_event, job_id=job_id,
        )
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 1.0
        jobs[job_id]["output_path"] = result["output_path"]
        elapsed = time.time() - start_time
        logger.info("Job %s: completed in %.1fs, output=%s", job_id, elapsed, result["output_path"])
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        elapsed = time.time() - start_time
        logger.error("Job %s: failed after %.1fs: %s", job_id, elapsed, e, exc_info=True)


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Get current job status and progress."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/stream/{job_id}")
async def stream_events(job_id: str):
    """SSE stream for real-time progress updates."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        last_idx = 0
        while True:
            job = jobs[job_id]
            events = job["events"]

            # Send new events
            while last_idx < len(events):
                event = events[last_idx]
                yield f"data: {json.dumps(event)}\n\n"
                last_idx += 1

            if job["status"] in ("completed", "failed"):
                final = {
                    "stage": "done",
                    "message": "Pipeline finished" if job["status"] == "completed" else f"Error: {job['error']}",
                    "progress": job["progress"],
                    "data": {"status": job["status"], "output_path": job.get("output_path")},
                }
                yield f"data: {json.dumps(final)}\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/download/{job_id}")
async def download_video(job_id: str):
    """Download the final video."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if job["status"] != "completed" or not job["output_path"]:
        raise HTTPException(status_code=400, detail="Video not ready")

    return FileResponse(
        job["output_path"],
        media_type="video/mp4",
        filename="linCut_output.mp4",
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "linCut"}


# Job cleanup: remove jobs older than 1 hour every 10 minutes
async def _cleanup_old_jobs():
    while True:
        await asyncio.sleep(600)  # 10 minutes
        cutoff = time.time() - 3600  # 1 hour
        stale = [jid for jid, j in jobs.items()
                 if j.get("created_at", 0) < cutoff and j["status"] in ("completed", "failed")]
        for jid in stale:
            # Remove output directory
            job_dir = os.path.join(OUTPUT_DIR, f"job_{jid}")
            if os.path.isdir(job_dir):
                shutil.rmtree(job_dir, ignore_errors=True)
            del jobs[jid]
        if stale:
            logger.info("Cleaned up %d old jobs: %s", len(stale), stale)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_cleanup_old_jobs())


# Serve frontend static files (must be last - catches all unmatched routes)
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
