"""Planner Agent — interprets the user brief into a production blueprint."""
import json
import logging

from backend.agents.base import BaseAgent, ProductionContext
from backend.core import llm

log = logging.getLogger("lincut.agents.planner")

SYSTEM = """You are a creative producer planning a short-form video. Break the user's idea into a structured blueprint.

For each segment provide:
- seq: segment index starting at 1
- length_sec: duration in seconds (total must match requested length)
- scene_brief: visual description for AI video (camera, lighting, motion, subject)
- voiceover: spoken narration for this segment (English)
- tone: emotional tone (e.g. uplifting, tense, calm, lively)

Top-level fields:
- headline: short video title
- look: overall visual style
- runtime_sec: total seconds

Return ONLY valid JSON, no markdown."""


class PlannerAgent(BaseAgent):
    name = "planner"
    max_retries = 2

    def _progress_hint(self, ctx: ProductionContext) -> float:
        return 0.05

    def run(self, ctx: ProductionContext) -> dict:
        self.emit("Analyzing creative brief...", 0.05)
        per_seg = max(1, ctx.runtime // ctx.segment_count)
        user_msg = (
            f"Plan a {ctx.runtime}s video with {ctx.segment_count} segments (~{per_seg}s each).\n"
            f"Brief: {ctx.prompt}"
        )
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        def _call():
            raw = llm.complete(messages)
            return self._parse(raw, messages, ctx)

        blueprint = self.retry_call(_call, "LLM blueprint", 0.08)
        ctx.blueprint = blueprint
        self.emit(
            f"Blueprint ready: {blueprint['headline']} ({len(blueprint['segments'])} segments)",
            0.15,
            {"headline": blueprint["headline"], "segments": len(blueprint["segments"])},
        )
        return blueprint

    def _parse(self, raw: str, messages: list, ctx: ProductionContext) -> dict:
        retry_hint = (
            "Invalid JSON. Return ONLY JSON with keys: headline, look, runtime_sec, segments[]. "
            "Each segment needs seq, length_sec, scene_brief, voiceover, tone."
        )
        try:
            return self._validate(llm.parse_json_object(raw), ctx)
        except (json.JSONDecodeError, ValueError) as err:
            log.warning("Planner JSON parse failed (%s), asking LLM again", err)
            messages.extend([{"role": "assistant", "content": raw}, {"role": "user", "content": retry_hint}])
            raw2 = llm.complete(messages)
            return self._validate(llm.parse_json_object(raw2), ctx)

    def _normalize_segment_lengths(self, blueprint: dict) -> dict:
        """Align segment durations with runtime ÷ count (60s → 10×6s)."""
        segments = blueprint["segments"]
        per_seg = max(1, blueprint["runtime_sec"] // len(segments))
        for seg in segments:
            seg["length_sec"] = per_seg
        return blueprint

    def _validate(self, blueprint: dict, ctx: ProductionContext) -> dict:
        blueprint = llm.unwrap_payload(blueprint, "segments")
        segments = blueprint.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ValueError("Blueprint missing non-empty 'segments' array")
        if len(segments) != ctx.segment_count:
            raise ValueError(
                f"Blueprint has {len(segments)} segments, expected {ctx.segment_count}"
            )
        blueprint.setdefault("headline", ctx.prompt[:50].strip() or "Untitled")
        blueprint.setdefault("look", "cinematic")
        blueprint.setdefault("runtime_sec", ctx.runtime)
        return self._normalize_segment_lengths(blueprint)
