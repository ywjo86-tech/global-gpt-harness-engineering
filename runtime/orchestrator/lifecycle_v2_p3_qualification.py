"""Bounded P3 validation execution and read-only P4 entry."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_PLAN = "docs/harness/P3_CANARY_VALIDATE_FULL_PLAN.md"
_SPEC = "docs/harness/P3_CANARY_VALIDATE_SPEC.md"
_PLAN_SHA = "4720c963563b8f5488df73a623a5e5d2dc2a798b0c3dbb932bcbc235373acd22"
_SPEC_SHA = "b581bc9a2ecb92052b4e9edfb2cd5f3d2f2f75661ebd1dbefb47b652a9f8b7f1"
_EXECUTE_SPEC = "docs/harness/P3_CANARY_EXECUTE_SPEC.md"
_EXECUTE_SPEC_SHA = "925e3a7c845cc74b6599241f544c31ec49dbef4cba3d678b5687018f9bcc9de0"
_P4_SPEC = "docs/harness/P4_READ_ONLY_ENTRY_SPEC.md"
_P4_SPEC_SHA = "acd1b0be3f3df553ed93314933cc5de5e546bbb8ffeca01a5999352ca6671269"
_TESTS = (
    "tests.test_lifecycle_v2_p3_promotion_admission",
    "tests.test_ocpv2_successor_stage_runtime_p3_wiring",
    "tests.test_p3_canary_validate_registration",
    "tests.test_p3_canary_validate_registration_request",
    "tests.test_p3_canary_validate_evidence_issue_request",
)


class LifecycleV2P3QualificationError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value) or ".." in value:
        raise LifecycleV2P3QualificationError(f"invalid {label}")
    return value


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.parent.resolve() != path.parent:
        raise LifecycleV2P3QualificationError("unsafe receipt root")
    payload = _canonical(value)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LifecycleV2P3QualificationError("receipt conflict")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _load_registration(state_root: Path, admission_digest: str) -> dict[str, Any]:
    path = state_root / "p3-canary-validate-registrations" / f"{admission_digest}.json"
    if path.is_symlink() or not path.is_file():
        raise LifecycleV2P3QualificationError("validation registration required")
    value = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != _canonical(value):
        raise LifecycleV2P3QualificationError("noncanonical validation registration")
    forbidden = (
        "runtime_current_switch_authorized", "predecessor_shutdown_authorized",
        "existing_run_migration_authorized", "successor_polling_authorized", "execution_authorized",
    )
    if value.get("status") != "P3_CANARY_VALIDATE_REGISTERED" or any(value.get(k) is not False for k in forbidden):
        raise LifecycleV2P3QualificationError("validation authority widened")
    unsigned = {k: v for k, v in value.items() if k != "registration_digest"}
    if value.get("registration_digest") != _digest(unsigned):
        raise LifecycleV2P3QualificationError("registration digest mismatch")
    return value


def execute_p3_canary_and_qualify(*, state_root: str | Path, project_root: str | Path,
                                  project_alias: str, candidate_run_id: str,
                                  admission_digest: str, expected_branch: str,
                                  expected_head: str, approval_ref: str,
                                  runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> dict[str, Any]:
    state = Path(state_root).absolute()
    project = Path(project_root).absolute()
    for path, label in ((state, "state root"), (project, "project root")):
        if path.is_symlink() or not path.is_dir() or path.resolve() != path:
            raise LifecycleV2P3QualificationError(f"unsafe {label}")
    _safe(project_alias, _SAFE, "project alias"); _safe(candidate_run_id, _SAFE, "candidate")
    _safe(admission_digest, _SHA256, "admission digest"); _safe(expected_head, _SHA1, "head")
    _safe(approval_ref, _SAFE, "approval ref")
    registration = _load_registration(state, admission_digest)
    if (registration.get("project_alias"), registration.get("candidate_run_id"), registration.get("admission_digest")) != (project_alias, candidate_run_id, admission_digest):
        raise LifecycleV2P3QualificationError("registration lineage mismatch")
    branch = subprocess.run(["git", "-C", str(project), "branch", "--show-current"], capture_output=True, text=True, timeout=10)
    head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
    if branch.returncode or head.returncode or (branch.stdout.strip(), head.stdout.strip()) != (expected_branch, expected_head):
        raise LifecycleV2P3QualificationError("source identity mismatch")
    if any((_file_sha(project / path) != digest) for path, digest in (
        (_PLAN, _PLAN_SHA), (_SPEC, _SPEC_SHA), (_EXECUTE_SPEC, _EXECUTE_SPEC_SHA), (_P4_SPEC, _P4_SPEC_SHA),
    )):
        raise LifecycleV2P3QualificationError("P3 authority digest mismatch")
    command: Sequence[str] = ("python3", "-m", "unittest", "-q", *_TESTS)
    completed = runner(command, cwd=project, capture_output=True, text=True, timeout=300)
    if completed.returncode:
        raise LifecycleV2P3QualificationError("bounded canary failed")
    result_unsigned = {
        "schema_version": "orchestration.lifecycle-v2-p3-bounded-canary-result.v1",
        "project_alias": project_alias, "candidate_run_id": candidate_run_id,
        "admission_digest": admission_digest, "registration_digest": registration["registration_digest"],
        "expected_branch": expected_branch, "expected_head": expected_head,
        "approval_ref": approval_ref, "test_modules": list(_TESTS), "test_exit_code": 0,
        "runtime_current_switch_performed": False, "predecessor_shutdown_performed": False,
        "existing_run_migration_performed": False, "successor_polling_enabled": False,
        "service_manager_invoked": False, "generic_mutation_performed": False,
        "status": "P3_BOUNDED_CANARY_PASSED",
    }
    result = {**result_unsigned, "result_digest": _digest(result_unsigned)}
    _write_once(state / "p3-bounded-canary-results" / f"{admission_digest}.json", result)
    qualification_unsigned = {
        "schema_version": "orchestration.lifecycle-v2-p3-final-qualification.v1",
        "project_alias": project_alias, "candidate_run_id": candidate_run_id,
        "admission_digest": admission_digest, "registration_digest": registration["registration_digest"],
        "canary_result_digest": result["result_digest"], "expected_branch": expected_branch,
        "expected_head": expected_head, "status": "P3_FINAL_QUALIFIED",
        "p4_entry_authorized": True, "runtime_current_switch_authorized": False,
        "predecessor_shutdown_authorized": False, "existing_run_migration_authorized": False,
        "successor_polling_authorized": False, "generic_mutation_authorized": False,
    }
    qualification = {**qualification_unsigned, "qualification_digest": _digest(qualification_unsigned)}
    _write_once(state / "p3-final-qualifications" / f"{admission_digest}.json", qualification)
    return qualification


def enter_p4_read_only(*, state_root: str | Path, admission_digest: str,
                       qualification_digest: str, approval_ref: str) -> dict[str, Any]:
    state = Path(state_root).absolute()
    if state.is_symlink() or not state.is_dir() or state.resolve() != state:
        raise LifecycleV2P3QualificationError("unsafe state root")
    _safe(admission_digest, _SHA256, "admission digest"); _safe(qualification_digest, _SHA256, "qualification digest")
    _safe(approval_ref, _SAFE, "approval ref")
    path = state / "p3-final-qualifications" / f"{admission_digest}.json"
    if path.is_symlink() or not path.is_file():
        raise LifecycleV2P3QualificationError("P3 qualification required")
    qualification = json.loads(path.read_text(encoding="utf-8"))
    unsigned_qualification = {k: v for k, v in qualification.items() if k != "qualification_digest"}
    forbidden = ("runtime_current_switch_authorized", "predecessor_shutdown_authorized", "existing_run_migration_authorized", "successor_polling_authorized", "generic_mutation_authorized")
    if path.read_bytes() != _canonical(qualification) or qualification.get("status") != "P3_FINAL_QUALIFIED" or qualification.get("qualification_digest") != qualification_digest or qualification_digest != _digest(unsigned_qualification) or qualification.get("p4_entry_authorized") is not True or any(qualification.get(k) is not False for k in forbidden):
        raise LifecycleV2P3QualificationError("P3 qualification mismatch")
    unsigned = {
        "schema_version": "orchestration.lifecycle-v2-p4-read-only-entry.v1",
        "project_alias": qualification["project_alias"], "candidate_run_id": qualification["candidate_run_id"],
        "admission_digest": admission_digest, "qualification_digest": qualification_digest,
        "expected_branch": qualification["expected_branch"], "expected_head": qualification["expected_head"],
        "approval_ref": approval_ref, "status": "P4_READ_ONLY_ENTERED",
        "runtime_current_switch_authorized": False, "predecessor_shutdown_authorized": False,
        "existing_run_migration_authorized": False, "successor_polling_authorized": False,
        "generic_mutation_authorized": False, "service_manager_invoked": False,
    }
    receipt = {**unsigned, "entry_digest": _digest(unsigned)}
    _write_once(state / "p4-read-only-entries" / f"{admission_digest}.json", receipt)
    return receipt
