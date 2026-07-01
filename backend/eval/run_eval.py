#!/usr/bin/env python3
"""Run real-API quality eval against the full agent pipeline.

Examples:
  python -m backend.eval.run_eval                    # quick cases (12s × 2)
  python -m backend.eval.run_eval --tag full         # include 60s case
  python -m backend.eval.run_eval --case product_intro --judge
  python -m backend.eval.run_eval --compare eval_runs/20250624_120000/report.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.agents.base import AgentEvent
from backend.core.settings import bootstrap
from backend.eval.metrics import (
    CaseMetrics,
    Check,
    check_blueprint,
    check_events,
    check_plan,
    check_trace_artifacts,
    judge_blueprint_with_llm,
    score_checks,
)
from backend.studio import produce

log = logging.getLogger("lincut.eval")

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_PATH = Path(__file__).resolve().parent / "prompts.json"
EVAL_RUNS_DIR = REPO_ROOT / "eval_runs"


def load_cases(tags: list[str] | None = None, case_id: str | None = None) -> list[dict]:
    with open(PROMPTS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    cases = data.get("cases") or []
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
        if not cases:
            raise SystemExit(f"Unknown case id: {case_id}")
        return cases
    if not tags:
        return cases
    tag_set = set(tags)
    return [c for c in cases if tag_set.intersection(c.get("tags") or [])]


def run_case(case: dict, run_dir: Path, *, with_judge: bool) -> CaseMetrics:
    case_id = case["id"]
    case_dir = run_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    events: list[dict] = []
    timings: dict[str, float] = {}
    project_id = f"eval_{case_id}_{uuid.uuid4().hex[:6]}"

    def on_event(event: AgentEvent):
        events.append({
            "agent": event.agent,
            "message": event.message,
            "progress": event.progress,
            "data": event.data,
            "timestamp": event.timestamp,
        })

    metrics = CaseMetrics(case_id=case_id, passed=False, score=0.0)
    t0 = time.time()

    try:
        result = produce(
            case["prompt"],
            runtime=case["duration"],
            segment_count=case["segment_count"],
            with_score=case.get("with_score", False),
            on_event=on_event,
            project_id=project_id,
        )
        timings["total"] = round(time.time() - t0, 1)
        trace = result["trace"]
        deliverable = result["deliverable"]
        workspace = str(REPO_ROOT / "backend" / "workspace" / f"project_{project_id}")

        checks = []
        if trace.get("planner"):
            checks.extend(check_blueprint(trace["planner"], case["duration"], case["segment_count"]))
        if trace.get("writer"):
            checks.extend(check_plan(trace["writer"], case["segment_count"]))
        checks.extend(check_trace_artifacts(
            trace,
            workspace,
            case["duration"],
            case["segment_count"],
            case.get("with_score", False),
            deliverable,
        ))
        checks.extend(check_events(events))

        judge_result = None
        if with_judge and trace.get("planner"):
            judge_result = judge_blueprint_with_llm(case["prompt"], trace["planner"])
            checks.append(Check(
                "llm_judge_blueprint",
                judge_result["passed"],
                f"score={judge_result['score']}: {judge_result.get('rationale', '')[:120]}",
                weight=0.5,
            ))

        passed, score = score_checks(checks)
        metrics.passed = passed
        metrics.score = score
        metrics.checks = checks
        metrics.timings_sec = timings
        metrics.artifacts = {
            "project_id": project_id,
            "workspace": workspace,
            "deliverable": deliverable,
            "judge": judge_result,
        }

        with open(case_dir / "trace.json", "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)
        with open(case_dir / "events.json", "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)

    except Exception as exc:
        metrics.error = str(exc)
        metrics.timings_sec = {"total": round(time.time() - t0, 1)}
        metrics.checks = [Check("pipeline", False, str(exc))]
        metrics.passed = False
        metrics.score = 0.0
        log.exception("Case %s failed", case_id)

    with open(case_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics.to_dict(), f, ensure_ascii=False, indent=2)

    return metrics


def print_case_summary(m: CaseMetrics):
    status = "PASS" if m.passed and not m.error else "FAIL"
    print(f"\n{'─' * 60}")
    print(f"  [{status}] {m.case_id}  score={m.score}  time={m.timings_sec.get('total', '?')}s")
    if m.error:
        print(f"  error: {m.error}")
    for c in m.checks:
        mark = "✓" if c.passed else "✗"
        print(f"    {mark} {c.name}: {c.detail[:100]}")


def compare_reports(current: dict, baseline_path: Path):
    with open(baseline_path, encoding="utf-8") as f:
        baseline = json.load(f)
    base_cases = {c["case_id"]: c for c in baseline.get("cases", [])}

    print(f"\nCompare vs {baseline_path}")
    print(f"{'case':<20} {'score Δ':>10} {'time Δ':>10}")
    for c in current.get("cases", []):
        cid = c["case_id"]
        prev = base_cases.get(cid)
        if not prev:
            print(f"{cid:<20} {'(new)':>10}")
            continue
        ds = c["score"] - prev.get("score", 0)
        dt = c.get("timings_sec", {}).get("total", 0) - prev.get("timings_sec", {}).get("total", 0)
        print(f"{cid:<20} {ds:+.1f}{'':>5} {dt:+.1f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="linCut real-API quality eval")
    parser.add_argument("--tag", action="append", help="Filter by tag (quick, full). Repeatable.")
    parser.add_argument("--case", help="Run a single case id")
    parser.add_argument("--judge", action="store_true", help="LLM-as-judge on blueprint (extra API call)")
    parser.add_argument("--compare", type=Path, help="Compare scores to a previous report.json")
    parser.add_argument("--dry-run", action="store_true", help="List cases and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tags = args.tag or (["quick"] if not args.case else None)
    cases = load_cases(tags=tags, case_id=args.case)

    if args.dry_run:
        for c in cases:
            print(f"{c['id']:<16} tags={c.get('tags')}  {c['duration']}s/{c['segment_count']}seg  score={c.get('with_score')}")
        return 0

    bootstrap()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = EVAL_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"linCut eval run: {run_id}")
    print(f"Cases: {', '.join(c['id'] for c in cases)}")
    print(f"Output: {run_dir}")

    results: list[CaseMetrics] = []
    for i, case in enumerate(cases, 1):
        print(f"\n>>> [{i}/{len(cases)}] {case['id']} ({case['duration']}s, {case['segment_count']} segments)")
        results.append(run_case(case, run_dir, with_judge=args.judge))

    report = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tags": tags,
        "case_ids": [c["id"] for c in cases],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed and not r.error),
            "failed": sum(1 for r in results if not r.passed or r.error),
            "avg_score": round(sum(r.score for r in results) / max(len(results), 1), 1),
        },
        "cases": [r.to_dict() for r in results],
    }

    report_path = run_dir / "report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    for m in results:
        print_case_summary(m)

    s = report["summary"]
    print(f"\n{'═' * 60}")
    print(f"  Summary: {s['passed']}/{s['total']} passed  avg_score={s['avg_score']}")
    print(f"  Report: {report_path}")

    if args.compare:
        compare_reports(report, args.compare)

    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
