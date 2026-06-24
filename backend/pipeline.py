"""Agent orchestration pipeline: Director -> Script -> Visual+Voice+Music -> Editor."""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from backend.agents import director, script, visual, voice, music, editor
from backend.config import OUTPUT_DIR

logger = logging.getLogger("lincut.pipeline")


@dataclass
class PipelineEvent:
    stage: str
    message: str
    progress: float  # 0.0 to 1.0
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


def run_pipeline(
    user_prompt: str,
    duration: int = 30,
    num_shots: int = 3,
    include_music: bool = True,
    on_event: Callable[[PipelineEvent], None] = None,
    job_id: str = None,
) -> dict:
    """Run the full video production pipeline.

    Args:
        user_prompt: User's creative description
        duration: Target video duration in seconds
        num_shots: Number of shots to generate
        include_music: Whether to generate background music
        on_event: Callback for progress events
        job_id: Job identifier for isolated output directory

    Returns:
        Dict with output_path and metadata
    """
    # Create job-specific output directory
    if job_id:
        job_output_dir = os.path.join(OUTPUT_DIR, f"job_{job_id}")
    else:
        job_output_dir = OUTPUT_DIR
    os.makedirs(job_output_dir, exist_ok=True)

    def emit(stage, message, progress, data=None):
        if on_event:
            on_event(PipelineEvent(stage, message, progress, data or {}))

    result = {"stages": {}}

    # Stage 1: Director Agent
    emit("director", "Director is analyzing your creative vision...", 0.05)
    t0 = time.time()
    try:
        outline = director.run(user_prompt, duration, num_shots)
    except Exception as e:
        logger.error("Director agent failed: %s", e, exc_info=True)
        emit("director", f"Director failed: {e}", 0.05, {"level": "error"})
        raise RuntimeError(f"Director agent failed: {e}") from e
    logger.info("Director completed in %.1fs", time.time() - t0)
    result["stages"]["director"] = outline
    emit("director", f"Outline ready: {outline['title']} ({len(outline['shots'])} shots)", 0.15,
         {"title": outline["title"], "shots": len(outline["shots"])})

    # Stage 2: Script Agent
    emit("script", "Scriptwriter is crafting detailed production specs...", 0.20)
    t0 = time.time()
    try:
        production_script = script.run(outline)
    except Exception as e:
        logger.error("Script agent failed: %s", e, exc_info=True)
        emit("script", f"Script failed: {e}", 0.20, {"level": "error"})
        raise RuntimeError(f"Script agent failed: {e}") from e
    logger.info("Script completed in %.1fs", time.time() - t0)
    result["stages"]["script"] = production_script
    # Send script preview data to frontend
    script_preview = [
        {"shot": s["shot_number"], "subtitle": s.get("subtitle", ""), "narration": s.get("narration", "")[:50]}
        for s in production_script.get("shots", [])
    ]
    emit("script", "Production script finalized", 0.30, {"script_preview": script_preview})

    # Stage 3: Visual + Voice + Music (truly parallel)
    emit("visual", "Visual team is generating video clips...", 0.35)

    def visual_progress(msg, current, total):
        p = 0.35 + (current / total) * 0.25
        emit("visual", msg, p)

    def voice_progress(msg, current, total):
        p = 0.60 + (current / total) * 0.10
        emit("voice", msg, p)

    def run_visual():
        return visual.run(production_script, on_progress=visual_progress, output_dir=job_output_dir)

    def run_voice():
        emit("voice", "Voice artist is recording narration...", 0.60)
        return voice.run(production_script, on_progress=voice_progress, output_dir=job_output_dir)

    def run_music():
        if not include_music:
            emit("music", "Music disabled by user", 0.78, {"level": "info", "skipped": True})
            return None
        emit("music", "Composer is creating background music...", 0.72)
        try:
            mood = outline["shots"][0].get("mood", "inspiring")
            path = music.run(outline["style"], mood, outline["total_duration"], output_dir=job_output_dir)
            emit("music", "Background music composed", 0.78)
            return path
        except Exception as e:
            logger.warning("Music agent failed: %s", e, exc_info=True)
            emit("music", f"Music generation skipped: {e}", 0.78, {"level": "warning", "skipped": True})
            return None

    # Run Visual, Voice, and Music concurrently
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as executor:
        visual_future = executor.submit(run_visual)
        voice_future = executor.submit(run_voice)
        music_future = executor.submit(run_music)

        try:
            video_results = visual_future.result()
        except Exception as e:
            logger.error("Visual agent failed: %s", e, exc_info=True)
            emit("visual", f"Visual generation failed: {e}", 0.60, {"level": "error"})
            raise RuntimeError(f"Visual agent failed: {e}") from e

        try:
            voice_results = voice_future.result()
        except Exception as e:
            logger.error("Voice agent failed: %s", e, exc_info=True)
            emit("voice", f"Voice generation failed: {e}", 0.70, {"level": "error"})
            raise RuntimeError(f"Voice agent failed: {e}") from e

        bgm_path = music_future.result()
    logger.info("Parallel stage (visual+voice+music) completed in %.1fs", time.time() - t0)

    result["stages"]["visual"] = [
        {"shot": r["shot_number"], "path": r["video_path"]} for r in video_results
    ]
    result["stages"]["voice"] = [
        {"shot": r["shot_number"], "path": r["audio_path"]} for r in voice_results
    ]
    if bgm_path:
        result["stages"]["music"] = {"path": bgm_path}

    # Stage 4: Editor Agent
    emit("editor", "Editor is compositing the final video...", 0.80)
    t0 = time.time()

    def editor_progress(msg, current, total):
        p = 0.80 + (current / total) * 0.18
        emit("editor", msg, p)

    try:
        output_path = editor.run(
            video_results, voice_results, production_script,
            bgm_path=bgm_path, on_progress=editor_progress, output_dir=job_output_dir,
        )
    except Exception as e:
        logger.error("Editor agent failed: %s", e, exc_info=True)
        emit("editor", f"Editor failed: {e}", 0.80, {"level": "error"})
        raise RuntimeError(f"Editor agent failed: {e}") from e
    logger.info("Editor completed in %.1fs", time.time() - t0)

    result["output_path"] = output_path
    emit("complete", "Your video is ready!", 1.0, {"output_path": output_path})

    return result
