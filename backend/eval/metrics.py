"""Rule-based quality checks for eval runs (no mocks — uses real pipeline outputs)."""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    weight: float = 1.0


@dataclass
class CaseMetrics:
    case_id: str
    passed: bool
    score: float
    checks: list[Check] = field(default_factory=list)
    timings_sec: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["checks"] = [asdict(c) for c in self.checks]
        return data


def expected_effective_duration(runtime: int, segment_count: int) -> float:
    """Hailuo 单 clip 最长 6s，成片有效时长上限。"""
    per_seg = max(1, runtime // segment_count)
    return segment_count * min(6, per_seg)


def score_checks(checks: list[Check]) -> tuple[bool, float]:
    if not checks:
        return False, 0.0
    total = sum(c.weight for c in checks)
    earned = sum(c.weight for c in checks if c.passed)
    score = round(100.0 * earned / total, 1)
    passed = all(c.passed for c in checks if c.weight >= 1.0)
    return passed, score


def _ffprobe_json(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def probe_duration(path: str) -> float:
    data = _ffprobe_json(path)
    return float(data["format"]["duration"])


def probe_streams(path: str) -> list[str]:
    data = _ffprobe_json(path)
    return [s.get("codec_type", "") for s in data.get("streams", [])]


def count_srt_entries(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return len(re.findall(r"^\d+\s*$", text, re.MULTILINE))


def check_blueprint(blueprint: dict, runtime: int, segment_count: int) -> list[Check]:
    checks: list[Check] = []
    segments = blueprint.get("segments") or []

    checks.append(Check(
        "blueprint_segment_count",
        len(segments) == segment_count,
        f"got {len(segments)}, want {segment_count}",
    ))
    checks.append(Check(
        "blueprint_runtime",
        blueprint.get("runtime_sec") == runtime,
        f"runtime_sec={blueprint.get('runtime_sec')}, want {runtime}",
    ))

    required_seg = ("seq", "scene_brief", "voiceover", "tone", "length_sec")
    missing = [
        f"seg{seg.get('seq', '?')}.{k}"
        for seg in segments
        for k in required_seg
        if not str(seg.get(k, "")).strip()
    ]
    checks.append(Check(
        "blueprint_fields_complete",
        not missing,
        "missing: " + ", ".join(missing[:8]) if missing else "ok",
    ))

    per_seg = max(1, runtime // max(segment_count, 1))
    expected_len = min(6, per_seg)
    bad_lens = [seg.get("seq") for seg in segments if seg.get("length_sec") != expected_len]
    checks.append(Check(
        "blueprint_segment_lengths",
        not bad_lens,
        f"normalized length_sec should be {expected_len}, bad seq: {bad_lens}",
    ))

    headline = (blueprint.get("headline") or "").strip()
    checks.append(Check(
        "blueprint_headline",
        len(headline) >= 3,
        headline or "(empty)",
        weight=0.5,
    ))
    return checks


def check_plan(plan: dict, segment_count: int) -> list[Check]:
    checks: list[Check] = []
    segments = plan.get("segments") or []

    checks.append(Check(
        "plan_segment_count",
        len(segments) == segment_count,
        f"got {len(segments)}, want {segment_count}",
    ))

    missing_prompt = [seg.get("seq") for seg in segments if not str(seg.get("render_prompt", "")).strip()]
    checks.append(Check(
        "plan_render_prompts",
        not missing_prompt,
        f"missing render_prompt on seq: {missing_prompt}" if missing_prompt else "ok",
    ))

    missing_text = [
        seg.get("seq") for seg in segments
        if not str(seg.get("caption", "")).strip() and not str(seg.get("voiceover", "")).strip()
    ]
    checks.append(Check(
        "plan_captions_or_voiceover",
        not missing_text,
        f"missing caption/voiceover on seq: {missing_text}" if missing_text else "ok",
    ))

    short_captions = sum(
        1 for seg in segments
        if str(seg.get("caption", "")).strip()
        and len(str(seg.get("caption", ""))) <= len(str(seg.get("voiceover", "")))
    )
    checks.append(Check(
        "plan_caption_shorter_than_voiceover",
        short_captions >= max(1, len(segments) // 2),
        f"{short_captions}/{len(segments)} segments have caption <= voiceover length",
        weight=0.5,
    ))
    return checks


def check_trace_artifacts(
    trace: dict,
    workspace: str,
    runtime: int,
    segment_count: int,
    with_score: bool,
    deliverable: Optional[str],
    duration_tolerance_sec: float = 4.0,
) -> list[Check]:
    checks: list[Check] = []
    clips = trace.get("footage") or []
    voices = trace.get("narrator") or []

    checks.append(Check(
        "clip_count",
        len(clips) == segment_count,
        f"got {len(clips)}, want {segment_count}",
    ))
    checks.append(Check(
        "voice_track_count",
        len(voices) == segment_count,
        f"got {len(voices)}, want {segment_count}",
    ))

    clip_paths = [c["path"] for c in clips if c.get("path")]
    voice_paths = [v["path"] for v in voices if v.get("path")]
    missing_media = [p for p in clip_paths + voice_paths if not os.path.isfile(p)]
    checks.append(Check(
        "media_files_exist",
        not missing_media,
        f"missing {len(missing_media)} files" if missing_media else "ok",
    ))

    small = [p for p in clip_paths + voice_paths if os.path.isfile(p) and os.path.getsize(p) < 512]
    checks.append(Check(
        "media_files_non_empty",
        not small,
        f"{len(small)} files under 512 bytes" if small else "ok",
    ))

    if with_score:
        score_path = (trace.get("composer") or {}).get("path")
        checks.append(Check(
            "score_generated",
            bool(score_path and os.path.isfile(score_path)),
            score_path or "no score_path in trace",
            weight=0.5,
        ))

    srt_path = os.path.join(workspace, "captions.srt")
    srt_count = count_srt_entries(srt_path)
    checks.append(Check(
        "captions_srt",
        srt_count == segment_count,
        f"{srt_path}: {srt_count} entries, want {segment_count}",
    ))

    checks.append(Check(
        "deliverable_exists",
        bool(deliverable and os.path.isfile(deliverable)),
        deliverable or "(none)",
    ))

    if deliverable and os.path.isfile(deliverable):
        try:
            actual = probe_duration(deliverable)
            expected = expected_effective_duration(runtime, segment_count)
            delta = abs(actual - expected)
            checks.append(Check(
                "deliverable_duration",
                delta <= duration_tolerance_sec,
                f"actual={actual:.1f}s expected≈{expected:.1f}s delta={delta:.1f}s",
            ))
            streams = probe_streams(deliverable)
            checks.append(Check(
                "deliverable_has_video_audio",
                "video" in streams and "audio" in streams,
                f"streams={streams}",
            ))
        except (subprocess.CalledProcessError, KeyError, ValueError) as exc:
            checks.append(Check("deliverable_ffprobe", False, str(exc)))

    return checks


def check_events(events: list[dict]) -> list[Check]:
    checks: list[Check] = []
    retries = sum(1 for e in events if (e.get("data") or {}).get("retry"))
    checks.append(Check(
        "agent_retries",
        retries <= 3,
        f"{retries} retry events (soft threshold: 3)",
        weight=0.5,
    ))

    agents_seen = {e.get("agent") for e in events if e.get("agent")}
    for name in ("planner", "writer", "footage", "narrator", "assembler"):
        checks.append(Check(
            f"event_agent_{name}",
            name in agents_seen,
            "seen" if name in agents_seen else "missing",
            weight=0.5,
        ))

    complete = any(e.get("agent") == "complete" for e in events)
    checks.append(Check("pipeline_complete_event", complete, "complete event emitted" if complete else "missing"))
    return checks


def judge_blueprint_with_llm(prompt: str, blueprint: dict) -> dict[str, Any]:
    """Optional LLM-as-judge: scores brief ↔ blueprint alignment (1–5)."""
    from backend.core import llm

    rubric = (
        "Score the video blueprint against the creative brief.\n"
        "Return ONLY JSON: {\"score\": 1-5, \"rationale\": \"...\"}\n"
        "5 = highly relevant, coherent segments; 1 = off-topic or incoherent."
    )
    raw = llm.complete([
        {"role": "system", "content": rubric},
        {"role": "user", "content": f"Brief:\n{prompt}\n\nBlueprint:\n{json.dumps(blueprint, ensure_ascii=False)[:6000]}"},
    ], temperature=0.2, max_tokens=400)
    try:
        data = llm.parse_json_object(raw)
        score = float(data.get("score", 0))
        return {
            "score": score,
            "rationale": data.get("rationale", ""),
            "passed": score >= 3.0,
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"score": 0, "rationale": raw[:300], "passed": False}
