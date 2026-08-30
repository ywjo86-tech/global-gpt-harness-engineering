"""Persistent, replay-safe recovery for terminated bound worker workspaces."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .lifecycle_binding import canonical_bytes, validate_binding
from .production_lifecycle import consume, produce


class PartialRecoveryError(ValueError): pass


STATES = (
    "WORKER_REQUESTED", "WORKER_RUNNING", "PARTIAL_WORKSPACE_DETECTED",
    "LIVE_BOUND_WORKER", "TERMINATED_ADOPTABLE_PARTIAL",
    "INVALID_OR_AMBIGUOUS_PARTIAL", "ADOPTION_VALIDATED", "RESULT_PUBLISHED",
    "REVIEW_PENDING", "REMEDIATION_REQUIRED", "REVIEW_PASSED", "CHECKPOINTED",
    "LV_EXITED",
)
TRANSITIONS = {
    "WORKER_REQUESTED":{"WORKER_RUNNING"},
    "WORKER_RUNNING":{"PARTIAL_WORKSPACE_DETECTED"},
    "PARTIAL_WORKSPACE_DETECTED":{"LIVE_BOUND_WORKER", "TERMINATED_ADOPTABLE_PARTIAL", "INVALID_OR_AMBIGUOUS_PARTIAL"},
    "LIVE_BOUND_WORKER":set(), "INVALID_OR_AMBIGUOUS_PARTIAL":set(),
    "TERMINATED_ADOPTABLE_PARTIAL":{"ADOPTION_VALIDATED"},
    "ADOPTION_VALIDATED":{"RESULT_PUBLISHED"},
    "RESULT_PUBLISHED":{"REVIEW_PENDING"},
    "REVIEW_PENDING":{"REMEDIATION_REQUIRED", "REVIEW_PASSED"},
    "REMEDIATION_REQUIRED":{"RESULT_PUBLISHED"},
    "REVIEW_PASSED":{"CHECKPOINTED"}, "CHECKPOINTED":{"LV_EXITED"},
    "LV_EXITED":set(),
}


def _atomic_create(path: Path, value: Mapping[str, Any]) -> None:
    data = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        try: os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data: raise PartialRecoveryError("append-only publication conflict")
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class PartialRecoveryMachine:
    def __init__(self, root: str | Path, binding: Mapping[str, Any]):
        self.root = Path(root)
        self.binding = validate_binding(binding)
        self.journal = self.root / "recovery.events.jsonl"

    def events(self) -> list[dict[str, Any]]:
        if not self.journal.exists(): return []
        try:
            rows = [json.loads(line) for line in self.journal.read_text(encoding="utf-8").splitlines() if line]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PartialRecoveryError("corrupt recovery journal") from exc
        predecessor = None
        for index, row in enumerate(rows):
            supplied = row.get("event_sha256")
            projection = {k:v for k,v in row.items() if k != "event_sha256"}
            if row.get("sequence") != index + 1 or row.get("predecessor") != predecessor or supplied != hashlib.sha256(canonical_bytes(projection)).hexdigest():
                raise PartialRecoveryError("recovery journal lineage mismatch")
            predecessor = supplied
        return rows

    @property
    def state(self) -> str | None:
        rows = self.events(); return rows[-1]["state"] if rows else None

    def advance(self, state: str, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if state not in STATES: raise PartialRecoveryError("unknown recovery state")
        rows = self.events(); current = rows[-1]["state"] if rows else None
        if current == state: return rows[-1]
        if current is None:
            if state != "WORKER_REQUESTED": raise PartialRecoveryError("recovery must start requested")
        elif state not in TRANSITIONS[current]:
            raise PartialRecoveryError("duplicate or out-of-order recovery transition")
        event = {"schema_version":"orchestration.partial-recovery-event.v1",
                 "sequence":len(rows)+1, "state":state,
                 "binding":self.binding, "evidence":dict(evidence or {}),
                 "predecessor":rows[-1]["event_sha256"] if rows else None}
        event["event_sha256"] = hashlib.sha256(canonical_bytes(event)).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        # Journal append is serialized as replace-after-fsync; event lineage makes
        # crash replay deterministic and rejects partial/corrupt writes.
        data = b"".join(canonical_bytes(row)+b"\n" for row in [*rows,event])
        fd,tmp=tempfile.mkstemp(prefix="journal.",dir=self.root)
        try:
            with os.fdopen(fd,"wb") as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp,self.journal)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        return event

    def classify_worker(self, *, recorded_pid: int, recorded_start: str,
                        process_probe: Callable[[int], str | None], diff: Mapping[str,str],
                        owned_scope: Sequence[str]) -> str:
        if self.state != "PARTIAL_WORKSPACE_DETECTED": raise PartialRecoveryError("partial detection required")
        actual_start = process_probe(recorded_pid)
        if actual_start == recorded_start:
            self.advance("LIVE_BOUND_WORKER", {"pid":recorded_pid}); return "LIVE_BOUND_WORKER"
        outside = sorted(set(diff) - set(owned_scope))
        if outside:
            self.advance("INVALID_OR_AMBIGUOUS_PARTIAL", {"outside_owned_scope":outside}); return "INVALID_OR_AMBIGUOUS_PARTIAL"
        # Missing heartbeat is never consulted. Only absence or a start-time
        # mismatch proves the recorded process binding is no longer live.
        self.advance("TERMINATED_ADOPTABLE_PARTIAL", {"pid":recorded_pid,"diff":dict(diff)})
        return "TERMINATED_ADOPTABLE_PARTIAL"

    def adopt(self, diff: Mapping[str,str], owned_scope: Sequence[str]) -> dict[str,Any]:
        if set(diff) - set(owned_scope): raise PartialRecoveryError("owned scope exceeded")
        if self.state == "ADOPTION_VALIDATED": return self.events()[-1]
        if self.state != "TERMINATED_ADOPTABLE_PARTIAL": raise PartialRecoveryError("terminated partial required")
        return self.advance("ADOPTION_VALIDATED", {"owned_diff":dict(sorted(diff.items()))})

    def publish_result(self, payload: Mapping[str,Any]) -> dict[str,Any]:
        if self.state == "RESULT_PUBLISHED":
            artifact=json.loads((self.root/"worker.result.json").read_text(encoding="utf-8"))
            return consume("worker_result",artifact,self.binding)
        if self.state not in {"ADOPTION_VALIDATED","REMEDIATION_REQUIRED"}:
            raise PartialRecoveryError("validated adoption or remediation required")
        artifact=produce("worker_result",payload,self.binding)
        _atomic_create(self.root/"worker.result.json",artifact)
        self.advance("RESULT_PUBLISHED",{"envelope_sha256":artifact["envelope_sha256"]})
        return artifact

    def review(self, verdict: str) -> str:
        if self.state == "RESULT_PUBLISHED": self.advance("REVIEW_PENDING")
        if self.state != "REVIEW_PENDING" or verdict not in {"PASS","FAIL"}: raise PartialRecoveryError("invalid review transition")
        target="REVIEW_PASSED" if verdict=="PASS" else "REMEDIATION_REQUIRED"
        self.advance(target,{"verdict":verdict}); return target

    def complete(self) -> None:
        if not (self.root/"worker.result.json").is_file(): raise PartialRecoveryError("result required before completion")
        if self.state != "REVIEW_PASSED": raise PartialRecoveryError("review PASS required")
        self.advance("CHECKPOINTED"); self.advance("LV_EXITED")
