"""Studio orchestrator — coordinates production agents."""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from backend.agents.assembler import AssemblerAgent
from backend.agents.base import AgentEvent, ProductionContext
from backend.agents.composer import ComposerAgent
from backend.agents.footage import FootageAgent
from backend.agents.narrator import NarratorAgent
from backend.agents.planner import PlannerAgent
from backend.agents.writer import WriterAgent
from backend.core.settings import WORKSPACE_ROOT

log = logging.getLogger("lincut.studio")


def produce(
    prompt: str,
    runtime: int = 30,
    segment_count: int = 3,
    with_score: bool = True,
    on_event: Callable[[AgentEvent], None] = None,
    project_id: str = None,
) -> dict:
    """Run the full agent pipeline and return deliverable path + trace."""
    workspace = (
        os.path.join(WORKSPACE_ROOT, f"project_{project_id}")
        if project_id
        else WORKSPACE_ROOT
    )
    os.makedirs(workspace, exist_ok=True)

    ctx = ProductionContext(
        prompt=prompt,
        runtime=runtime,
        segment_count=segment_count,
        with_score=with_score,
        workspace=workspace,
    )
    trace = {}

    # ── Planning agents (sequential) ───────────────────────────────────
    t0 = time.time()
    PlannerAgent(on_event).invoke(ctx)
    log.info("Planner agent done in %.1fs", time.time() - t0)
    trace["planner"] = ctx.blueprint

    t0 = time.time()
    WriterAgent(on_event).invoke(ctx)
    log.info("Writer agent done in %.1fs", time.time() - t0)
    trace["writer"] = ctx.plan

    # ── Media agents (parallel) ────────────────────────────────────────
    t0 = time.time()
    footage = FootageAgent(on_event)
    narrator = NarratorAgent(on_event)
    composer = ComposerAgent(on_event)

    with ThreadPoolExecutor(max_workers=3) as pool:
        clip_f = pool.submit(footage.invoke, ctx)
        voice_f = pool.submit(narrator.invoke, ctx)
        score_f = pool.submit(composer.invoke, ctx)

        clip_f.result()
        voice_f.result()
        score_f.result()

    log.info("Media agents done in %.1fs", time.time() - t0)
    trace["footage"] = [{"seq": c["seq"], "path": c["clip_path"]} for c in ctx.clips]
    trace["narrator"] = [{"seq": v["seq"], "path": v["track_path"]} for v in ctx.voice_tracks]
    if ctx.score_path:
        trace["composer"] = {"path": ctx.score_path}

    # ── Assembly agent ─────────────────────────────────────────────────
    t0 = time.time()
    AssemblerAgent(on_event).invoke(ctx)
    log.info("Assembler agent done in %.1fs", time.time() - t0)

    if on_event:
        on_event(AgentEvent(
            "complete", "Video ready for download", 1.0,
            {"deliverable": ctx.deliverable},
        ))

    return {"deliverable": ctx.deliverable, "trace": trace}
