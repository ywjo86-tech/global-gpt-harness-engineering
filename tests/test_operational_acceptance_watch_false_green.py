from __future__ import annotations

from runtime.orchestrator.operational_acceptance_watch import (
    blocking_attention_events,
    current_registered_job_keys,
)


def test_blocked_and_failed_attention_remain_operational_blockers():
    events = [
        {"state": "BLOCKED", "event_id": "blocked"},
        {"state": "FAILED", "event_id": "failed"},
        {"state": "WAITING_PROVIDER", "event_id": "waiting"},
        {"state": "COMPLETED", "event_id": "completed"},
        {"state": "CANCELLED", "event_id": "cancelled"},
        {"state": "SUPERSEDED", "event_id": "superseded"},
        {"state": "RETIRED", "event_id": "retired"},
    ]

    blocking = blocking_attention_events(events)

    assert [item["event_id"] for item in blocking] == [
        "blocked",
        "failed",
        "waiting",
    ]


def test_only_latest_registered_run_per_project_blocks(tmp_path):
    old = tmp_path / "jobs" / "P" / "old.job.json"
    new = tmp_path / "jobs" / "P" / "new.job.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}")
    new.write_text("{}")
    import os
    os.utime(old, (100, 100))
    os.utime(new, (200, 200))
    jobs = [
        {"project_id": "P", "run_id": "OLD", "job_path": str(old)},
        {"project_id": "P", "run_id": "NEW", "job_path": str(new)},
    ]
    keys = current_registered_job_keys(jobs)
    assert keys == frozenset({("P", "NEW")})
    blocking = blocking_attention_events(
        [
            {"project_id": "P", "run_id": "OLD", "state": "BLOCKED", "event_id": "old"},
            {"project_id": "P", "run_id": "NEW", "state": "BLOCKED", "event_id": "new"},
        ],
        current_job_keys=keys,
    )
    assert [item["event_id"] for item in blocking] == ["new"]
