"""Narrator Agent — synthesizes voiceover tracks per segment."""
import json
import logging
import os

from backend.agents.base import BaseAgent, ProductionContext
from backend.core.settings import MINIMAX_BASE_URL, http

log = logging.getLogger("lincut.agents.narrator")

_TONE_TO_EMOTION = {
    "uplifting": "happy",
    "inspiring": "happy",
    "dramatic": "sad",
    "calm": "neutral",
    "lively": "happy",
    "energetic": "happy",
    "contemplative": "neutral",
    "exciting": "happy",
    "professional": "neutral",
    "warm": "happy",
}


class NarratorAgent(BaseAgent):
    name = "narrator"
    max_retries = 2

    def _progress_hint(self, ctx: ProductionContext) -> float:
        return 0.60

    def run(self, ctx: ProductionContext) -> list:
        self.emit("Recording voiceover...", 0.60)
        tracks = []
        segments = ctx.plan["segments"]
        workspace = ctx.workspace

        for i, seg in enumerate(segments):
            path = self.retry_call(
                lambda s=seg, idx=i: self._synthesize(
                    s["voiceover"], f"voice_{idx + 1}.mp3", s.get("tone", "neutral"), workspace
                ),
                f"Voice track {i + 1}",
                0.60 + ((i + 1) / len(segments)) * 0.10,
            )
            tracks.append({"seq": seg["seq"], "track_path": path})
            self.emit(f"Voice track {i + 1} ready", 0.60 + ((i + 1) / len(segments)) * 0.10)

        ctx.voice_tracks = tracks
        return tracks

    def _synthesize(self, text: str, filename: str, tone: str, workspace: str) -> str:
        emotion = _TONE_TO_EMOTION.get(tone, "neutral")
        resp = http.post(
            f"{MINIMAX_BASE_URL}/t2a_v2",
            json={
                "model": "speech-2.6-hd",
                "text": text,
                "stream": False,
                "voice_setting": {
                    "voice_id": "English_expressive_narrator",
                    "speed": 1,
                    "vol": 1,
                    "pitch": 0,
                    "emotion": emotion,
                },
                "audio_setting": {
                    "sample_rate": 32000,
                    "bitrate": 128000,
                    "format": "mp3",
                    "channel": 1,
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
        base = data.get("base_resp", {})
        if base.get("status_code", 0) != 0:
            raise RuntimeError(
                f"MiniMax TTS error: {base.get('status_msg', 'unknown')} (code {base.get('status_code')})"
            )
        if "data" not in data or "audio" not in data["data"]:
            raise RuntimeError(f"TTS failed: {json.dumps(data)[:500]}")

        dest = os.path.join(workspace, filename)
        with open(dest, "wb") as f:
            f.write(bytes.fromhex(data["data"]["audio"]))
        return dest
