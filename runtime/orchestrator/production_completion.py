"""Deterministic product-evidence verification for production LV completion."""
from __future__ import annotations

import hashlib, json, os, re, tempfile
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

_SHA = re.compile(r"[0-9a-f]{40,64}\Z")
_REQUIRED_IDS = ("project_id", "gate_id", "lv_id", "run_id", "approval_event_id", "plan_sha256")
_COMMANDS = ("worker", "focused_test", "full_regression", "compile_import", "git_diff_check")

class ProductCompletionError(ValueError): pass

def write_completion_rejection(harness_root: str | Path, *, project_id: str, gate_id: str,
                               lv_id: str, run_id: str, attempt: int, reasons: list[str],
                               source_shas: Mapping[str, str], next_attempt: int) -> dict[str, Any]:
    """Append one deterministic, replay-safe completion rejection record."""
    if attempt < 1 or next_attempt != attempt + 1 or not reasons:
        raise ProductCompletionError("completion rejection binding is invalid")
    payload = {"schema_version":"orchestration.product-completion-rejection.v1","project_id":project_id,
               "gate_id":gate_id,"lv_id":lv_id,"run_id":run_id,"attempt":attempt,
               "status":"REJECTED_COMPLETION_UNPROVEN","reasons":sorted(set(reasons)),
               "source_shas":dict(sorted(source_shas.items())),"next_attempt":next_attempt,"hard_stop":True}
    raw=lambda value: json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    payload["record_hash"]=hashlib.sha256(raw(payload)).hexdigest()
    target=Path(harness_root).resolve()/"_workspace"/"global-gate"/project_id/"recovery"/f"{run_id}-attempt-{attempt:02d}-completion-rejection.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        existing=json.loads(target.read_text(encoding="utf-8"))
        if existing != payload: raise ProductCompletionError("completion rejection replay conflict")
        return existing
    fd,tmp=tempfile.mkstemp(prefix=target.name+".",dir=str(target.parent))
    try:
        with os.fdopen(fd,"wb") as handle: handle.write(raw(payload)); handle.flush(); os.fsync(handle.fileno())
        try: os.link(tmp,target)
        except FileExistsError: raise ProductCompletionError("completion rejection already exists")
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return payload

def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise ProductCompletionError("git evidence verification failed")
    return result.stdout.strip()

def _safe_paths(values: object) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(v, str) or not v or PurePosixPath(v).is_absolute() or ".." in PurePosixPath(v).parts for v in values):
        raise ProductCompletionError("path evidence is invalid")
    return list(values)

def verify_product_completion(project_root: str | Path, evidence: Mapping[str, Any],
                              contract: Mapping[str, Any], *, terminal_head: bool = True) -> dict[str, Any]:
    """Verify Git and command evidence independently; return structured reasons."""
    root = Path(project_root).resolve(); reasons: list[str] = []
    if not root.is_dir() or not isinstance(evidence, Mapping) or not isinstance(contract, Mapping):
        raise ProductCompletionError("completion input is invalid")
    for field in _REQUIRED_IDS:
        if not isinstance(evidence.get(field), str) or not evidence[field]: reasons.append(f"MISSING_{field.upper()}")
        elif contract.get(field) is not None and evidence[field] != contract[field]: reasons.append(f"MISMATCH_{field.upper()}")
    if evidence.get("attempt", 0) < 1: reasons.append("INVALID_ATTEMPT")
    if evidence.get("hard_stop") is not True: reasons.append("HARD_STOP_MISSING")
    owned = _safe_paths(contract.get("owned_files", [])); changed = _safe_paths(evidence.get("changed_files", []))
    mode = evidence.get("completion_mode", "CODE_CHANGE")
    if not changed and mode != "PLAN_AUTHORIZED_NO_OP": reasons.append("CHANGED_FILES_EMPTY")
    if mode == "PLAN_AUTHORIZED_NO_OP" and contract.get("allow_no_op") is not True: reasons.append("NO_OP_NOT_AUTHORIZED")
    for path in changed:
        if not any(path == scope or (scope.endswith("/") and path.startswith(scope)) for scope in owned): reasons.append("OWNED_SCOPE_VIOLATION")
    commands = evidence.get("commands")
    if not isinstance(commands, Mapping): reasons.append("COMMAND_EVIDENCE_MISSING")
    else:
        for name in _COMMANDS:
            item = commands.get(name)
            if not isinstance(item, Mapping) or not isinstance(item.get("command"), list) or item.get("exit_code") != 0:
                reasons.append(f"{name.upper()}_UNPROVEN")
    if evidence.get("review_verdict") != "PASS": reasons.append("REVIEW_NOT_PASS")
    if evidence.get("staged_changes") is not False or evidence.get("unstaged_changes") is not False: reasons.append("WORKTREE_NOT_DECLARED_CLEAN")
    checkpoint = evidence.get("checkpoint_commit")
    if not isinstance(checkpoint, str) or not _SHA.fullmatch(checkpoint): reasons.append("CHECKPOINT_COMMIT_MISSING")
    else:
        try:
            head = _git(root, "rev-parse", "HEAD"); tree = _git(root, "rev-parse", f"{checkpoint}^{{tree}}")
            files = set(_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", checkpoint).splitlines())
            if terminal_head and head != checkpoint: reasons.append("CHECKPOINT_NOT_HEAD")
            if evidence.get("current_head") != checkpoint: reasons.append("CHECKPOINT_BINDING_MISMATCH")
            if not terminal_head:
                ancestor = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", checkpoint, head], check=False)
                if ancestor.returncode != 0: reasons.append("CHECKPOINT_NOT_ANCESTOR")
                else:
                    later = set(_git(root, "diff", "--name-only", f"{checkpoint}..{head}").splitlines())
                    if later.intersection(set(owned)): reasons.append("PRIOR_LV_SCOPE_INVALIDATED")
            if not set(changed).issubset(files): reasons.append("CHECKPOINT_FILES_MISSING")
            if _git(root, "status", "--porcelain=v1"): reasons.append("WORKTREE_NOT_CLEAN")
        except ProductCompletionError:
            reasons.append("CHECKPOINT_COMMIT_INVALID")
    baseline = evidence.get("baseline_head")
    if not isinstance(baseline, str) or not _SHA.fullmatch(baseline): reasons.append("BASELINE_HEAD_MISSING")
    else:
        try:
            if evidence.get("baseline_tree") != _git(root, "rev-parse", f"{baseline}^{{tree}}"):
                reasons.append("BASELINE_TREE_MISMATCH")
        except ProductCompletionError: reasons.append("BASELINE_HEAD_INVALID")
    if not isinstance(evidence.get("artifact_sha_chain"), Mapping) or not evidence["artifact_sha_chain"]:
        reasons.append("ARTIFACT_SHA_CHAIN_MISSING")
    reasons = sorted(set(reasons))
    return {"schema_version":"orchestration.product-completion-verdict.v1",
            "status":"PASS" if not reasons else "REJECTED_COMPLETION_UNPROVEN",
            "completion_eligible":not reasons, "reasons":reasons, "hard_stop":True}
