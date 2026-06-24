"""Footage Agent — renders video clips via Hailuo (parallel per segment)."""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from backend.agents.base import BaseAgent, ProductionContext
from backend.core.settings import MINIMAX_BASE_URL, http

log = logging.getLogger("lincut.agents.footage")


class FootageAgent(BaseAgent):
    name = "footage"
    max_retries = 2

    def _progress_hint(self, ctx: ProductionContext) -> float:
        return 0.35

    def run(self, ctx: ProductionContext) -> list:
        self.emit("Rendering video clips...", 0.35)
        segments = ctx.plan["segments"]
        workspace = ctx.workspace
        slots = [None] * len(segments)

        with ThreadPoolExecutor(max_workers=3) as pool:
            pending = {
                pool.submit(self._render_segment, seg, i, workspace, len(segments)): i
                for i, seg in enumerate(segments)
            }
            for future in as_completed(pending):
                idx = pending[future]
                slots[idx] = future.result()
                self.emit(
                    f"Clip {idx + 1} rendered",
                    0.35 + ((idx + 1) / len(segments)) * 0.25,
                )

        ctx.clips = slots
        return slots

    def _render_segment(self, segment: dict, index: int, workspace: str, total: int) -> dict:
        def _once():
            task_id = self._submit_job(segment["render_prompt"], segment.get("length_sec", 6))
            file_id = self._wait_for_file(task_id)
            clip_path = self._pull_file(file_id, f"clip_{index + 1}.mp4", workspace)
            return {
                "seq": segment["seq"],
                "clip_path": clip_path,
                "length_sec": segment.get("length_sec", 6),
            }

        progress = 0.35 + ((index + 1) / total) * 0.25
        return self.retry_call(_once, f"Clip {index + 1}", progress)

    def _submit_job(self, prompt: str, length_sec: int) -> str:
        resp = http.post(
            f"{MINIMAX_BASE_URL}/video_generation",
            json={
                "prompt": prompt,
                "model": "MiniMax-Hailuo-2.3",
                "duration": min(length_sec, 6),
                "resolution": "1080P",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        base = data.get("base_resp", {})
        if base.get("status_code", 0) != 0:
            raise RuntimeError(
                f"MiniMax API error: {base.get('status_msg', 'unknown')} (code {base.get('status_code')})"
            )
        task_id = data.get("task_id")
        if not task_id:
            raise RuntimeError(f"Video job rejected: {data}")
        return task_id

    def _wait_for_file(self, task_id: str, timeout: int = 300) -> str:
        url = f"{MINIMAX_BASE_URL}/query/video_generation"
        started = time.time()
        while time.time() - started < timeout:
            time.sleep(10)
            data = http.get(url, params={"task_id": task_id}).json()
            status = data.get("status", "Unknown")
            if status == "Success":
                return data["file_id"]
            if status == "Fail":
                raise RuntimeError(f"Video render failed: {data.get('error_message')}")
        raise TimeoutError(f"Video render timed out after {timeout}s")

    def _pull_file(self, file_id: str, filename: str, workspace: str) -> str:
        resp = http.get(f"{MINIMAX_BASE_URL}/files/retrieve", params={"file_id": file_id})
        resp.raise_for_status()
        url = resp.json()["file"]["download_url"]
        dest = os.path.join(workspace, filename)
        with open(dest, "wb") as f:
            f.write(requests.get(url).content)
        return dest
