"""Read-only discovery of pending Full Plan user-attention events across registered jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .production_attention import AttentionOutbox


def _load_json(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def discover_registered_jobs(search_root: str | Path) -> list[dict[str, Any]]:
    root = Path(search_root).resolve()
    jobs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in root.rglob("*.job.json"):
        if "production-full-plan-jobs" not in path.parts:
            continue
        job = _load_json(path)
        if not job:
            continue
        project_id = str(job.get("project_id") or "")
        run_id = str(job.get("run_id") or "")
        harness_root = str(job.get("harness_root") or "")
        if not project_id or not run_id or not harness_root:
            continue
        key = (project_id, run_id, str(Path(harness_root).resolve()))
        if key in seen:
            continue
        seen.add(key)
        jobs.append({"project_id": project_id, "run_id": run_id, "harness_root": key[2], "job_path": str(path)})
    return sorted(jobs, key=lambda item: (item["project_id"], item["run_id"], item["harness_root"]))


def discover_pending_attention(search_root: str | Path, *, stale_after_seconds: int = 120) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in discover_registered_jobs(search_root):
        harness = Path(job["harness_root"])
        run_base = harness / "_workspace" / "production-full-plan" / job["project_id"] / job["run_id"]
        state = _load_json(run_base / "state.json") or {}
        outbox = AttentionOutbox(run_base, project_id=job["project_id"], run_id=job["run_id"])
        pending = outbox.pending()
        for event in pending:
            rows.append({
                "project_id": job["project_id"],
                "run_id": job["run_id"],
                "state": str(state.get("state") or event.get("state") or "UNKNOWN"),
                "current_gate": state.get("current_gate") or event.get("gate_id"),
                "last_semantic_progress_at": state.get("last_semantic_progress_at") or state.get("last_progress_at"),
                "event_id": event.get("event_id"),
                "kind": event.get("kind"),
                "reason": event.get("reason"),
                "created_at": event.get("created_at"),
                "harness_root": job["harness_root"],
            })
        active = {"READY", "DISPATCHED", "RUNNING", "VERIFYING", "RECOVERING"}
        last_live = state.get("last_liveness_at") or state.get("last_progress_at")
        if str(state.get("state")) in active and isinstance(last_live, str):
            try:
                observed = datetime.fromisoformat(last_live.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
            except (ValueError, TypeError):
                age = -1
            if age >= stale_after_seconds:
                seed = f"{job['project_id']}|{job['run_id']}|{state.get('state')}|{last_live}"
                event_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()
                if event_id not in {str(item.get("event_id")) for item in pending}:
                    rows.append({
                        "project_id": job["project_id"], "run_id": job["run_id"],
                        "state": str(state.get("state")), "current_gate": state.get("current_gate"),
                        "last_semantic_progress_at": state.get("last_semantic_progress_at") or state.get("last_progress_at"),
                        "event_id": event_id, "kind": "SUPERVISOR_OR_WORKER_LIVENESS_LOST",
                        "reason": "NO_RECENT_LIVENESS_HEARTBEAT", "created_at": last_live,
                        "harness_root": job["harness_root"], "synthetic_read_only": True,
                    })
    return sorted(rows, key=lambda item: (str(item.get("created_at") or ""), str(item.get("event_id") or "")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover pending Full Plan attention events")
    parser.add_argument("--search-root", required=True)
    parser.add_argument("--stale-after-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    print(json.dumps({"pending": discover_pending_attention(args.search_root, stale_after_seconds=args.stale_after_seconds)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
