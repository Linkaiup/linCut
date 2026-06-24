"""Writer Agent — expands blueprint into render-ready segment specs."""
import json
import logging

from backend.agents.base import BaseAgent, ProductionContext
from backend.core import llm

log = logging.getLogger("lincut.agents.writer")

SYSTEM = """You are a production writer turning a video blueprint into render specifications.

For each segment produce:
- render_prompt: vivid prompt for AI video (subject, motion, lens, lighting, palette). Max 200 words.
- voiceover: polished narration timed to segment length
- caption: concise on-screen caption (shorter than voiceover if needed)
- tone: carry over emotional tone

Return ONLY JSON with a "segments" array."""


class WriterAgent(BaseAgent):
    name = "writer"
    max_retries = 2

    def _progress_hint(self, ctx: ProductionContext) -> float:
        return 0.20

    def run(self, ctx: ProductionContext) -> dict:
        self.emit("Drafting segment specifications...", 0.20)
        blueprint = ctx.blueprint
        user_msg = (
            f"Headline: {blueprint['headline']}\n"
            f"Look: {blueprint['look']}\n"
            f"Runtime: {blueprint['runtime_sec']}s\n\n"
            f"Segments:\n{json.dumps(blueprint['segments'], indent=2)}\n\n"
            f"Expand each segment with render_prompt and caption."
        )
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        def _call():
            raw = llm.complete(messages, max_tokens=3000)
            try:
                plan = llm.parse_json_object(raw)
            except json.JSONDecodeError:
                messages.extend([
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "Return ONLY valid JSON, no markdown."},
                ])
                plan = llm.parse_json_object(llm.complete(messages, max_tokens=3000))
            plan["headline"] = blueprint["headline"]
            plan["look"] = blueprint["look"]
            plan["runtime_sec"] = blueprint["runtime_sec"]
            return plan

        plan = self.retry_call(_call, "LLM screenplay", 0.25)
        ctx.plan = plan

        preview = [
            {"seq": s["seq"], "caption": s.get("caption", ""), "voiceover": s.get("voiceover", "")[:50]}
            for s in plan.get("segments", [])
        ]
        self.emit("Production plan locked", 0.30, {"plan_preview": preview})
        return plan
