"""Assembler Agent — muxes clips, voice, score, and captions into deliverable MP4."""
import json
import logging
import os
import subprocess

from backend.agents.base import BaseAgent, ProductionContext

log = logging.getLogger("lincut.agents.assembler")


class AssemblerAgent(BaseAgent):
    name = "assembler"
    max_retries = 1

    def _progress_hint(self, ctx: ProductionContext) -> float:
        return 0.80

    def run(self, ctx: ProductionContext) -> str:
        self.emit("Muxing deliverable...", 0.80)
        workspace = ctx.workspace

        def _mux():
            return self._compose(ctx.clips, ctx.voice_tracks, ctx.plan, ctx.score_path, workspace)

        deliverable = self.retry_call(_mux, "ffmpeg mux", 0.85)
        ctx.deliverable = deliverable
        self.emit("Export complete", 0.98)
        return deliverable

    def _compose(self, clips, voice_tracks, plan, score_path, workspace):
        merged_video = self._merge_media(
            [c["clip_path"] for c in clips], "clips.txt", "timeline.mp4", workspace
        )
        merged_voice = self._merge_media(
            [t["track_path"] for t in voice_tracks], "voices.txt", "voiceover.mp3", workspace
        )

        clip_lengths = []
        for clip in clips:
            try:
                clip_lengths.append(self._probe_duration(clip["clip_path"]))
            except Exception:
                clip_lengths.append(clip.get("length_sec", 6))

        caption_file = self._write_captions(plan["segments"], clip_lengths, workspace)
        final_path = os.path.join(workspace, "deliverable.mp4")
        duration = self._probe_duration(merged_video)

        inputs = ["-i", merged_video, "-i", merged_voice]
        filters = []
        audio_out = "[1:a]"

        if score_path and os.path.exists(score_path):
            inputs.extend(["-i", score_path])
            audio_out = "[mix]"
            filters.append(
                f"[2:a]atrim=0:{duration},asetpts=PTS-STARTPTS,volume=0.2[bed];"
                f"[1:a]volume=1.0[vox];"
                f"[vox][bed]amix=inputs=2:duration=first[mix]"
            )

        has_subs = "subtitles" in subprocess.run(
            ["ffmpeg", "-filters"], capture_output=True, text=True
        ).stdout
        sub_filter = (
            f"subtitles={caption_file}:force_style="
            f"'FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
            f"BorderStyle=3,Outline=2,Shadow=0,MarginV=30'"
            if has_subs
            else None
        )

        if filters:
            graph = ";".join(filters)
            if sub_filter:
                graph += f";[0:v]{sub_filter}[vout]"
                vmap = "[vout]"
            else:
                vmap = "0:v"
            cmd = [
                "ffmpeg", "-y", *inputs,
                "-filter_complex", graph,
                "-map", vmap, "-map", audio_out,
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                "-t", str(duration), final_path,
            ]
        else:
            cmd = ["ffmpeg", "-y", *inputs]
            if sub_filter:
                cmd.extend(["-vf", sub_filter])
            cmd.extend([
                "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                "-t", str(duration), final_path,
            ])

        subprocess.run(cmd, check=True, capture_output=True)
        return final_path

    def _probe_duration(self, path: str) -> float:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True, check=True,
        )
        return float(json.loads(out.stdout)["format"]["duration"])

    def _srt_timestamp(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _write_captions(self, segments, clip_lengths, workspace):
        path = os.path.join(workspace, "captions.srt")
        cursor = 0.0
        with open(path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments):
                dur = clip_lengths[i] if i < len(clip_lengths) else seg.get("length_sec", 6)
                text = seg.get("caption", seg.get("voiceover", ""))
                f.write(f"{i + 1}\n")
                f.write(f"{self._srt_timestamp(cursor)} --> {self._srt_timestamp(cursor + dur)}\n")
                f.write(f"{text}\n\n")
                cursor += dur
        return path

    def _merge_media(self, paths, list_name, out_name, workspace):
        listing = os.path.join(workspace, list_name)
        with open(listing, "w") as f:
            for p in paths:
                f.write(f"file '{os.path.abspath(p)}'\n")
        dest = os.path.join(workspace, out_name)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", dest],
            check=True, capture_output=True,
        )
        return dest
