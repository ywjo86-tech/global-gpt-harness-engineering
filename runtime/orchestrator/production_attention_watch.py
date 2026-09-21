"""Read-only discovery of pending Full Plan user-attention events across registered jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .production_attention import AttentionOutbox
from .user_interaction_policy import STALL_CONFIRMED, evaluate_attention_delivery
from .harness_state_root import discovery_roots, job_dedupe_key, job_state_root
from .run_supersession import RunSupersessionStore, evaluate_supersession


def _load_json(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def discover_registered_jobs(search_root: str | Path, *, legacy_roots: tuple[str | Path, ...] = ()) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for root in discovery_roots(search_root, legacy_roots):
        if not root.is_dir():
            continue
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
            key = job_dedupe_key(job, source_path=path)
            if key in seen:
                continue
            seen.add(key)
            jobs.append({
                "project_id": project_id, "run_id": run_id,
                "harness_root": str(Path(harness_root).resolve()),
                "harness_state_root": str(job_state_root(job)), "job_path": str(path),
                "authority_core_sha256": str(job.get("authority_core_sha256") or ""),
            })
    return sorted(jobs, key=lambda item: (item["project_id"], item["run_id"], item["harness_state_root"]))


def _age_seconds(value: object, *, now: datetime) -> float:
    if not isinstance(value, str):
        return -1.0
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return -1.0
    if observed.tzinfo is None:
        return -1.0
    return (now - observed.astimezone(timezone.utc)).total_seconds()


def discover_pending_attention(
    search_root: str | Path, *, legacy_roots: tuple[str | Path, ...] = (), stale_after_seconds: int = 120,
    user_attention_after_seconds: int = 300, now: datetime | None = None,
) -> list[dict[str, Any]]:
    if stale_after_seconds <= 0 or user_attention_after_seconds <= 0:
        raise ValueError("attention thresholds must be positive")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("attention clock must be timezone-aware")
    current = current.astimezone(timezone.utc)
    rows: list[dict[str, Any]] = []
    jobs = discover_registered_jobs(search_root, legacy_roots=legacy_roots)
    job_index = {(item["project_id"], item["run_id"], item.get("authority_core_sha256", "")): item for item in jobs}
    for job in jobs:
        state_root = Path(job["harness_state_root"])
        run_base = state_root / "_workspace" / "production-full-plan" / job["project_id"] / job["run_id"]
        state = _load_json(run_base / "state.json") or {}
        outbox = AttentionOutbox(run_base, project_id=job["project_id"], run_id=job["run_id"])
        pending = outbox.pending()
        for event in pending:
            archived = False
            event_with_authority = {**event, "authority_core_sha256": job.get("authority_core_sha256", "")}
            try:
                supersession_store = RunSupersessionStore(state_root)
                for record in supersession_store.find(project_id=job["project_id"], predecessor_run_id=job["run_id"]):
                    successor_job = job_index.get((record.project_id, record.successor_run_id, record.successor_authority_sha256))
                    if successor_job is None:
                        continue
                    successor_base = Path(successor_job["harness_state_root"]) / "_workspace" / "production-full-plan" / record.project_id / record.successor_run_id
                    successor_state = _load_json(successor_base / "state.json") or {}
                    candidate = {
                        "project_id": record.project_id, "run_id": record.successor_run_id,
                        "authority_core_sha256": record.successor_authority_sha256,
                        "state": successor_state.get("state"),
                        "semantic_progress_verified": int(successor_state.get("progress_sequence") or 0) > 0,
                    }
                    if evaluate_supersession(event_with_authority, candidate, record=record).archived:
                        archived = True
                        break
            except Exception:
                archived = False
            if archived:
                continue
            assessment = evaluate_attention_delivery(
                event, state, now=current, threshold_seconds=user_attention_after_seconds,
            )
            if not assessment.eligible:
                continue
            rows.append({
                "project_id": job["project_id"], "run_id": job["run_id"],
                "state": str(state.get("state") or event.get("state") or "UNKNOWN"),
                "current_gate": state.get("current_gate") or event.get("gate_id"),
                "last_semantic_progress_at": state.get("last_semantic_progress_at") or state.get("last_progress_at"),
                "event_id": event.get("event_id"), "kind": event.get("kind"),
                "reason": event.get("reason"), "created_at": event.get("created_at"),
                "delivery_class": assessment.delivery_class,
                "harness_root": job["harness_root"],
            })
        active = {"READY", "DISPATCHED", "RUNNING", "VERIFYING", "RECOVERING"}
        last_live = state.get("last_liveness_at") or state.get("last_progress_at")
        last_semantic = state.get("last_semantic_progress_at") or state.get("last_progress_at") or last_live
        live_age = _age_seconds(last_live, now=current)
        semantic_age = _age_seconds(last_semantic, now=current)
        if (str(state.get("state")) in active and live_age >= stale_after_seconds
                and semantic_age >= user_attention_after_seconds):
            seed = f"{job['project_id']}|{job['run_id']}|{state.get('state')}|{last_live}"
            event_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()
            if event_id not in {str(item.get("event_id")) for item in pending}:
                rows.append({
                    "project_id": job["project_id"], "run_id": job["run_id"],
                    "state": str(state.get("state")), "current_gate": state.get("current_gate"),
                    "last_semantic_progress_at": last_semantic, "event_id": event_id,
                    "kind": "SUPERVISOR_OR_WORKER_LIVENESS_LOST",
                    "reason": "NO_RECENT_LIVENESS_HEARTBEAT", "created_at": last_live,
                    "delivery_class": STALL_CONFIRMED, "harness_root": job["harness_root"],
                    "synthetic_read_only": True,
                })
    return sorted(rows, key=lambda item: (str(item.get("created_at") or ""), str(item.get("event_id") or "")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover pending Full Plan attention events")
    parser.add_argument("--search-root", required=True)
    parser.add_argument("--stale-after-seconds", type=int, default=120)
    parser.add_argument("--user-attention-after-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    print(json.dumps({"pending": discover_pending_attention(
        args.search_root, stale_after_seconds=args.stale_after_seconds,
        user_attention_after_seconds=args.user_attention_after_seconds,
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
