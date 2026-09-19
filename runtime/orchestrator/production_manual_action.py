"""GPT-operator authorized bounded mutation path for production Full Plan.

This is deliberately not a provider. It can run only after the governed Router
has returned ACTION_PROVIDER_BLOCKED and only for a digest-bound patch, scope,
commands, task execution identity and GPT_OPERATOR authorization.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .git_provenance import GitProvenanceError, touched_paths_between
from .lv_execution_package import canonical_json_bytes
from .operator_control import ManualActionAuthorizationV1, OperatorDirectiveV1
from .schemas import TaskSlice, WorkerRequest
from .provider_router import (
    ProviderEligibilitySnapshotV1, RouterRequestV2, RouterDecisionV2,
    ELIGIBILITY_SCHEMA_V1, route_request,
)

ACTION_SCHEMA = "orchestration.production-manual-action.v1"
EXECUTOR_ID = "gpt-operator-manual-action"
EXECUTOR_VERSION = "1"
COMPLETION_MODE = "GPT_OPERATOR_MANUAL_ACTION"
_VALIDATION_KEYS = ("focused_test", "full_regression", "compile_import", "git_diff_check")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class ProductionManualActionError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def editable_scope_digest(paths: Sequence[str]) -> str:
    return _digest(list(paths))


def command_plan_digest(commands: Mapping[str, Sequence[str]]) -> str:
    return _digest({key: list(commands[key]) for key in _VALIDATION_KEYS})


def _within(path: str, scopes: Sequence[str]) -> bool:
    return any(path == scope.rstrip("/") or (scope.endswith("/") and path.startswith(scope)) for scope in scopes)


def _safe_paths(values: object, *, label: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ProductionManualActionError(f"{label} is missing")
    out: list[str] = []
    for raw in values:
        if not isinstance(raw, str) or not raw or "\\" in raw:
            raise ProductionManualActionError(f"{label} is unsafe")
        directory = raw.endswith("/")
        normalized = raw.rstrip("/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != normalized:
            raise ProductionManualActionError(f"{label} is unsafe")
        out.append(normalized + ("/" if directory else ""))
    if len(out) != len(set(out)):
        raise ProductionManualActionError(f"{label} contains duplicates")
    return out


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=False, timeout=120)


def _git_text(root: Path, *args: str) -> str:
    cp = _git(root, *args)
    if cp.returncode != 0:
        raise ProductionManualActionError("manual action Git verification failed")
    return cp.stdout.decode("utf-8", errors="strict").strip()


def _assert_safe_descendant_source(root: Path, *, sealed_head: str, current_head: str,
                                   owned_files: Sequence[str]) -> bool:
    """Allow a sealed manual action on a clean descendant only when its owned scope is untouched."""
    if current_head == sealed_head:
        return False
    if not _GIT_OID.fullmatch(sealed_head) or not _GIT_OID.fullmatch(current_head):
        raise ProductionManualActionError("manual action source identity drift")
    ancestor = _git(root, "merge-base", "--is-ancestor", sealed_head, current_head)
    if ancestor.returncode != 0:
        raise ProductionManualActionError("manual action source is not a safe descendant")
    try:
        changed = touched_paths_between(root, sealed_head, current_head)
    except GitProvenanceError as exc:
        raise ProductionManualActionError("manual action source is not a safe descendant") from exc
    if any(_within(path, owned_files) for path in changed):
        raise ProductionManualActionError("manual action safe descendant historically changed owned scope")
    return True


def _command(root: Path, argv: Sequence[str], *, timeout: int = 180) -> dict[str, Any]:
    if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)) or not argv:
        raise ProductionManualActionError("manual action command is invalid")
    command = [str(part) for part in argv]
    if any(not part or "\x00" in part for part in command):
        raise ProductionManualActionError("manual action command is invalid")
    executable = PurePosixPath(command[0]).name
    if executable not in {"python", "python3", "git"}:
        raise ProductionManualActionError("manual action command executable is not approved")
    if executable in {"python", "python3"}:
        allowed = command[1:3] in (["-m", "unittest"], ["-m", "compileall"])
        if not allowed:
            raise ProductionManualActionError("manual action Python command is not approved")
    if executable == "git" and command[1:3] != ["diff", "--check"]:
        raise ProductionManualActionError("manual action Git command is not approved")
    try:
        cp = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            check=False, timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        cp = None
        timed_out = True
        stdout = exc.stdout or b""; stderr = exc.stderr or b""
    else:
        stdout = cp.stdout; stderr = cp.stderr
    return {"command": command, "exit_code": None if timed_out else cp.returncode,
            "timeout": timed_out, "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest()}


def _validate_router(action: Mapping[str, Any]) -> tuple[OperatorDirectiveV1, RouterRequestV2, RouterDecisionV2]:
    directive = OperatorDirectiveV1.from_mapping(action.get("operator_directive", {}))
    if directive.current_stage != "PREPARE" or directive.requested_next_stage != "ACTION" or not directive.state_change_required:
        raise ProductionManualActionError("manual action requires PREPARE to ACTION GPT directive")
    raw_request = action.get("router_request")
    if not isinstance(raw_request, Mapping) or not isinstance(raw_request.get("eligibility_snapshot"), Mapping):
        raise ProductionManualActionError("manual action Router request is missing")
    snap_raw = raw_request["eligibility_snapshot"]
    snapshot = ProviderEligibilitySnapshotV1(
        schema_version=str(snap_raw.get("schema_version", "")), snapshot_id=str(snap_raw.get("snapshot_id", "")),
        provider_eligible=dict(snap_raw.get("provider_eligible", {})), model_refs=dict(snap_raw.get("model_refs", {})),
        evidence_refs=tuple(snap_raw.get("evidence_refs", ())), failure_classes=dict(snap_raw.get("failure_classes", {})),
    )
    request = RouterRequestV2(
        schema_version=str(raw_request.get("schema_version", "")), request_id=str(raw_request.get("request_id", "")),
        project_id=str(raw_request.get("project_id", "")), run_id=str(raw_request.get("run_id", "")),
        task_id=str(raw_request.get("task_id", "")), task_execution_id=str(raw_request.get("task_execution_id", "")),
        directive_digest=str(raw_request.get("directive_digest", "")), stage=str(raw_request.get("stage", "")),
        required_capabilities=tuple(raw_request.get("required_capabilities", ())),
        state_change_required=bool(raw_request.get("state_change_required")), policy_profile=str(raw_request.get("policy_profile", "")),
        eligibility_snapshot=snapshot, eligibility_snapshot_ref=str(raw_request.get("eligibility_snapshot_ref", "")),
        eligibility_snapshot_digest=str(raw_request.get("eligibility_snapshot_digest", "")),
        request_source=str(raw_request.get("request_source", "governed_v2")), failure_class=str(raw_request.get("failure_class", "")),
        failover_request_ref=str(raw_request.get("failover_request_ref", "")),
    )
    if request.directive_digest != directive.directive_digest:
        raise ProductionManualActionError("manual action Router/directive binding mismatch")
    expected = route_request(request)
    supplied = action.get("router_decision")
    if not isinstance(supplied, Mapping) or supplied != expected.to_dict():
        raise ProductionManualActionError("manual action Router decision is not canonical")
    if expected.eligible or expected.stage != "ACTION" or expected.action_state != "ACTION_PROVIDER_BLOCKED" or expected.provider_ref or expected.model_ref:
        raise ProductionManualActionError("manual action requires ACTION_PROVIDER_BLOCKED")
    return directive, request, expected


def validate_action_package(action: Mapping[str, Any], authorization: Mapping[str, Any], manifest: Mapping[str, Any]) -> tuple[ManualActionAuthorizationV1, RouterDecisionV2]:
    required = {"schema_version", "project_id", "run_id", "gate_id", "lv_id", "task_execution_id",
                "plan_sha256", "source_head", "owned_files", "expected_changed_files", "prepared_artifact_digest",
                "patch", "patch_sha256", "validation_ids", "validation_commands", "commit_subject",
                "operator_directive", "router_request", "router_decision", "action_package_digest"}
    if not isinstance(action, Mapping) or set(action) != required or action.get("schema_version") != ACTION_SCHEMA:
        raise ProductionManualActionError("manual action package schema mismatch")
    unsigned = {key: value for key, value in action.items() if key != "action_package_digest"}
    if action.get("action_package_digest") != _digest(unsigned):
        raise ProductionManualActionError("manual action package digest mismatch")
    if action.get("patch_sha256") != hashlib.sha256(str(action.get("patch", "")).encode("utf-8")).hexdigest():
        raise ProductionManualActionError("manual action patch digest mismatch")
    if not _SHA64.fullmatch(str(action.get("prepared_artifact_digest", ""))):
        raise ProductionManualActionError("manual action prepared artifact digest is invalid")
    owned = _safe_paths(action.get("owned_files"), label="manual action owned scope")
    changed = _safe_paths(action.get("expected_changed_files"), label="manual action changed files")
    if any(not _within(path, owned) for path in changed):
        raise ProductionManualActionError("manual action changed file is outside owned scope")
    if (action.get("project_id") != manifest.get("project_id") or action.get("run_id") != manifest.get("run_id")
            or action.get("gate_id") != manifest.get("gate_id") or action.get("lv_id") != manifest.get("lv_id")
            or action.get("plan_sha256") != manifest.get("canonical_plan_sha256")
            or action.get("source_head") != manifest.get("source_head") or owned != manifest.get("owned_files")):
        raise ProductionManualActionError("manual action package/Full Plan manifest binding mismatch")
    raw_commands = action.get("validation_commands")
    if not isinstance(raw_commands, Mapping) or set(raw_commands) != set(_VALIDATION_KEYS):
        raise ProductionManualActionError("manual action validation command plan mismatch")
    commands = {key: list(raw_commands[key]) for key in _VALIDATION_KEYS}
    directive, request, decision = _validate_router(action)
    identity = (str(action["project_id"]), str(action["run_id"]), str(action["lv_id"]), str(action["task_execution_id"]), str(action["gate_id"]))
    if (directive.project_id, directive.run_id, directive.task_id, directive.task_execution_id, directive.gate_id) != identity:
        raise ProductionManualActionError("manual action operator directive identity mismatch")
    if action["prepared_artifact_digest"] not in directive.input_artifact_digests:
        raise ProductionManualActionError("manual action prepared artifact is not authorized by directive")
    if (request.project_id, request.run_id, request.task_id, request.task_execution_id) != identity[:4]:
        raise ProductionManualActionError("manual action Router request identity mismatch")
    try:
        auth = ManualActionAuthorizationV1(**dict(authorization))
    except Exception as exc:
        raise ProductionManualActionError(f"manual action authorization invalid: {exc}") from exc
    if (auth.project_id, auth.run_id, auth.task_id, auth.task_execution_id, auth.gate_id) != identity:
        raise ProductionManualActionError("manual action authorization identity mismatch")
    if auth.action_package_digest != action["action_package_digest"]:
        raise ProductionManualActionError("manual action authorization package mismatch")
    if auth.editable_scope_digest != editable_scope_digest(owned):
        raise ProductionManualActionError("manual action authorization scope mismatch")
    if auth.command_digest != command_plan_digest(commands):
        raise ProductionManualActionError("manual action authorization command mismatch")
    return auth, decision


def build_manual_worker_request(*, project_root: str | Path, package_root: str | Path,
                                task: TaskSlice, manifest: Mapping[str, Any],
                                preflight_evidence_sha256: str, package_manifest_sha256: str,
                                approval_event_id: str, action_package: Mapping[str, Any]) -> WorkerRequest:
    """Build the canonical review-visible WorkerRequest for a GPT manual ACTION."""
    if not isinstance(task, TaskSlice):
        raise ProductionManualActionError("manual action task slice is invalid")
    if not _SHA64.fullmatch(str(package_manifest_sha256)) or not _SHA64.fullmatch(str(preflight_evidence_sha256)):
        raise ProductionManualActionError("manual action request evidence digest is invalid")
    run_id = str(manifest.get("run_id", ""))
    if not run_id or run_id != str(action_package.get("run_id", "")):
        raise ProductionManualActionError("manual action request run binding mismatch")
    contract_summary = {
        "project_id": manifest.get("project_id"),
        "gate_id": manifest.get("gate_id"),
        "lv_id": manifest.get("lv_id"),
        "canonical_plan_sha256": manifest.get("canonical_plan_sha256"),
    }
    if any(not isinstance(value, str) or not value for value in contract_summary.values()):
        raise ProductionManualActionError("manual action request contract binding is incomplete")
    extra_context = {
        "execution_mode": "production",
        "execution_backend": "GPT_OPERATOR_MANUAL_ACTION",
        "run_id": run_id,
        "run_root": str(Path(package_root).resolve()),
        "task_effect_requirement": "MUTATION_REQUIRED",
        "change_target_count": len(manifest.get("owned_files", [])),
        "package_manifest_sha256": package_manifest_sha256,
        "preflight_evidence_sha256": preflight_evidence_sha256,
        "attempt": 1,
        "source_snapshot": {key: manifest.get(key) for key in (
            "source_head", "source_tree", "source_index_fingerprint", "source_worktree_fingerprint"
        )},
        "gate_id": manifest.get("gate_id"),
        "lv_id": manifest.get("lv_id"),
        "approval_event_id": approval_event_id,
        "manual_action_package_digest": action_package.get("action_package_digest", ""),
    }
    return WorkerRequest(
        project_root=str(Path(project_root).resolve()), task=task, contract_summary=contract_summary,
        state_snapshot={"branch": "sealed", "head": str(manifest.get("source_head", ""))},
        extra_context=extra_context,
    )


def execute_gpt_operator_manual_action(*, project_root: str | Path, package_root: str | Path,
                                       manifest: Mapping[str, Any], preflight_evidence_sha256: str,
                                       action_package: Mapping[str, Any], authorization: Mapping[str, Any],
                                       expected_branch: str, package_manifest_sha256: str) -> dict[str, Any]:
    root = Path(project_root).resolve(); package = Path(package_root).resolve()
    auth, decision = validate_action_package(action_package, authorization, manifest)
    baseline = _git_text(root, "rev-parse", "HEAD")
    if not _SHA64.fullmatch(str(package_manifest_sha256)):
        raise ProductionManualActionError("manual action package manifest digest is invalid")
    if not isinstance(expected_branch, str) or not expected_branch.strip():
        raise ProductionManualActionError("manual action approved branch binding is missing")
    if _git_text(root, "branch", "--show-current") != expected_branch:
        raise ProductionManualActionError("manual action source identity drift")
    if _git_text(root, "status", "--porcelain=v1", "-uall"):
        raise ProductionManualActionError("manual action requires a clean product worktree")
    safe_descendant = _assert_safe_descendant_source(
        root, sealed_head=str(action_package["source_head"]), current_head=baseline,
        owned_files=list(manifest["owned_files"]),
    )
    baseline_tree = _git_text(root, "rev-parse", "HEAD^{tree}")
    patch_text = str(action_package["patch"])
    patch_fd, patch_name = tempfile.mkstemp(prefix="manual-action-", suffix=".patch", dir=str(package))
    try:
        with os.fdopen(patch_fd, "w", encoding="utf-8") as handle:
            handle.write(patch_text); handle.flush(); os.fsync(handle.fileno())
        check = subprocess.run(["git", "-C", str(root), "apply", "--check", patch_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=60)
        if check.returncode != 0:
            raise ProductionManualActionError("manual action patch preflight failed")
        apply = subprocess.run(["git", "-C", str(root), "apply", patch_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=60)
        if apply.returncode != 0:
            raise ProductionManualActionError("manual action patch apply failed")
    finally:
        try: os.unlink(patch_name)
        except FileNotFoundError: pass
    expected = sorted(action_package["expected_changed_files"])
    working = sorted(set(filter(None, _git_text(root, "diff", "--name-only").splitlines())) |
                     set(filter(None, _git_text(root, "ls-files", "--others", "--exclude-standard").splitlines())))
    if working != expected:
        raise ProductionManualActionError("manual action changed-file set mismatch")
    worker_record = {"command": ["git", "apply", f"sha256:{action_package['patch_sha256']}"], "exit_code": 0, "timeout": False,
                     "stdout_sha256": hashlib.sha256(check.stdout + apply.stdout).hexdigest(),
                     "stderr_sha256": hashlib.sha256(check.stderr + apply.stderr).hexdigest()}
    commands: dict[str, Any] = {"worker": worker_record}
    for key in _VALIDATION_KEYS:
        result = _command(root, action_package["validation_commands"][key])
        commands[key] = result
        if result["exit_code"] != 0 or result["timeout"]:
            raise ProductionManualActionError(f"manual action validation failed: {key}")
    add = _git(root, "add", "--", *expected)
    if add.returncode != 0:
        raise ProductionManualActionError("manual action staging failed")
    staged = sorted(filter(None, _git_text(root, "diff", "--cached", "--name-only").splitlines()))
    if staged != expected:
        raise ProductionManualActionError("manual action staged-file set mismatch")
    commit = _git(root, "-c", "user.name=Global GPT Harness", "-c", "user.email=harness@localhost.invalid",
                  "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", "commit", "-m", str(action_package["commit_subject"]))
    if commit.returncode != 0:
        raise ProductionManualActionError("manual action checkpoint commit failed")
    head = _git_text(root, "rev-parse", "HEAD")
    changed = sorted(filter(None, _git_text(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head).splitlines()))
    if changed != expected or _git_text(root, "status", "--porcelain=v1", "-uall"):
        raise ProductionManualActionError("manual action checkpoint verification failed")
    tree = _git_text(root, "rev-parse", "HEAD^{tree}")
    manual = {"schema_version": "orchestration.production-manual-action-provenance.v1",
              "operator": "GPT_OPERATOR", "authorization": auth.to_dict(),
              "authorization_digest": auth.authorization_digest,
              "action_package_digest": action_package["action_package_digest"],
              "prepared_artifact_digest": action_package["prepared_artifact_digest"],
              "router_decision_digest": decision.decision_digest,
              "editable_scope_digest": auth.editable_scope_digest, "command_digest": auth.command_digest,
              "authorized_commands": {key: list(action_package["validation_commands"][key]) for key in _VALIDATION_KEYS}}
    evidence = {
        "schema_version": "orchestration.product-completion-evidence.v1", "status": "completed",
        "project_id": manifest["project_id"], "gate_id": manifest["gate_id"], "lv_id": manifest["lv_id"],
        "run_id": manifest["run_id"], "approval_event_id": manifest.get("approval_id", ""),
        "plan_sha256": manifest["canonical_plan_sha256"], "attempt": 1, "completion_mode": COMPLETION_MODE,
        "tests": list(action_package["validation_ids"]), "owned_files": list(manifest["owned_files"]),
        "changed_files": changed, "baseline_head": baseline, "baseline_tree": baseline_tree,
        "sealed_source_head": str(action_package["source_head"]), "safe_descendant_source": safe_descendant,
        "current_head": head, "current_tree": tree, "checkpoint_commit": head, "commands": commands,
        "staged_changes": False, "unstaged_changes": False, "review_verdict": "PASS",
        "executor": {"identity": EXECUTOR_ID, "version": EXECUTOR_VERSION}, "manual_action": manual,
        "governed_effect_evidence": [], "package_sha256": package_manifest_sha256,
        "preflight_evidence_sha256": preflight_evidence_sha256,
        "validation_events": ["GPT_OPERATOR_MANUAL_ACTION_AUTHORIZED", "VALIDATION_STARTED", "FOCUSED_TEST_COMPLETED",
                              "FULL_REGRESSION_COMPLETED", "WORKER_RESULT_SEALED"],
        "artifact_sha_chain": {"action_package": action_package["action_package_digest"],
                               "authorization": auth.authorization_digest, "router_decision": decision.decision_digest},
        "hard_stop": True,
    }
    evidence["evidence_sha256"] = _digest(evidence)
    return evidence
