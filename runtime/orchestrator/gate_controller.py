from __future__ import annotations

import re
import hashlib
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .canonical_transition import CanonicalTransitionError, validate_canonical_gate_state, validate_governance_descendant
from .production_approval import ApprovalBindings, evaluate_production_authorization
from .recovery_contract import is_completion_eligible
from .production_lifecycle import (
    ProductionLifecycleError, consume as consume_lifecycle, produce as produce_lifecycle,
)
from .lifecycle_binding import DIGEST_FIELDS, build_binding_from_sources, canonical_bytes
from .persisted_artifact import publish as publish_persisted, validate as validate_persisted
from .resume_store import ResumeStore, RunBinding, ResumeStoreError


class GateControllerError(ValueError):
    """Fail-closed error raised at an orchestration lifecycle boundary."""


class GovernanceBranchError(GateControllerError):
    """Known governance precondition failure carrying only bounded identity."""
    def __init__(self, message: str, *, branch_id: str, origin: str = "PRECONDITION"):
        super().__init__(message)
        self.governance_branch_id = branch_id
        self.authorization_branch_id = branch_id
        self.governance_reason_origin = origin
        self.authorization_reason_origin = origin


def _bounded_authorization_reason(exc: BaseException) -> str:
    if isinstance(exc, ApprovalFreshnessError):
        return "STALE_APPROVAL"
    if isinstance(exc, CanonicalTransitionError):
        return "GOVERNANCE_MISMATCH"
    message = str(exc)
    if "scope" in message and "mismatch" in message:
        return "APPROVAL_SCOPE_MISMATCH"
    if "lineage" in message or "record_hash" in message:
        return "APPROVAL_LINEAGE_MISMATCH"
    if "baseline" in message or "descendant" in message:
        return "BASELINE_MISMATCH"
    if "canonical Gate state" in message or "closure" in message:
        return "GOVERNANCE_MISMATCH"
    if "context missing required field" in message or "required field" in message:
        return "GOVERNANCE_MISMATCH"
    return "UNKNOWN"


class ApprovalFreshnessError(GateControllerError):
    """Bounded production freshness failure without commit or approval data."""

    def __init__(self, message: str, *, stage: str):
        super().__init__(message)
        self.approval_freshness_stage = stage
        self.approval_descendant_authorization = "REJECTED"

def adopt_terminated_partial(**kwargs: Any) -> dict[str, Any]:
    """Controller-owned official adoption route; no direct artifact fabrication."""
    from .official_adoption import official_adopt
    return official_adopt(**kwargs)


StageCallable = Callable[[Mapping[str, Any]], Mapping[str, Any]]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_WORKER_STATUS_COMPATIBILITY = {"COMPLETED": "COMPLETED", "PASS": "PASS", "completed": "COMPLETED"}
_FRESHNESS_STAGES = {
    "PRE_RUN", "RESUME_AUTHORIZATION", "POST_REVIEW", "POST_CHECKPOINT",
    "POST_EXIT", "POST_HANDOFF", "FINALIZATION", "PUBLICATION", "UNKNOWN",
}
_CANONICAL_LIFECYCLE_PAYLOAD_FIELDS = frozenset({
    "project_id", "gate_id", "lv_id", "run_id", "plan_sha256", "requirements_sha256",
    "branch", "baseline_head", "current_head", "head", "predecessor_completion_digest",
    "approval_mode", "canonical_lv_scope", "owned_file_scope", "phase", "resume",
    "predecessor_evidence", "predecessor_lv", "completion_conditions", "recovery",
    "canonical_state_override", "attempt", "recovery_id", "approval_event_id",
    "approval_record_hash", "approval_freshness_stage", "owned_files",
    "completed_plan_items", "remaining_plan_items", "execution_mode", "review_attempt",
    "worker_result", "last_stage", "last_status", "package_result", "preflight_result",
    "review_result", "remediation_result", "checkpoint_result", "exit_result", "handoff_result",
})
_LIFECYCLE_RUNTIME_CONTROL_FIELDS = frozenset({
    "lifecycle_binding", "lifecycle_artifact_root", "lifecycle_source_sha256",
    "lifecycle_predecessor",
})


def _canonical_lifecycle_payload(
    state: Mapping[str, Any], prior_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Project public lifecycle semantics; runtime carriers never enter seals."""
    unknown = {
        key for key in state
        if (key not in _CANONICAL_LIFECYCLE_PAYLOAD_FIELDS
            and key not in _LIFECYCLE_RUNTIME_CONTROL_FIELDS
            and not key.startswith("issue065_"))
    }
    if unknown:
        raise ProductionLifecycleError("unsupported lifecycle payload field family")
    payload = {
        key: state[key] for key in _CANONICAL_LIFECYCLE_PAYLOAD_FIELDS
        if key in state
    }
    payload["prior_evidence"] = dict(prior_evidence)
    # This is an invariant, not recovery: public noncanonical state blocks and
    # no field is dropped, stringified, or defaulted after failure.
    canonical_bytes(payload)
    return payload


def _verified_recovery_context(context: Mapping[str, Any]) -> bool:
    """Accept descendant fallback only for a sealed recovery checkpoint."""
    recovery = context.get("recovery")
    if not isinstance(recovery, Mapping):
        return False
    required = ("schema_version", "project_id", "gate_id", "lv_id", "run_id",
                "recovery_id", "next_attempt", "status", "checkpoint_sha256", "hard_stop")
    if any(key not in recovery for key in required) or recovery.get("schema_version") != "orchestration.production-recovery-checkpoint.v1":
        return False
    if any(recovery.get(key) != str(context.get(key)) for key in ("project_id", "gate_id", "lv_id", "run_id")):
        return False
    if (not isinstance(recovery.get("recovery_id"), str) or not recovery["recovery_id"]
            or not isinstance(recovery.get("next_attempt"), int) or recovery["next_attempt"] <= 0
            or recovery.get("hard_stop") is not True or not isinstance(recovery.get("status"), str)):
        return False
    checkpoint_sha = recovery.get("checkpoint_sha256")
    if not isinstance(checkpoint_sha, str) or not _SHA256.fullmatch(checkpoint_sha):
        return False
    unsigned = {key: value for key, value in recovery.items() if key != "checkpoint_sha256"}
    return hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == checkpoint_sha


def has_verified_worker_recovery(
    project_root: str | Path, harness_root: str | Path, *, project_id: str, gate_id: str,
    lv_id: str, run_id: str, plan_sha256: str, requirements_sha256: str | None = None,
    owned_files: Mapping[str, Any] | None = None,
) -> bool:
    """Return true only for a persisted, same-run worker checkpoint.

    This is intentionally narrow: a product descendant is recoverable only
    when the canonical ResumeStore chain contains a sealed WORKER result whose
    checkpoint commit is the current HEAD and whose changed files stay within
    the approval-owned scope.
    """
    try:
        root = Path(project_root)
        current_head = __import__("subprocess").run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        base = Path(harness_root) / "_workspace" / "global-gate-resume"
        owned = {path for values in (owned_files or {}).values() for path in values}
        if not base.is_dir() or not owned:
            return False
        for namespace in base.iterdir():
            if namespace.is_symlink() or not namespace.is_dir():
                continue
            events = namespace / project_id / gate_id / lv_id / run_id / "events"
            first = events / "000001.json"
            if first.is_symlink() or not first.is_file():
                continue
            try:
                payload = json.loads(first.read_text(encoding="utf-8"))
                binding_payload = payload.get("binding")
                if not isinstance(binding_payload, dict):
                    continue
                binding = RunBinding(**binding_payload)
                if (binding.project_id != project_id or binding.gate_id != gate_id or binding.lv_id != lv_id
                        or binding.run_id != run_id or binding.plan_sha256 != plan_sha256
                        or (requirements_sha256 is not None and binding.requirements_sha256 != requirements_sha256)):
                    continue
                store = ResumeStore(namespace, binding)
                records = store.verify()
                for record in records:
                    if record.get("lifecycle") != "WORKER":
                        continue
                    worker = record.get("stage_payload")
                    if not isinstance(worker, dict) or _WORKER_STATUS_COMPATIBILITY.get(worker.get("status")) not in {"COMPLETED", "PASS"}:
                        continue
                    if worker.get("checkpoint_commit") != current_head:
                        continue
                    changed = worker.get("changed_files")
                    if not isinstance(changed, list) or not changed or any(path not in owned for path in changed):
                        continue
                    return True
            except (OSError, UnicodeError, ValueError, TypeError, ResumeStoreError, json.JSONDecodeError):
                continue
    except (OSError, ValueError, __import__("subprocess").SubprocessError):
        return False
    return False


def verify_production_recovery_descendant(
    context: Mapping[str, Any], *, project_root: str | Path, harness_root: str | Path,
) -> bool:
    """Authoritative recovery proof shared by CLI and inner gate validation.

    Explicit completion-recovery checkpoints and the normal crash-after-WORKER
    path are distinct contracts, but both are verified here.  No descendant
    is accepted from Git ancestry alone.
    """
    if _verified_recovery_context(context):
        return True
    required = ("project_id", "gate_id", "lv_id", "run_id", "plan_sha256")
    if any(not context.get(field) for field in required):
        return False
    return has_verified_worker_recovery(
        project_root, harness_root,
        project_id=str(context["project_id"]), gate_id=str(context["gate_id"]),
        lv_id=str(context["lv_id"]), run_id=str(context["run_id"]),
        plan_sha256=str(context["plan_sha256"]),
        requirements_sha256=(str(context["requirements_sha256"]) if context.get("requirements_sha256") else None),
        owned_files=context.get("owned_file_scope"),
    )


def verify_same_run_governed_descendant(
    context: Mapping[str, Any], *, project_root: str | Path, harness_root: str | Path,
    expected_outcome: Mapping[str, Any] | None = None,
) -> bool:
    """Verify a completed same-run product descendant, fail closed.

    This contract is deliberately stronger than Git ancestry.  It consumes one
    immutable ResumeStore chain and requires the normal production lifecycle,
    its cross-stage bindings, the exact worker checkpoint at HEAD, and a clean
    worktree.  It is distinct from predecessor SYSTEM_TRANSITION authorization.
    """
    required = (
        "project_id", "gate_id", "lv_id", "run_id", "plan_sha256",
        "requirements_sha256", "branch", "baseline_head",
        "approval_event_id", "approval_record_hash", "owned_file_scope",
    )
    if any(not context.get(field) for field in required):
        return False
    owned_by_lv = context.get("owned_file_scope")
    if not isinstance(owned_by_lv, Mapping):
        return False
    owned = owned_by_lv.get(context["lv_id"])
    if not isinstance(owned, (list, tuple)) or not owned:
        return False
    try:
        import subprocess
        root = Path(project_root)
        current = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1"],
            capture_output=True, text=True, check=True,
        ).stdout:
            return False
        if subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor",
             str(context["baseline_head"]), current],
            capture_output=True, text=True,
        ).returncode != 0:
            return False

        base = Path(harness_root) / "_workspace" / "global-gate-resume"
        if not base.is_dir() or base.is_symlink():
            return False
        matches = 0
        for namespace in base.iterdir():
            if namespace.is_symlink() or not namespace.is_dir():
                continue
            first = (namespace / str(context["project_id"]) / str(context["gate_id"])
                     / str(context["lv_id"]) / str(context["run_id"])
                     / "events" / "000001.json")
            if first.is_symlink() or not first.is_file():
                continue
            binding_payload = json.loads(first.read_text(encoding="utf-8")).get("binding")
            if not isinstance(binding_payload, dict):
                continue
            binding = RunBinding(**binding_payload)
            if (binding.project_id != context["project_id"]
                    or binding.gate_id != context["gate_id"]
                    or binding.lv_id != context["lv_id"]
                    or binding.run_id != context["run_id"]
                    or binding.plan_sha256 != context["plan_sha256"]
                    or binding.requirements_sha256 != context["requirements_sha256"]
                    or binding.branch != context["branch"]):
                continue
            if subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor",
                 str(context["baseline_head"]), binding.head],
                capture_output=True, text=True,
            ).returncode != 0:
                continue
            checkpoint_count = subprocess.run(
                ["git", "-C", str(root), "rev-list", "--count", f"{binding.head}..{current}"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            if checkpoint_count != "1" or context.get("current_head") != current:
                continue
            records = ResumeStore(namespace, binding).verify()
            if [record.get("lifecycle") for record in records] != [
                "PACKAGE", "PREFLIGHT", "WORKER", "REVIEW",
                "CHECKPOINT", "EXIT", "HANDOFF",
            ]:
                continue
            checkpoints = [record for record in records if record.get("checkpoint") is True]
            if len(checkpoints) != 1 or checkpoints[0] is not records[4]:
                continue
            package, preflight, worker, review, checkpoint, lv_exit, handoff_event = records
            wp = worker.get("stage_payload")
            rp = review.get("stage_payload")
            cp = checkpoint.get("checkpoint_payload")
            if not all(isinstance(value, dict) for value in (wp, rp, cp)):
                continue
            package_path = (Path(harness_root) / "_workspace" / "orchestration-runs"
                            / str(context["run_id"]) / str(context["lv_id"])
                            / "package.manifest.json")
            if package_path.is_symlink() or not package_path.is_file():
                continue
            package_bytes = package_path.read_bytes()
            manifest = json.loads(package_bytes)
            if (hashlib.sha256(package_bytes).hexdigest() != binding.artifact_sha256
                    or manifest.get("project_id") != context["project_id"]
                    or manifest.get("gate_id") != context["gate_id"]
                    or manifest.get("lv_id") != context["lv_id"]
                    or manifest.get("run_id") != context["run_id"]
                    or manifest.get("canonical_plan_sha256") != context["plan_sha256"]
                    or manifest.get("approval_id") != context["approval_event_id"]
                    or manifest.get("approval_record_hash") != context["approval_record_hash"]
                    or manifest.get("source_head") != binding.head):
                continue
            if (package.get("evidence_sha256") != binding.artifact_sha256
                    or wp.get("schema_version") != "orchestration.product-completion-evidence.v1"
                    or wp.get("status") != "COMPLETED"
                    or wp.get("worker_status") != "completed"
                    or wp.get("project_id") != context["project_id"]
                    or wp.get("gate_id") != context["gate_id"]
                    or wp.get("lv_id") != context["lv_id"]
                    or wp.get("run_id") != context["run_id"]
                    or wp.get("plan_sha256") != context["plan_sha256"]
                    or wp.get("approval_event_id") != context["approval_event_id"]
                    or wp.get("package_sha256") != package.get("evidence_sha256")
                    or wp.get("preflight_evidence_sha256") != preflight.get("evidence_sha256")
                    or wp.get("baseline_head") != binding.head
                    or wp.get("checkpoint_commit") != current
                    or wp.get("current_head") != current
                    or wp.get("staged_changes") is not False
                    or wp.get("unstaged_changes") is not False
                    or not isinstance(wp.get("tests"), list) or not wp["tests"]
                    or rp.get("status") != "PASS"
                    or rp.get("run_id") != context["run_id"]
                    or rp.get("worker_result_sha256") != worker.get("evidence_sha256")
                    or cp.get("run_id") != context["run_id"]
                    or cp.get("lv_id") != context["lv_id"]
                    or cp.get("prior_evidence") != {
                        "package": package["evidence_sha256"],
                        "preflight": preflight["evidence_sha256"],
                        "worker": worker["evidence_sha256"],
                        "review": review["evidence_sha256"],
                    }
                    or lv_exit.get("stage_payload", {}).get("status") != "EXITED"
                    or handoff_event.get("stage_payload", {}).get("status") != "SEALED"):
                continue
            changed = wp.get("changed_files")
            if not isinstance(changed, list) or not changed or not set(changed).issubset(set(owned)):
                continue
            committed = subprocess.run(
                ["git", "-C", str(root), "diff-tree", "--no-commit-id", "--name-only", "-r", current],
                capture_output=True, text=True, check=True,
            ).stdout.splitlines()
            if sorted(committed) != sorted(changed):
                continue
            handoff_path = (Path(harness_root) / "_workspace" / "global-gate"
                            / str(context["project_id"]) / "artifact"
                            / f"{context['run_id']}.handoff.json")
            if handoff_path.is_symlink() or not handoff_path.is_file():
                continue
            handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            unsigned = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
            if (handoff.get("handoff_sha256") != hashlib.sha256(json.dumps(
                    unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode()).hexdigest()
                    or handoff.get("project") != context["project_id"]
                    or handoff.get("gate") != context["gate_id"]
                    or handoff.get("lv") != context["lv_id"]
                    or handoff.get("run_id") != context["run_id"]
                    or handoff.get("canonical_plan_sha256") != context["plan_sha256"]
                    or handoff.get("branch") != context["branch"]
                    or handoff.get("head") != current
                    or handoff.get("authorization", {}).get("id") != context["approval_event_id"]
                    or handoff.get("artifact_sha256") != worker.get("evidence_sha256")
                    or handoff.get("changed_files") != changed
                    or handoff.get("hard_stop") is not True
                    or handoff_event.get("evidence_sha256") != handoff.get("handoff_sha256")):
                continue
            if expected_outcome is not None:
                expected_evidence = expected_outcome.get("evidence")
                if (expected_outcome.get("status") != "SYSTEM_TRANSITION"
                        or expected_outcome.get("project_id") != context["project_id"]
                        or expected_outcome.get("gate_id") != context["gate_id"]
                        or expected_outcome.get("lv_id") != context["lv_id"]
                        or expected_outcome.get("run_id") != context["run_id"]
                        or expected_outcome.get("trace") != [
                            "PACKAGE", "PREFLIGHT", "WORKER", "REVIEW",
                            "CHECKPOINT", "EXIT", "HANDOFF", "SYSTEM_TRANSITION",
                        ]
                        or not isinstance(expected_evidence, Mapping)
                        or expected_evidence != {
                            "package": package["evidence_sha256"],
                            "preflight": preflight["evidence_sha256"],
                            "worker": worker["evidence_sha256"],
                            "review": review["evidence_sha256"],
                            "checkpoint": checkpoint["evidence_sha256"],
                            "exit": lv_exit["evidence_sha256"],
                            "handoff": handoff_event["evidence_sha256"],
                        }):
                    continue
            matches += 1
        return matches == 1
    except (OSError, UnicodeError, ValueError, TypeError, ResumeStoreError,
            json.JSONDecodeError, __import__("subprocess").SubprocessError):
        return False


def verify_production_transition_descendant(
    context: Mapping[str, Any], *, project_root: str | Path, harness_root: str | Path,
    predecessor: Mapping[str, Any] | None, approval_record_hash: str,
) -> bool:
    """Verify a completed predecessor LV SYSTEM_TRANSITION descendant.

    This is intentionally separate from same-run WORKER crash recovery: a
    predecessor transition may authorize a new run, but Git ancestry alone
    never establishes that authority.
    """
    if not isinstance(predecessor, Mapping) or predecessor.get("status") != "COMPLETE":
        return False
    required = ("project_id", "gate_id", "plan_sha256", "run_id", "lv_id", "branch")
    if any(not context.get(field) for field in required[:-1]):
        return False
    if predecessor.get("lv_id") != context.get("predecessor_lv") or predecessor.get("project_id", context.get("project_id")) != context.get("project_id"):
        return False
    order = context.get("canonical_lv_scope")
    if not isinstance(order, (list, tuple)) or context.get("predecessor_lv") not in order or context.get("lv_id") not in order:
        return False
    if order.index(context["predecessor_lv"]) + 1 != order.index(context["lv_id"]):
        return False
    root = Path(project_root)
    try:
        current = __import__("subprocess").run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, __import__("subprocess").SubprocessError):
        return False
    state_root = Path(harness_root) / "_workspace" / "global-gate" / str(context["project_id"]) / "state"
    for path in sorted(state_root.glob("*-active-transition.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or record.get("transition_type") != "SYSTEM_TRANSITION":
            continue
        unsigned = {key: value for key, value in record.items() if key != "record_hash"}
        if hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() != record.get("record_hash"):
            continue
        if (record.get("project_id") != context.get("project_id") or record.get("gate_id") != context.get("gate_id")
                or record.get("lv_id") != context.get("predecessor_lv") or record.get("plan_sha256") != context.get("plan_sha256")
                or record.get("branch") != context.get("branch") or record.get("baseline_head") != context.get("baseline_head")
                or record.get("approval_event_id") != context.get("approval_event_id")
                or record.get("current_head") != current or record.get("user_approval_renewal") is True):
            continue
        if predecessor.get("run_id") != record.get("run_id"):
            continue
        if predecessor.get("review_sha256") and not _SHA256.fullmatch(str(predecessor["review_sha256"])):
            continue
        if context.get("approval_record_hash") and context.get("approval_record_hash") != approval_record_hash:
            return False
        # The bridge has already verified the predecessor's sealed review and
        # worker lineage; require those immutable references to be present.
        if not predecessor.get("review_sha256") or not predecessor.get("worker_sha256"):
            continue
        return True
    # Historical production runs use the recovery-contract record/checkpoint
    # namespace rather than the newer active-transition projection.  Consume
    # that sealed lineage directly; never infer authority from Git ancestry.
    recovery_root = Path(harness_root) / "_workspace" / "global-gate" / str(context["project_id"]) / "recovery"
    for path in sorted(recovery_root.glob("*.json")):
        if path.is_symlink() or not path.is_file() or path.name.endswith(".checkpoint.json"):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            checkpoint_path = path.with_name(path.stem + ".checkpoint.json")
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        unsigned = {key: value for key, value in record.items() if key != "record_hash"}
        checkpoint_unsigned = {key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"}
        if (hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() != record.get("record_hash")
                or hashlib.sha256(json.dumps(checkpoint_unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() != checkpoint.get("checkpoint_sha256")):
            continue
        if (record.get("project_id") != context.get("project_id") or record.get("gate_id") != context.get("gate_id")
                or record.get("lv_id") != context.get("predecessor_lv") or record.get("run_id") != predecessor.get("run_id")
                or record.get("approval_event_id") != context.get("approval_event_id")
                or record.get("plan_sha256") != context.get("plan_sha256") or record.get("branch") != context.get("branch")
                or record.get("current_head") != current or checkpoint.get("hard_stop") is not True):
            continue
        if checkpoint.get("recovery_record_hash") != record.get("record_hash"):
            continue
        if not predecessor.get("review_sha256") or not predecessor.get("worker_sha256"):
            continue
        return True
    run_root = Path(harness_root) / "_workspace" / "orchestration-runs" / str(predecessor.get("run_id"))
    for worker_path in run_root.rglob("worker.result.json"):
        if worker_path.is_symlink() or not worker_path.is_file():
            continue
        try:
            worker = json.loads(worker_path.read_text(encoding="utf-8"))
            review = json.loads((worker_path.parent / "review.json").read_text(encoding="utf-8"))
            handoff = json.loads((worker_path.parent / "handoff.json").read_text(encoding="utf-8"))
            lv_exit = json.loads((worker_path.parent / "lv.exit.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (worker.get("schema_version") != "orchestration.product-completion-evidence.v1"
                or worker.get("status") not in {"completed", "COMPLETED", "PASS"}
                or worker.get("project_id") != context.get("project_id") or worker.get("gate_id") != context.get("gate_id")
                or worker.get("lv_id") != context.get("predecessor_lv") or worker.get("run_id") != predecessor.get("run_id")
                or worker.get("plan_sha256") != context.get("plan_sha256") or worker.get("checkpoint_commit") != current
                or review.get("verdict") != "PASS" or lv_exit.get("status") != "EXITED"
                or handoff.get("status") != "SEALED"):
            continue
        if predecessor.get("worker_sha256") and predecessor.get("worker_sha256") != hashlib.sha256(worker_path.read_bytes()).hexdigest():
            continue
        return True
    return False


def authorize_production_descendant(
    context: Mapping[str, Any], *, project_root: str | Path, harness_root: str | Path,
    predecessor: Mapping[str, Any] | None = None, approval_record_hash: str | None = None,
    freshness_stage: str = "UNKNOWN",
) -> dict[str, Any]:
    """Select exactly one verified production descendant authorization."""
    if freshness_stage not in _FRESHNESS_STAGES:
        freshness_stage = "UNKNOWN"
    required = ("project_id", "gate_id", "lv_id", "run_id", "baseline_head")
    missing = [field for field in required if not context.get(field)]
    if missing:
        raise GovernanceBranchError("production descendant context missing required field",
                                    branch_id="GOVERNANCE_PRECONDITION_CONTEXT", origin="PRECONDITION")
    try:
        result = validate_governance_descendant(project_root, str(context["baseline_head"]))
        result["approval_freshness_stage"] = freshness_stage
        result["approval_descendant_authorization"] = "BASELINE_EXACT"
        return result
    except ValueError:
        pass
    required_descendant = ("branch", "plan_sha256", "requirements_sha256",
                           "approval_event_id", "approval_record_hash", "canonical_lv_scope")
    missing = [field for field in required_descendant if not context.get(field)]
    if missing:
        raise GovernanceBranchError("production descendant context missing required field",
                                    branch_id="GOVERNANCE_PRECONDITION_DESCENDANT", origin="PRECONDITION")
    if context.get("predecessor_lv") and predecessor is not None and approval_record_hash:
        try:
            transition_verified = verify_production_transition_descendant(
                context, project_root=project_root, harness_root=harness_root,
                predecessor=predecessor, approval_record_hash=approval_record_hash,
            )
        except Exception as exc:
            if (not getattr(exc, "authorization_helper_id", None)
                    and not getattr(exc, "authorization_branch_id", None)
                    and not getattr(exc, "governance_branch_id", None)):
                exc.authorization_helper_id = "VERIFY_PRODUCTION_TRANSITION_DESCENDANT"
                if (not getattr(exc, "authorization_reason_origin", None)
                        and not getattr(exc, "governance_reason_origin", None)):
                    exc.authorization_reason_origin = "VALIDATOR"
            raise
        if transition_verified:
            return {"baseline_head": context["baseline_head"],
                    "current_head": context.get("current_head"),
                    "changed_files": [], "governance_only": False,
                    "transition_descendant": True,
                    "approval_freshness_stage": freshness_stage,
                    "approval_descendant_authorization": "SYSTEM_TRANSITION"}
    if context.get("predecessor_lv") and isinstance(predecessor, Mapping):
        predecessor_context = dict(context)
        predecessor_context["lv_id"] = context["predecessor_lv"]
        try:
            same_run_predecessor = verify_same_run_governed_descendant(
                predecessor_context, project_root=project_root, harness_root=harness_root,
                expected_outcome=predecessor,
            )
        except Exception as exc:
            if (not getattr(exc, "authorization_helper_id", None)
                    and not getattr(exc, "authorization_branch_id", None)
                    and not getattr(exc, "governance_branch_id", None)):
                exc.authorization_helper_id = "VERIFY_SAME_RUN_GOVERNED_DESCENDANT"
                if (not getattr(exc, "authorization_reason_origin", None)
                        and not getattr(exc, "governance_reason_origin", None)):
                    exc.authorization_reason_origin = "VALIDATOR"
            raise
        if same_run_predecessor:
            return {"baseline_head": context["baseline_head"],
                    "current_head": context.get("current_head"),
                    "changed_files": [], "governance_only": False,
                    "same_run_governed_descendant": True,
                    "approval_freshness_stage": freshness_stage,
                    "approval_descendant_authorization": "SAME_RUN_GOVERNED"}
    try:
        same_run = verify_same_run_governed_descendant(
            context, project_root=project_root, harness_root=harness_root,
        )
    except Exception as exc:
        if (not getattr(exc, "authorization_helper_id", None)
                and not getattr(exc, "authorization_branch_id", None)
                and not getattr(exc, "governance_branch_id", None)):
            exc.authorization_helper_id = "VERIFY_SAME_RUN_GOVERNED_DESCENDANT"
            if (not getattr(exc, "authorization_reason_origin", None)
                    and not getattr(exc, "governance_reason_origin", None)):
                exc.authorization_reason_origin = "VALIDATOR"
        raise
    if same_run:
        return {"baseline_head": context["baseline_head"],
                "current_head": context.get("current_head"),
                "changed_files": [], "governance_only": False,
                "same_run_governed_descendant": True,
                "approval_freshness_stage": freshness_stage,
                "approval_descendant_authorization": "SAME_RUN_GOVERNED"}
    try:
        recovery_verified = verify_production_recovery_descendant(
            context, project_root=project_root, harness_root=harness_root,
        )
    except Exception as exc:
        if (not getattr(exc, "authorization_helper_id", None)
                and not getattr(exc, "authorization_branch_id", None)
                and not getattr(exc, "governance_branch_id", None)):
            exc.authorization_helper_id = "VERIFY_PRODUCTION_RECOVERY_DESCENDANT"
            if (not getattr(exc, "authorization_reason_origin", None)
                    and not getattr(exc, "governance_reason_origin", None)):
                exc.authorization_reason_origin = "VALIDATOR"
        raise
    if recovery_verified:
        return {"baseline_head": context["baseline_head"],
                "current_head": context.get("current_head"),
                "changed_files": [], "governance_only": False,
                "recovery_owned_descendant": True,
                "approval_freshness_stage": freshness_stage,
                "approval_descendant_authorization": "SAME_RUN_GOVERNED"}
    failure = ApprovalFreshnessError(
        "production approval is stale after product-code descendant changes",
        stage=freshness_stage,
    )
    failure.governance_branch_id = "GOVERNANCE_AUTHORIZATION_VALIDATION"
    failure.authorization_branch_id = "GOVERNANCE_AUTHORIZATION_VALIDATION"
    failure.governance_reason_origin = "VALIDATOR"
    failure.authorization_reason_origin = "VALIDATOR"
    raise failure


@dataclass(frozen=True)
class GateControllerAdapters:
    package: StageCallable
    preflight: StageCallable
    worker: StageCallable
    review: StageCallable
    remediation: StageCallable
    checkpoint: StageCallable
    exit: StageCallable
    handoff: StageCallable


_SUCCESS = {
    "PACKAGE": {"SEALED"},
    "PREFLIGHT": {"READY"},
    "WORKER": {"COMPLETED", "PASS"},
    "REVIEW": {"PASS", "FAIL"},
    "REMEDIATION": {"PASS"},
    "CHECKPOINT": {"CHECKPOINTED", "PASS"},
    "EXIT": {"EXITED", "PASS"},
    "HANDOFF": {"SEALED", "PASS"},
}


def _validated_result(stage: str, value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GateControllerError(f"{stage} did not return a result mapping")
    result = dict(value)
    if not is_completion_eligible(result):
        raise GateControllerError(f"{stage} returned completion-ineligible evidence")
    status = result.get("status")
    exit_code = result.get("exit_code")
    evidence = result.get("evidence_sha256")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise GateControllerError(f"{stage} did not return an integer exit code")
    if exit_code != 0:
        raise GateControllerError(f"{stage} failed with exit code {exit_code}")
    if status not in _SUCCESS[stage]:
        raise GateControllerError(f"{stage} returned invalid status {status!r}")
    if not isinstance(evidence, str) or not _SHA256.fullmatch(evidence):
        raise GateControllerError(f"{stage} returned invalid evidence SHA-256")
    if result.get("hard_stop") is not True:
        raise GateControllerError(f"{stage} did not preserve the hard-stop boundary")
    return result


def gate_dry_run(context: Mapping[str, Any]) -> dict[str, Any]:
    """Describe the lifecycle without invoking any execution adapter."""
    required = ("project_id", "gate_id", "lv_id", "run_id", "plan_sha256")
    missing = [field for field in required if not context.get(field)]
    if missing:
        raise GateControllerError(f"dry-run context is missing: {', '.join(missing)}")
    return {
        "status": "DRY_RUN",
        "mutation_performed": False,
        "stages": [
            "PACKAGE", "PREFLIGHT", "WORKER", "REVIEW", "REMEDIATION",
            "CHECKPOINT", "EXIT", "HANDOFF", "SYSTEM_TRANSITION",
        ],
        "context": dict(context),
        "hard_stop": True,
    }


def run_gate_lifecycle(context: Mapping[str, Any], adapters: GateControllerAdapters) -> dict[str, Any]:
    """Run one LV through the real, injected lifecycle and derive its transition."""
    required = ("project_id", "gate_id", "lv_id", "run_id", "plan_sha256")
    missing = [field for field in required if not context.get(field)]
    if missing:
        raise GateControllerError(f"run context is missing: {', '.join(missing)}")
    if not _SHA256.fullmatch(str(context["plan_sha256"])):
        raise GateControllerError("run context has invalid plan SHA-256")

    dispatch_trace = context.get("issue065_dispatch_preinvoke")
    post_context_trace = context.get("issue065_post_context")
    state: dict[str, Any] = dict(context)
    def mark_dispatch(step: str, *, completed: bool = False, failure: str = "NONE",
                      exception_bucket: str = "NONE") -> None:
        if callable(dispatch_trace):
            dispatch_trace(step, completed=completed, failure=failure, exception_bucket=exception_bucket)
    def mark_post_context(edge: str, *, completed: bool = False, branch: str = "UNKNOWN",
                          exit_kind: str = "UNKNOWN", failure: str = "NONE",
                          failure_mode: str = "NONE") -> None:
        if callable(post_context_trace):
            post_context_trace(edge, completed=completed, branch=branch, exit_kind=exit_kind,
                               failure=failure, failure_mode=failure_mode)
    evidence: dict[str, str] = {}
    trace: list[str] = []

    def invoke(stage: str, adapter: StageCallable) -> dict[str, Any]:
        if stage == "PACKAGE":
            mark_dispatch("CALLABLE_RESOLUTION", completed=True)
        adapter_request = dict(state)
        adapter_request["prior_evidence"] = dict(evidence)
        lifecycle_binding = context.get("lifecycle_binding")
        if stage == "PACKAGE":
            mark_post_context("LIFECYCLE_BINDING_CONDITION")
        kind = {"PACKAGE":"package", "PREFLIGHT":"preflight", "WORKER":"worker_result",
                "REVIEW":"review", "REMEDIATION":"recovery_successor", "CHECKPOINT":"checkpoint",
                "EXIT":"lv_exit", "HANDOFF":"handoff"}[stage]
        if lifecycle_binding is not None:
            if stage == "PACKAGE":
                mark_post_context("LIFECYCLE_BINDING_CONDITION", completed=True, branch="TRUE",
                                  exit_kind="TO_LIFECYCLE_SEAL")
                mark_dispatch("CONTEXT_EXTRACTION", completed=True)
                mark_dispatch("LIFECYCLE_SEAL")
                mark_post_context("LIFECYCLE_SEAL_PRODUCE_CONSUME", exit_kind="TO_ARTIFACT_PUBLISH")
            try:
                lifecycle_request = _canonical_lifecycle_payload(state, evidence)
                sealed_request = produce_lifecycle("worker_request" if stage == "WORKER" else kind,
                                                   lifecycle_request, lifecycle_binding)
                consume_lifecycle("worker_request" if stage == "WORKER" else kind,
                                  sealed_request, lifecycle_binding)
            except Exception as exc:
                if stage == "PACKAGE":
                    mark_post_context("LIFECYCLE_SEAL_PRODUCE_CONSUME", failure="LIFECYCLE_SEAL_PRODUCE_CONSUME",
                                      failure_mode="RAISED", branch="RETURN", exit_kind="BLOCK_RETURN")
                    bucket = "TYPE" if isinstance(exc, TypeError) else ("KEY" if isinstance(exc, KeyError)
                             else ("VALUE" if isinstance(exc, ValueError) else "OTHER"))
                    mark_dispatch("LIFECYCLE_SEAL", failure="LIFECYCLE_SEAL", exception_bucket=bucket)
                raise
            if stage == "PACKAGE":
                mark_dispatch("LIFECYCLE_SEAL", completed=True)
                mark_post_context("LIFECYCLE_SEAL_PRODUCE_CONSUME", completed=True, branch="CONTINUE",
                                  exit_kind="TO_ARTIFACT_PUBLISH")
        artifact_root=context.get("lifecycle_artifact_root")
        if lifecycle_binding is not None and artifact_root:
            if stage == "PACKAGE":
                mark_post_context("ARTIFACT_PUBLISH_CONDITION")
            source=str(context["lifecycle_source_sha256"]); predecessor=str(context["lifecycle_predecessor"])
            rel=f"{len(trace):02d}-{kind}.request.json"; request_kind="worker_request" if stage=="WORKER" else kind
            try:
                publish_persisted(artifact_root,rel,kind=request_kind,payload=lifecycle_request,binding=lifecycle_binding,source_artifact_sha256=source,predecessor_digest=predecessor)
                persisted_request = dict(validate_persisted(artifact_root,rel,expected_kind=request_kind,expected_binding=lifecycle_binding,expected_source_sha256=source,expected_predecessor=predecessor).payload)
                if canonical_bytes(persisted_request) != canonical_bytes(lifecycle_request):
                    raise ProductionLifecycleError("persisted lifecycle payload mismatch")
            except Exception as exc:
                if stage == "PACKAGE":
                    mark_post_context("ARTIFACT_PUBLISH_CONDITION", failure="ARTIFACT_PUBLISH_CONDITION",
                                      failure_mode="RAISED", branch="RETURN", exit_kind="BLOCK_RETURN")
                    bucket = "TYPE" if isinstance(exc, TypeError) else ("KEY" if isinstance(exc, KeyError)
                             else ("VALUE" if isinstance(exc, ValueError) else "OTHER"))
                    mark_dispatch("ARTIFACT_PUBLISH", failure="ARTIFACT_PUBLISH", exception_bucket=bucket)
                raise
            if stage == "PACKAGE":
                mark_dispatch("ARTIFACT_PUBLISH", completed=True)
                mark_post_context("ARTIFACT_PUBLISH_CONDITION", completed=True, branch="CONTINUE",
                                  exit_kind="TO_INVOCATION")
        if stage == "PACKAGE":
            mark_post_context("PACKAGE_INVOCATION_GATE")
            mark_dispatch("INVOCATION", completed=True)
            mark_post_context("PACKAGE_INVOCATION_GATE", completed=True, branch="TRUE",
                              exit_kind="TO_INVOCATION")
        result = _validated_result(stage, adapter(adapter_request))
        if lifecycle_binding is not None:
            sealed_result = produce_lifecycle(kind, result, lifecycle_binding)
            consume_lifecycle(kind, sealed_result, lifecycle_binding)
        if lifecycle_binding is not None and artifact_root:
            rel=f"{len(trace):02d}-{kind}.result.json"
            publish_persisted(artifact_root,rel,kind=kind,payload=result,binding=lifecycle_binding,source_artifact_sha256=source,predecessor_digest=predecessor)
            result=_validated_result(stage,validate_persisted(artifact_root,rel,expected_kind=kind,expected_binding=lifecycle_binding,expected_source_sha256=source,expected_predecessor=predecessor).payload)
        evidence[stage.lower()] = result["evidence_sha256"]
        trace.append(stage)
        state["last_stage"] = stage
        state["last_status"] = result["status"]
        # Keep the complete sealed stage result in the in-process lifecycle
        # state so downstream HANDOFF adapters can bind prerequisite evidence
        # before sealing their artifact.  This does not add a lifecycle stage.
        state[f"{stage.lower()}_result"] = result
        return result

    invoke("PACKAGE", adapters.package)
    invoke("PREFLIGHT", adapters.preflight)
    invoke("WORKER", adapters.worker)
    review = invoke("REVIEW", adapters.review)
    restored_verdicts = review.get("verdict_history")
    review_verdicts = list(restored_verdicts) if isinstance(restored_verdicts, list) and restored_verdicts else [review["status"]]
    remediated = False
    remediation_verdict = review.get("remediation_verdict")
    if remediation_verdict is not None:
        remediated = True
    if review["status"] == "FAIL":
        remediation = invoke("REMEDIATION", adapters.remediation)
        remediation_verdict = remediation["status"]
        remediated = True
        state["review_attempt"] = 2
        review = invoke("REVIEW", adapters.review)
        review_verdicts.append(review["status"])
        if review["status"] != "PASS":
            raise GateControllerError(f"independent review did not pass after remediation: {review}")
    invoke("CHECKPOINT", adapters.checkpoint)
    invoke("EXIT", adapters.exit)
    handoff = invoke("HANDOFF", adapters.handoff)
    trace.append("SYSTEM_TRANSITION")
    return {
        "status": "SYSTEM_TRANSITION",
        "event_type": "SYSTEM_TRANSITION",
        "user_approval_renewal": False,
        "project_id": context["project_id"],
        "gate_id": context["gate_id"],
        "lv_id": context["lv_id"],
        "run_id": context["run_id"],
        "plan_sha256": context["plan_sha256"],
        "trace": trace,
        "evidence": evidence,
        "remediated": remediated,
        "review_verdicts": review_verdicts,
        "remediation_verdict": remediation_verdict,
        "handoff": handoff,
        "hard_stop": True,
    }


def run_production_gate_lifecycle(
    context: Mapping[str, Any], adapters: GateControllerAdapters, *, approval_events: list[Mapping[str, Any]],
    project_root: str, canonical_state: Mapping[str, Any], completion_conditions_sha256: str,
    historical_predecessor: str | None = None, historical_event_ids: tuple[str, ...] = (),
    harness_root: str | None = None,
) -> dict[str, Any]:
    """Production boundary: v2 authorization, Git descendant, state, then lifecycle."""
    preentry = context.get("issue065_package_preentry")
    auth_trace = context.get("issue065_auth_validation")
    lifecycle_trace = context.get("issue065_lifecycle")
    active_auth_check = "UNKNOWN"
    def mark_preentry(step: str, *, failure: str | None = None, exception_bucket: str | None = None,
                      completed: bool = True) -> None:
        if callable(preentry):
            preentry(step, failure=failure, exception_bucket=exception_bucket, completed=completed)
    def mark_auth(check: str, *, completed: bool = False, failure_mode: str = "NONE") -> None:
        nonlocal active_auth_check
        active_auth_check = check
        if callable(auth_trace):
            auth_trace(check, completed=completed, failure_mode=failure_mode)
    def mark_lifecycle(stage: str, *, completed: bool = False, failure_mode: str = "NONE",
                       check_id: str = "NONE", reason_presence: str = "UNKNOWN") -> None:
        if callable(lifecycle_trace):
            lifecycle_trace(stage, completed=completed, failure_mode=failure_mode,
                            check_id=check_id, reason_presence=reason_presence)
    mark_preentry("LIFECYCLE_ENTRY")
    required = ("project_id", "gate_id", "plan_sha256", "branch", "baseline_head", "approval_mode", "canonical_lv_scope", "owned_file_scope", "phase")
    mark_auth("REQUIRED_CONTEXT_FIELDS")
    missing = [field for field in required if not context.get(field)]
    if missing:
        mark_auth("REQUIRED_CONTEXT_FIELDS", failure_mode="MISSING")
        raise GateControllerError(f"production context is missing: {', '.join(missing)}")
    mark_auth("REQUIRED_CONTEXT_FIELDS", completed=True)
    try:
        mark_auth("APPROVAL_AUTHORIZATION")
        approval = evaluate_production_authorization(
            approval_events,
            ApprovalBindings(
                project_id=str(context["project_id"]), gate_id=str(context["gate_id"]),
                plan_sha256=str(context["plan_sha256"]), branch=str(context["branch"]),
                baseline_head=str(context["baseline_head"]), approval_mode=str(context["approval_mode"]),
                canonical_lv_scope=tuple(context["canonical_lv_scope"]),
                owned_file_scope={key: tuple(value) for key, value in context["owned_file_scope"].items()},
                completion_conditions_sha256=completion_conditions_sha256,
            ),
            historical_predecessor=historical_predecessor,
            historical_event_ids=historical_event_ids,
        )
        mark_auth("APPROVAL_AUTHORIZATION", completed=True)
        mark_auth("DESCENDANT_AUTHORIZATION")
        descendant_authorization = authorize_production_descendant(
            context, project_root=project_root, harness_root=harness_root or "",
            predecessor=context.get("predecessor_evidence"),
            approval_record_hash=str(approval["record_hash"]),
            freshness_stage=str(context.get("approval_freshness_stage", "PRE_RUN")),
        )
        mark_auth("DESCENDANT_AUTHORIZATION", completed=True)
        mark_preentry("AUTHORIZATION_VALIDATION")
        if not descendant_authorization.get("governance_only", False):
            import subprocess
            changed = subprocess.run(
                ["git", "-C", str(project_root), "diff", "--name-only",
                 f"{context['baseline_head']}..HEAD"], capture_output=True, text=True, check=True,
            ).stdout.splitlines()
            owned = {path for paths in context["owned_file_scope"].values() for path in paths}
            governance = ("AGENTS.md", "docs/", "runtime/orchestrator/", ".agents/", ".codex/")
            mark_auth("DESCENDANT_SCOPE_GUARD")
            if not changed or any(path not in owned and not any(path == p or path.startswith(p) for p in governance)
                                   for path in changed):
                mark_auth("DESCENDANT_SCOPE_GUARD", failure_mode="BLOCK")
                raise ValueError("production descendant contains outside-scope changes")
            mark_auth("DESCENDANT_SCOPE_GUARD", completed=True)
        else:
            mark_auth("DESCENDANT_SCOPE_GUARD", completed=True)
        mark_auth("CANONICAL_GATE_STATE_VALIDATION")
        validate_canonical_gate_state(
            canonical_state, project_id=str(context["project_id"]), gate_id=str(context["gate_id"]),
            phase=str(context["phase"]), plan_sha256=str(context["plan_sha256"]),
            approval_record_hash=str(approval["record_hash"]),
        )
        mark_auth("CANONICAL_GATE_STATE_VALIDATION", completed=True)
    except Exception as exc:
        bucket = "TYPE" if isinstance(exc, TypeError) else ("KEY" if isinstance(exc, KeyError) else
                 ("VALUE" if isinstance(exc, ValueError) else ("ATTRIBUTE" if isinstance(exc, AttributeError) else "OTHER")))
        mark_preentry("AUTHORIZATION_VALIDATION", failure="AUTHORIZATION_VALIDATION",
                      exception_bucket=bucket, completed=False)
        mark_auth(active_auth_check, failure_mode="RAISED")
        wrapped = GateControllerError(str(exc))
        wrapped.approval_reason_code = _bounded_authorization_reason(exc)
        if hasattr(exc, "governance_branch_id"):
            wrapped.governance_branch_id = exc.governance_branch_id
            wrapped.governance_reason_origin = exc.governance_reason_origin
            wrapped.authorization_branch_id = exc.governance_branch_id
            wrapped.authorization_reason_origin = exc.governance_reason_origin
        if hasattr(exc, "authorization_helper_id"):
            wrapped.authorization_helper_id = exc.authorization_helper_id
            wrapped.authorization_reason_origin = getattr(
                exc, "authorization_reason_origin", "UNKNOWN")
        if isinstance(exc, ApprovalFreshnessError):
            wrapped.approval_freshness_stage = exc.approval_freshness_stage
            wrapped.approval_descendant_authorization = exc.approval_descendant_authorization
        raise wrapped from exc
    if harness_root is not None:
        from .active_transition import activate_canonical_lv_transition
        mark_lifecycle("TRANSITION_ACTIVATION")
        try:
            transition = activate_canonical_lv_transition(
                harness_root, project_id=str(context["project_id"]), gate_id=str(context["gate_id"]),
                lv_id=str(context["lv_id"]), run_id=str(context["run_id"]), approval_event_id=str(approval["event_id"]),
                plan_sha256=str(context["plan_sha256"]), branch=str(context["branch"]),
                baseline_head=str(context["baseline_head"]), current_head=str(context.get("current_head", "")),
                predecessor_digest=str(context.get("predecessor_completion_digest", "")),
                owned_files=list(context["owned_file_scope"][context["lv_id"]]),
                completion_conditions=list(context.get("completion_conditions", [])),
            )
        except Exception:
            mark_lifecycle("TRANSITION_ACTIVATION", failure_mode="RAISED",
                           check_id="TRANSITION_ACTIVATION", reason_presence="UNKNOWN")
            raise
        mark_lifecycle("TRANSITION_ACTIVATION", completed=True)
        context = dict(context)
        context["canonical_state_override"] = {
            "state": "GATE1_ACTIVE", "gate_id": str(context["gate_id"]), "active_scope": [str(context["lv_id"])],
            "selected_source": str(__import__("pathlib").Path(project_root).resolve() / "IMPLEMENTATION_PLAN.md"),
            "canonical_plan": "IMPLEMENTATION_PLAN.md", "plan_sha256": str(context["plan_sha256"]),
            "approval_id": approval["event_id"], "approval_record_hash": approval["record_hash"],
            "checkpoint_commit": transition["current_head"], "owned_files": list(context["owned_file_scope"][context["lv_id"]]),
            "ledger_path": "docs/GATE_STATE.md", "transition": transition,
        }
        mark_preentry("TRANSITION_ACTIVATION")
    context = dict(context)
    mark_lifecycle("LIFECYCLE_BINDING")
    if "lifecycle_binding" not in context:
        digest_sources = {
            field: {"field": field, "context": context.get(field.removesuffix("_sha256")),
                    "project_id": context["project_id"], "gate_id": context["gate_id"],
                    "lv_id": context["lv_id"], "run_id": context["run_id"]}
            for field in DIGEST_FIELDS
        }
        context["lifecycle_binding"] = build_binding_from_sources(
            digest_sources, project_id=str(context["project_id"]), gate_id=str(context["gate_id"]),
            lv_id=str(context["lv_id"]), run_id=str(context["run_id"]),
            attempt=int(context.get("attempt", 1)), recovery_id=str(context.get("recovery_id", "none")),
            approval_event_id=str(approval["event_id"]), branch=str(context["branch"]),
            baseline_head=str(context["baseline_head"]), current_head=str(context.get("current_head") or context["baseline_head"]),
            hard_stop=True,
        )
    mark_lifecycle("LIFECYCLE_BINDING", completed=True)
    mark_preentry("LIFECYCLE_BINDING")
    if harness_root is not None:
        context["lifecycle_artifact_root"] = str(__import__("pathlib").Path(harness_root)/"_workspace"/"production-lifecycle"/str(context["run_id"]))
        context["lifecycle_source_sha256"] = str(context["plan_sha256"])
        context["lifecycle_predecessor"] = str(context.get("predecessor_completion_digest") or "0"*64)
    mark_preentry("DISPATCH_READY")
    mark_lifecycle("DISPATCH_READY")
    mark_lifecycle("DISPATCH_READY", completed=True)
    outcome = run_gate_lifecycle(context, adapters)
    outcome["production_approval_schema"] = approval["schema_version"]
    outcome["production_approval_record_hash"] = approval["record_hash"]
    outcome["approval_freshness_stage"] = descendant_authorization["approval_freshness_stage"]
    outcome["approval_descendant_authorization"] = descendant_authorization["approval_descendant_authorization"]
    return outcome
