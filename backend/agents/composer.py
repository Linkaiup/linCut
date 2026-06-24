"""Composer Agent — optional background score (non-blocking on failure)."""
import json
import logging
import os
from typing import Optional

from backend.agents.base import BaseAgent, ProductionContext
from backend.core.settings import MINIMAX_BASE_URL, http

log = logging.getLogger("lincut.agents.composer")


class ComposerAgent(BaseAgent):
    name = "composer"
    max_retries = 2
    optional = True

    def _progress_hint(self, ctx: ProductionContext) -> float:
        return 0.72

    def run(self, ctx: ProductionContext) -> Optional[str]:
        if not ctx.with_score:
            self.emit("Score disabled by user", 0.78, {"level": "info", "skipped": True})
            return None

        self.emit("Composing background score...", 0.72)
        blueprint = ctx.blueprint
        tone = blueprint["segments"][0].get("tone", "uplifting")

        def _call():
            resp = http.post(
                f"{MINIMAX_BASE_URL}/music_generation",
                json={
                    "model": "music-2.0",
                    "prompt": (
                        f"Instrumental score for a {blueprint['runtime_sec']}s {blueprint['look']} video. "
                        f"Mood: {tone}. No vocals, cinematic background bed."
                    ),
                    "lyrics": "[Instrumental]\nBackground score\nCinematic\nPolished",
                    "audio_setting": {"sample_rate": 44100, "bitrate": 128000, "format": "mp3"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            base = data.get("base_resp", {})
            if base.get("status_code", 0) != 0:
                raise RuntimeError(
                    f"MiniMax Music error: {base.get('status_msg', 'unknown')} (code {base.get('status_code')})"
                )
            if "data" not in data or "audio" not in data["data"]:
                raise RuntimeError(f"Score generation failed: {json.dumps(data)[:500]}")
            dest = os.path.join(ctx.workspace, "score.mp3")
            with open(dest, "wb") as f:
                f.write(bytes.fromhex(data["data"]["audio"]))
            return dest

        path = self.retry_call(_call, "Score generation", 0.75)
        ctx.score_path = path
        self.emit("Score ready", 0.78)
        return path
