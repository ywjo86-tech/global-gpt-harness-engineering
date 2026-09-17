"""Append-only recovery records for rejected partial production attempts."""
from __future__ import annotations
import hashlib, json, os, re, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

class RecoveryError(ValueError): pass
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}\Z")

def _valid_git_branch(value: object) -> bool:
    if not isinstance(value, str) or not _BRANCH.fullmatch(value):
        return False
    if value.startswith("/") or value.endswith("/") or value.endswith(".") or value.endswith(".lock"):
        return False
    if any(token in value for token in ("..", "//", "@{", "\\", "~", "^", ":", "?", "*", "[")):
        return False
    return all(part and not part.startswith(".") and not part.endswith(".lock") for part in value.split("/"))

def attempt_directory(attempt: object) -> str:
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
        raise RecoveryError("recovery attempt must be a positive integer")
    return f"attempt-{attempt:02d}"

def _bytes(v: object) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def _write_once(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically create a canonical JSON artifact, allowing identical replay."""
    data = _bytes(payload)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data:
            raise RecoveryError(f"recovery artifact replay conflict: {path.name}")
        return dict(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise RecoveryError("recovery artifact parent must not be a symlink")
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        try: os.link(tmp, path)
        except FileExistsError: raise RecoveryError(f"recovery artifact already exists: {path.name}")
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return dict(payload)

def write_provenance_rejection(harness_root: str | Path, *, project_id: str,
                               run_id: str, gate_id: str, lv_id: str,
                               schema_version: str, package_sha256: str,
                               source_preflight_sha256: str,
                               invalid_payload_sha256: str,
                               invalid_sidecar_expected_sha256: str,
                               invalid_sidecar_file_sha256: str,
                               predecessor: str | None,
                               provenance_audit_ref: str,
                               reason_code: str,
                               validator_version: str,
                               attempt: int | None = None,
                               recovery_id: str | None = None) -> dict[str, Any]:
    """Persist an immutable, provenance-bound rejection exactly once.

    This record deliberately lives beside recovery records and never mutates
    the rejected payload or sidecar.  Replays return the original bytes;
    conflicting identity or digest data is rejected.
    """
    values = (project_id, run_id, gate_id, lv_id, schema_version, package_sha256,
              source_preflight_sha256, invalid_payload_sha256,
              invalid_sidecar_expected_sha256, invalid_sidecar_file_sha256,
              provenance_audit_ref, reason_code, validator_version)
    if not all(isinstance(value, str) and value for value in values):
        raise RecoveryError("provenance rejection binding is incomplete")
    if not all(_SHA.fullmatch(value) for value in (package_sha256,
                                                   source_preflight_sha256,
                                                   invalid_payload_sha256,
                                                   invalid_sidecar_expected_sha256,
                                                   invalid_sidecar_file_sha256)):
        raise RecoveryError("provenance rejection digest is invalid")
    if attempt is not None and (not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0):
        raise RecoveryError("provenance rejection attempt is invalid")
    if recovery_id is not None and (not isinstance(recovery_id, str) or not _ID.fullmatch(recovery_id)):
        raise RecoveryError("provenance rejection recovery ID is invalid")
    if not all(_ID.fullmatch(value) for value in (project_id, run_id, gate_id, lv_id, reason_code, validator_version)):
        raise RecoveryError("provenance rejection identity is invalid")
    payload = {
        "schema_version": "orchestration.provenance-rejection.v1",
        "project_id": project_id, "run_id": run_id, "gate_id": gate_id, "lv_id": lv_id,
        "attempt": attempt, "recovery_id": recovery_id,
        "rejected_schema_version": schema_version,
        "package_sha256": package_sha256,
        "source_preflight_sha256": source_preflight_sha256,
        "invalid_payload_sha256": invalid_payload_sha256,
        "invalid_sidecar_expected_sha256": invalid_sidecar_expected_sha256,
        "invalid_sidecar_file_sha256": invalid_sidecar_file_sha256,
        "predecessor": predecessor,
        "provenance_audit_ref": provenance_audit_ref,
        "reason_code": reason_code,
        "validator_version": validator_version,
        "completion_eligible": False,
        "hard_stop": True,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["record_hash"] = hashlib.sha256(_bytes(payload)).hexdigest()
    harness_path = Path(harness_root).resolve()
    # Recovery records belong to the repository-level global-gate store.  A
    # preflight/publication staging directory is never a valid recovery root;
    # reject it before creating any directory or file.
    if "orchestration-preflights" in harness_path.parts:
        raise RecoveryError("noncanonical recovery destination")
    root = harness_path / "_workspace" / "global-gate" / project_id / "recovery"
    if root.is_symlink():
        raise RecoveryError("provenance rejection root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    suffix = f"-{lv_id}" if lv_id else ""
    target = root / f"{run_id}-provenance-rejection{suffix}.json"
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RecoveryError("provenance rejection replay is malformed") from exc
        if existing.get("record_hash") != hashlib.sha256(_bytes({k: v for k, v in existing.items() if k != "record_hash"})).hexdigest():
            raise RecoveryError("provenance rejection hash mismatch")
        if {k: v for k, v in existing.items() if k not in {"created_at", "record_hash"}} != {k: v for k, v in payload.items() if k not in {"created_at", "record_hash"}}:
            raise RecoveryError("provenance rejection replay conflict")
        return existing
    _write_once(target, payload)
    return payload

def write_recovery_record(harness_root: str | Path, *, project_id: str, gate_id: str, lv_id: str, run_id: str,
                          rejected_attempt: int, rejected_artifacts: Mapping[str, str], reason_code: str,
                          missing_bindings: list[str], recovery_attempt: int, approval_event_id: str,
                          plan_sha256: str, branch: str, baseline_head: str, current_head: str,
                          active_transition_sha256: str, source_shas: Mapping[str, str], predecessor: str | None,
                          supersedes: str, hard_stop: bool = True, recovery_id: str | None = None,
                          source_binding_kind: str = "ACTIVE_TRANSITION") -> dict[str, Any]:
    if rejected_attempt <= 0 or recovery_attempt != rejected_attempt + 1 or not hard_stop:
        raise RecoveryError("invalid recovery attempt or hard-stop binding")
    if not all(isinstance(v, str) and v for v in (project_id, gate_id, lv_id, run_id, reason_code, approval_event_id, plan_sha256, branch, baseline_head, current_head, active_transition_sha256, supersedes, source_binding_kind)):
        raise RecoveryError("recovery binding is incomplete")
    if (not all(_ID.fullmatch(v) for v in (project_id, gate_id, lv_id, run_id, reason_code, approval_event_id, supersedes, source_binding_kind))
            or not _valid_git_branch(branch)):
        raise RecoveryError("recovery binding is incomplete")
    if source_binding_kind not in {"ACTIVE_TRANSITION", "PRE_RESULT_PARTIAL_SOURCE", "POST_RESULT_MISSING_REQUEST_SOURCE"}:
        raise RecoveryError("unsupported recovery source binding kind")
    for path, digest in {**rejected_artifacts, **source_shas}.items():
        p = Path(path)
        if p.is_absolute() or ".." in p.parts or not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise RecoveryError("invalid recovery source path or SHA")
    recovery_id = recovery_id or f"{run_id}-recovery-{recovery_attempt:02d}"
    if not _ID.fullmatch(recovery_id):
        raise RecoveryError("recovery ID is invalid")
    payload = {"schema_version":"orchestration.production-recovery.v1","recovery_id":recovery_id,"project_id":project_id,"gate_id":gate_id,"lv_id":lv_id,"run_id":run_id,"rejected_attempt":rejected_attempt,"rejected_artifacts":dict(rejected_artifacts),"rejection_reason_code":reason_code,"missing_bindings":list(missing_bindings),"recovery_attempt":recovery_attempt,"approval_event_id":approval_event_id,"plan_sha256":plan_sha256,"branch":branch,"baseline_head":baseline_head,"current_head":current_head,"active_transition_sha256":active_transition_sha256,"source_binding_kind":source_binding_kind,"source_shas":dict(source_shas),"predecessor":predecessor,"supersedes":supersedes,"created_at":datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),"hard_stop":True}
    payload["record_hash"] = hashlib.sha256(_bytes(payload)).hexdigest()
    root = Path(harness_root).resolve()/"_workspace"/"global-gate"/project_id/"recovery"
    root.mkdir(parents=True, exist_ok=True); target=root/(payload["recovery_id"]+".json")
    if target.exists():
        existing=json.loads(target.read_text(encoding="utf-8"))
        if {k:v for k,v in existing.items() if k not in {"created_at","record_hash"}} != {k:v for k,v in payload.items() if k not in {"created_at","record_hash"}}: raise RecoveryError("recovery replay conflict")
        if existing.get("record_hash") != hashlib.sha256(_bytes({k:v for k,v in existing.items() if k!="record_hash"})).hexdigest(): raise RecoveryError("recovery hash mismatch")
        return existing
    fd,tmp=tempfile.mkstemp(prefix=target.name+".",dir=str(root))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as h: h.write(_bytes(payload).decode()); h.flush(); os.fsync(h.fileno())
        try:
            os.link(tmp, target)
        except FileExistsError:
            raise RecoveryError("recovery record already exists")
        finally:
            os.unlink(tmp)
        tmp = ""
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return payload

def classify_partial_attempt(manifest: Mapping[str, Any], worker: Mapping[str, Any] | None) -> dict[str, Any]:
    missing = [field for field in ("project_id", "canonical_plan_sha256") if not manifest.get(field)]
    if worker is None:
        missing.append("worker.result")
    else:
        missing.extend(field for field in ("project_id", "canonical_plan_sha256", "hard_stop") if not worker.get(field))
        # A worker result without the preflight digest was never producer-bound;
        # it must be rejected and can only advance through a new attempt.
        if not worker.get("preflight_evidence_sha256"):
            missing.append("preflight_evidence_sha256")
    status = "BOUND"
    if missing:
        status = ("REJECTED_WORKER_RESULT_UNBOUND_PREFLIGHT"
                  if "preflight_evidence_sha256" in missing and worker is not None
                  and worker.get("project_id") and (worker.get("canonical_plan_sha256") or worker.get("plan_sha256"))
                  else "REJECTED_UNBOUND_LEGACY")
    return {"status": status, "missing_bindings": sorted(set(missing)), "completion_eligible": not missing}

def is_completion_eligible(payload: Mapping[str, Any] | None, *,
                           manifest: Mapping[str, Any] | None = None) -> bool:
    """Reject retained recovery artifacts that must never be promoted."""
    if not isinstance(payload, Mapping):
        return False
    if payload.get("completion_eligible") is False:
        return False
    if isinstance(payload.get("status"), str) and payload.get("status", "").startswith("REJECTED_"):
        return False
    if isinstance(payload.get("rejection_reason_code"), str) and payload.get("rejection_reason_code", "").startswith("REJECTED_"):
        return False
    if manifest is not None and payload.get("attempt") == 1:
        return bool(classify_partial_attempt(manifest, payload)["completion_eligible"])
    return True

def canonical_recovery_binding(record: Mapping[str, Any], checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    """Build the one lifecycle binding shared by every recovery artifact."""
    keys = ("project_id", "gate_id", "lv_id", "run_id", "recovery_id")
    if any(record.get(key) != checkpoint.get(key) for key in keys):
        raise RecoveryError("recovery control binding mismatch")
    binding = {key: record.get(key) for key in keys}
    binding.update({
        "attempt": record.get("recovery_attempt"),
        "canonical_plan_sha256": record.get("plan_sha256"),
        "approval_event_id": record.get("approval_event_id"),
        "active_transition_sha256": record.get("active_transition_sha256"),
        "recovery_record_hash": record.get("record_hash"),
        "recovery_checkpoint_sha256": checkpoint.get("checkpoint_sha256"),
        "hard_stop": True,
    })
    required = ("project_id", "gate_id", "lv_id", "run_id", "recovery_id",
                "canonical_plan_sha256", "approval_event_id", "active_transition_sha256",
                "recovery_record_hash", "recovery_checkpoint_sha256")
    if any(not isinstance(binding.get(key), str) or not binding[key] for key in required):
        raise RecoveryError("canonical recovery binding is incomplete")
    if not isinstance(binding["attempt"], int) or binding["attempt"] <= 0 or checkpoint.get("next_attempt") != binding["attempt"] or record.get("hard_stop") is not True or checkpoint.get("hard_stop") is not True:
        raise RecoveryError("canonical recovery binding attempt or hard-stop mismatch")
    return binding

def prepare_partial_recovery(harness_root: str | Path, *, manifest_path: str | Path,
                             worker_path: str | Path, transition_path: str | Path,
                             approval_event_id: str) -> dict[str, Any]:
    """Classify one immutable partial attempt and persist its recovery decision.

    This is the controller-facing entry point.  It deliberately returns no
    completion evidence for a rejected attempt.
    """
    root = Path(harness_root).resolve()
    paths = [Path(value) for value in (manifest_path, worker_path, transition_path)]
    for path in paths:
        resolved = path.resolve()
        if not path.is_file() or path.is_symlink() or root not in resolved.parents:
            raise RecoveryError("unsafe recovery source artifact")
    try:
        manifest, worker, transition = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("malformed recovery source artifact") from exc
    if not all(isinstance(value, dict) for value in (manifest, worker, transition)):
        raise RecoveryError("recovery source artifact must be an object")
    keys = ("project_id", "gate_id", "lv_id", "run_id")
    expected = {key: manifest.get(key) for key in keys}
    if not all(isinstance(value, str) and value for value in expected.values()):
        raise RecoveryError("partial manifest binding is incomplete")
    if any(transition.get(key) != value for key, value in expected.items()):
        raise RecoveryError("partial transition binding mismatch")
    if any(worker.get(key) != value for key, value in expected.items() if key != "project_id"):
        raise RecoveryError("partial worker binding mismatch")
    if not isinstance(worker.get("attempt"), int) or worker["attempt"] <= 0:
        raise RecoveryError("partial worker attempt is invalid")
    classification = classify_partial_attempt(manifest, worker)
    if not classification["status"].startswith("REJECTED_"):
        raise RecoveryError("partial attempt is not eligible for legacy recovery")
    relative = [path.resolve().relative_to(root).as_posix() for path in paths]
    shas = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in zip(relative, paths)}
    run_id = expected["run_id"]
    rejected_attempt = int(worker["attempt"]); next_attempt = rejected_attempt + 1
    recovery_id = f"{run_id}-recovery-{next_attempt:02d}"
    recovery_root = root / "_workspace" / "global-gate" / expected["project_id"] / "recovery"
    if recovery_root.is_symlink():
        raise RecoveryError("recovery root must not be a symlink")
    if recovery_root.is_dir():
        for candidate in recovery_root.glob(f"{run_id}-recovery-*.json"):
            if candidate.name.endswith(".checkpoint.json"):
                continue
            # Recovery records are namespaced by LV as well as run.  A
            # completed lineage for another LV must not block this LV's
            # append-only recovery sequence.
            try:
                existing_record = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise RecoveryError("conflicting active recovery exists")
            if candidate.name != f"{recovery_id}.json" and existing_record.get("lv_id") == expected["lv_id"]:
                raise RecoveryError("conflicting active recovery exists")
            if candidate.name == f"{recovery_id}.json" and existing_record.get("lv_id") != expected["lv_id"]:
                # Preserve the historical run-level identifier while
                # avoiding a cross-LV collision in the shared append-only
                # namespace.
                recovery_id = f"{run_id}-recovery-{next_attempt:02d}-{expected['lv_id']}"
    transition_sha = shas[relative[2]]
    record = write_recovery_record(
        root, project_id=expected["project_id"], gate_id=expected["gate_id"],
        lv_id=expected["lv_id"], run_id=run_id, rejected_attempt=rejected_attempt,
        rejected_artifacts={relative[0]: shas[relative[0]], relative[1]: shas[relative[1]]},
        reason_code=classification["status"], missing_bindings=classification["missing_bindings"],
        recovery_attempt=next_attempt, approval_event_id=approval_event_id,
        plan_sha256=str(manifest.get("canonical_plan_sha256", "")),
        branch=str(transition.get("branch", "")), baseline_head=str(transition.get("baseline_head", "")),
        current_head=str(transition.get("current_head", "")), active_transition_sha256=transition_sha,
        source_shas=shas, predecessor=None, supersedes=shas[relative[1]], hard_stop=True,
        recovery_id=recovery_id,
    )
    checkpoint = {
        "schema_version": "orchestration.production-recovery-checkpoint.v1",
        "project_id": expected["project_id"], "gate_id": expected["gate_id"],
        "lv_id": expected["lv_id"], "run_id": run_id, "recovery_id": record["recovery_id"],
        "rejected_attempt": rejected_attempt, "next_attempt": next_attempt, "recovery_record_hash": record["record_hash"],
        "completion_evidence": [], "status": classification["status"], "hard_stop": True,
    }
    checkpoint["checkpoint_sha256"] = hashlib.sha256(_bytes(checkpoint)).hexdigest()
    target = recovery_root / f"{recovery_id}.checkpoint.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != checkpoint:
            raise RecoveryError("recovery checkpoint replay conflict")
    else:
        fd, tmp = tempfile.mkstemp(prefix=target.name + ".", dir=str(recovery_root))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(_bytes(checkpoint)); handle.flush(); os.fsync(handle.fileno())
            try: os.link(tmp, target)
            except FileExistsError: raise RecoveryError("recovery checkpoint already exists")
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    return {"classification": classification, "recovery": record, "checkpoint": checkpoint,
            "next_attempt": next_attempt, "completion_evidence": [], "hard_stop": True}

def _within_owned_scope(path: str, scopes: list[str]) -> bool:
    return any(path == scope.rstrip("/") or (scope.endswith("/") and path.startswith(scope)) for scope in scopes)


def prepare_pre_result_partial_recovery(
    harness_root: str | Path, *, project_root: str | Path,
    package_manifest_path: str | Path, preflight_path: str | Path,
    worker_request_path: str | Path, process_path: str | Path,
    approval_event_id: str, branch: str, baseline_head: str,
) -> dict[str, Any]:
    """Seal a broker-failed pre-result partial workspace into attempt-N+1 recovery.

    This path is intentionally narrower than legacy partial recovery: the first
    attempt must have a sealed PACKAGE/PREFLIGHT/worker request, a terminal
    nonzero executor process, no worker.result, and a nonempty Git diff wholly
    contained by the sealed owned scope.  The source artifact binds both the
    failed broker effects and the exact current partial file bytes.
    """
    root = Path(harness_root).resolve()
    project = Path(project_root).resolve()
    if not project.is_dir() or project.is_symlink():
        raise RecoveryError("pre-result partial project root is unsafe")
    paths = [Path(value) for value in (
        package_manifest_path, preflight_path, worker_request_path, process_path,
    )]
    for path in paths:
        resolved = path.resolve()
        if not path.is_file() or path.is_symlink() or root not in resolved.parents:
            raise RecoveryError("unsafe pre-result partial source artifact")
    try:
        manifest, preflight, request, process = [
            json.loads(path.read_text(encoding="utf-8")) for path in paths
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("malformed pre-result partial source artifact") from exc
    if not all(isinstance(value, dict) for value in (manifest, preflight, request, process)):
        raise RecoveryError("pre-result partial source artifact must be an object")

    expected = {key: manifest.get(key) for key in ("project_id", "gate_id", "lv_id", "run_id")}
    if not all(isinstance(value, str) and value for value in expected.values()):
        raise RecoveryError("pre-result partial manifest binding is incomplete")
    extra = request.get("extra_context")
    contract = request.get("contract_summary")
    if not isinstance(extra, dict) or not isinstance(contract, dict):
        raise RecoveryError("pre-result partial worker request binding is missing")
    if any(preflight.get(key) != value for key, value in expected.items()):
        raise RecoveryError("pre-result partial preflight binding mismatch")
    if any(contract.get(key) != value for key, value in expected.items() if key != "run_id"):
        raise RecoveryError("pre-result partial worker contract binding mismatch")
    if any(extra.get(key) != expected[key] for key in ("gate_id", "lv_id", "run_id")):
        raise RecoveryError("pre-result partial worker request identity mismatch")
    if extra.get("approval_event_id") != approval_event_id:
        raise RecoveryError("pre-result partial approval binding mismatch")
    rejected_attempt = extra.get("attempt")
    if not isinstance(rejected_attempt, int) or isinstance(rejected_attempt, bool) or rejected_attempt <= 0:
        raise RecoveryError("pre-result partial worker attempt is invalid")

    package_sidecar = paths[0].with_suffix(".sha256")
    preflight_sidecar = paths[1].with_suffix(".sha256")
    if not package_sidecar.is_file() or package_sidecar.is_symlink() or not preflight_sidecar.is_file() or preflight_sidecar.is_symlink():
        raise RecoveryError("pre-result partial source sidecar is missing or unsafe")
    package_sha = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    preflight_sha = hashlib.sha256(paths[1].read_bytes()).hexdigest()
    if package_sidecar.read_text(encoding="ascii").strip() != package_sha:
        raise RecoveryError("pre-result partial package sidecar mismatch")
    if preflight_sidecar.read_text(encoding="ascii").strip() != preflight_sha:
        raise RecoveryError("pre-result partial preflight sidecar mismatch")
    if preflight.get("package_manifest_sha256") != package_sha or extra.get("package_manifest_sha256") != package_sha:
        raise RecoveryError("pre-result partial package lineage mismatch")
    if extra.get("preflight_evidence_sha256") != preflight_sha:
        raise RecoveryError("pre-result partial preflight lineage mismatch")
    plan_sha = manifest.get("canonical_plan_sha256")
    if not isinstance(plan_sha, str) or not _SHA.fullmatch(plan_sha) or contract.get("canonical_plan_sha256") != plan_sha:
        raise RecoveryError("pre-result partial plan binding mismatch")
    source_head = manifest.get("source_head")
    if not isinstance(source_head, str) or not source_head:
        raise RecoveryError("pre-result partial source HEAD is missing")
    current_head = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    if current_head != source_head:
        raise RecoveryError("pre-result partial HEAD drifted from sealed source")
    if process.get("termination") not in {"EXITED", "TIMED_OUT", "CANCELLED"} or process.get("exit_code") in {None, 0}:
        raise RecoveryError("pre-result partial executor failure is not terminal")
    if not isinstance(process.get("broker_block"), dict):
        raise RecoveryError("pre-result partial broker failure evidence is missing")
    package_root = paths[0].parent
    if (package_root / "worker.result.json").exists() or (package_root / "worker.result.json").is_symlink():
        raise RecoveryError("pre-result partial recovery requires absent worker result")

    owned = manifest.get("owned_files")
    if not isinstance(owned, list) or not owned or any(not isinstance(item, str) or not item for item in owned):
        raise RecoveryError("pre-result partial owned scope is malformed")
    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain=v1", "-uall"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    changed = [line[3:] for line in status if len(line) > 3]
    if not changed or any(not _within_owned_scope(path, owned) for path in changed):
        raise RecoveryError("pre-result partial workspace is not a nonempty owned subset")
    owned_diff: dict[str, str] = {}
    for relative in sorted(changed):
        target = project / relative
        if target.is_symlink() or not target.is_file():
            raise RecoveryError("pre-result partial owned diff is not a regular file")
        owned_diff[relative] = hashlib.sha256(target.read_bytes()).hexdigest()

    effects = process.get("governed_effect_evidence")
    if not isinstance(effects, list) or not effects:
        raise RecoveryError("pre-result partial governed effect evidence is missing")
    effect_projection = []
    effect_artifacts: dict[str, str] = {}
    journal_root = root / "_workspace" / "host-gateway-ledger" / expected["project_id"] / expected["run_id"] / "tool-effects"
    for effect in effects:
        if not isinstance(effect, dict) or effect.get("operation") != "PROJECT_OWNED_FILE_WRITE":
            raise RecoveryError("pre-result partial governed effect evidence is malformed")
        scope_ref = effect.get("scope_ref")
        effect_id = effect.get("effect_id")
        if not isinstance(scope_ref, str) or not _within_owned_scope(scope_ref, owned) or not isinstance(effect_id, str) or not effect_id:
            raise RecoveryError("pre-result partial governed effect scope is invalid")
        for suffix in ("intent.json", "receipt.json"):
            artifact = journal_root / f"{effect_id}.{suffix}"
            if not artifact.is_file() or artifact.is_symlink():
                raise RecoveryError("pre-result partial tool-effect journal is incomplete")
            rel = artifact.resolve().relative_to(root).as_posix()
            effect_artifacts[rel] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        effect_projection.append({
            "effect_id": effect_id, "scope_ref": scope_ref,
            "mutation_performed": effect.get("mutation_performed") is True,
            "security_passed": effect.get("security_passed") is True,
        })
    if not any(item["mutation_performed"] and item["security_passed"] for item in effect_projection):
        raise RecoveryError("pre-result partial workspace lacks a completed governed mutation")
    if not any(not item["mutation_performed"] for item in effect_projection):
        raise RecoveryError("pre-result partial failure lacks a non-mutating failed effect")

    relative_sources = [path.resolve().relative_to(root).as_posix() for path in paths]
    source_shas = {
        rel: hashlib.sha256(path.read_bytes()).hexdigest()
        for rel, path in zip(relative_sources, paths)
    }
    source_shas.update(effect_artifacts)
    source = {
        "schema_version": "orchestration.pre-result-partial-source.v1",
        **expected,
        "attempt": rejected_attempt,
        "canonical_plan_sha256": plan_sha,
        "approval_event_id": approval_event_id,
        "branch": branch,
        "baseline_head": baseline_head,
        "source_head": source_head,
        "current_head": current_head,
        "owned_files": list(owned),
        "owned_diff": owned_diff,
        "package_manifest_sha256": package_sha,
        "preflight_evidence_sha256": preflight_sha,
        "worker_request_sha256": source_shas[relative_sources[2]],
        "executor_process_sha256": source_shas[relative_sources[3]],
        "governed_write_effects": sorted(effect_projection, key=lambda item: item["effect_id"]),
        "tool_effect_artifacts": dict(sorted(effect_artifacts.items())),
        "failure": {
            "termination": process.get("termination"), "exit_code": process.get("exit_code"),
            "broker_block": dict(process["broker_block"]),
        },
        "hard_stop": True,
    }
    source["source_payload_sha256"] = hashlib.sha256(_bytes(source)).hexdigest()
    source_path = package_root / "pre-result-partial-source.json"
    _write_once(source_path, source)
    source_rel = source_path.resolve().relative_to(root).as_posix()
    source_file_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    source_shas[source_rel] = source_file_sha

    next_attempt = rejected_attempt + 1
    recovery_id = f"{expected['run_id']}-recovery-{next_attempt:02d}"
    record = write_recovery_record(
        root, project_id=expected["project_id"], gate_id=expected["gate_id"],
        lv_id=expected["lv_id"], run_id=expected["run_id"],
        rejected_attempt=rejected_attempt,
        rejected_artifacts={source_rel: source_file_sha},
        reason_code="REJECTED_PRE_RESULT_PARTIAL", missing_bindings=["worker.result"],
        recovery_attempt=next_attempt, approval_event_id=approval_event_id,
        plan_sha256=plan_sha, branch=branch, baseline_head=baseline_head,
        current_head=current_head, active_transition_sha256=source_file_sha,
        source_shas=source_shas, predecessor=None, supersedes=source_file_sha,
        hard_stop=True, recovery_id=recovery_id,
        source_binding_kind="PRE_RESULT_PARTIAL_SOURCE",
    )
    checkpoint = {
        "schema_version": "orchestration.production-recovery-checkpoint.v1",
        "project_id": expected["project_id"], "gate_id": expected["gate_id"],
        "lv_id": expected["lv_id"], "run_id": expected["run_id"],
        "recovery_id": record["recovery_id"], "rejected_attempt": rejected_attempt,
        "next_attempt": next_attempt, "recovery_record_hash": record["record_hash"],
        "completion_evidence": [], "status": "REJECTED_PRE_RESULT_PARTIAL",
        "source_binding_kind": "PRE_RESULT_PARTIAL_SOURCE", "hard_stop": True,
    }
    checkpoint["checkpoint_sha256"] = hashlib.sha256(_bytes(checkpoint)).hexdigest()
    recovery_root = root / "_workspace" / "global-gate" / expected["project_id"] / "recovery"
    checkpoint_path = recovery_root / f"{record['recovery_id']}.checkpoint.json"
    _write_once(checkpoint_path, checkpoint)
    return {
        "classification": {"status": "REJECTED_PRE_RESULT_PARTIAL", "completion_eligible": False,
                           "missing_bindings": ["worker.result"]},
        "recovery": record, "checkpoint": checkpoint, "next_attempt": next_attempt,
        "source": source, "source_path": str(source_path), "completion_evidence": [], "hard_stop": True,
    }



def _run_checkpoint_verification_command(project: Path, argv: list[str], *, timeout: int = 300) -> dict[str, Any]:
    if not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
        raise RecoveryError("checkpoint recovery validation command is invalid")
    executable = Path(argv[0]).name
    if executable in {"python", "python3"}:
        if argv[1:3] not in (["-m", "unittest"], ["-m", "compileall"]):
            raise RecoveryError("checkpoint recovery Python command is not approved")
    elif executable == "git":
        if argv[1:3] != ["diff", "--check"]:
            raise RecoveryError("checkpoint recovery Git command is not approved")
    else:
        raise RecoveryError("checkpoint recovery command executable is not approved")
    try:
        completed = subprocess.run(argv, cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   check=False, timeout=timeout)
        timed_out = False
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr, exit_code = exc.stdout or b"", exc.stderr or b"", None
    return {"command": list(argv), "exit_code": exit_code, "timeout": timed_out,
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest()}


def prepare_post_result_missing_request_recovery(
    harness_root: str | Path, *, project_root: str | Path,
    package_manifest_path: str | Path, preflight_path: str | Path,
    worker_result_path: str | Path, review_request_path: str | Path,
    approval_event_id: str, branch: str,
) -> dict[str, Any]:
    """Reject a completed result whose pre-execution WorkerRequest is absent.

    The missing request is never reconstructed.  Instead, the original result
    is retained as immutable incident evidence and attempt N+1 is authorized
    only for checkpoint adoption + verification.
    """
    root = Path(harness_root).resolve(); project = Path(project_root).resolve()
    paths = [Path(value) for value in (package_manifest_path, preflight_path, worker_result_path, review_request_path)]
    if not project.is_dir() or project.is_symlink():
        raise RecoveryError("post-result recovery project root is unsafe")
    for path in paths:
        if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
            raise RecoveryError("post-result recovery source artifact is unsafe")
    package_root = paths[0].parent
    request_path = package_root / "worker.request.json"
    if request_path.exists() or request_path.is_symlink():
        raise RecoveryError("post-result recovery requires the original worker request to be absent")
    try:
        manifest, preflight, worker, review_request = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("post-result recovery source artifact is malformed") from exc
    if not all(isinstance(value, dict) for value in (manifest, preflight, worker, review_request)):
        raise RecoveryError("post-result recovery source artifact must be an object")
    expected = {key: manifest.get(key) for key in ("project_id", "gate_id", "lv_id", "run_id")}
    if not all(isinstance(value, str) and value for value in expected.values()):
        raise RecoveryError("post-result recovery manifest binding is incomplete")
    if any(preflight.get(key) != value for key, value in expected.items()):
        raise RecoveryError("post-result recovery preflight binding mismatch")
    if any(worker.get(key) != value for key, value in expected.items()):
        raise RecoveryError("post-result recovery worker binding mismatch")
    if any(review_request.get(key) != value for key, value in expected.items()):
        raise RecoveryError("post-result recovery review request binding mismatch")
    package_sidecar = paths[0].with_suffix('.sha256'); preflight_sidecar = paths[1].with_suffix('.sha256')
    package_sha = hashlib.sha256(paths[0].read_bytes()).hexdigest(); preflight_sha = hashlib.sha256(paths[1].read_bytes()).hexdigest()
    if not package_sidecar.is_file() or package_sidecar.is_symlink() or package_sidecar.read_text(encoding='ascii').strip() != package_sha:
        raise RecoveryError("post-result recovery package sidecar mismatch")
    if not preflight_sidecar.is_file() or preflight_sidecar.is_symlink() or preflight_sidecar.read_text(encoding='ascii').strip() != preflight_sha:
        raise RecoveryError("post-result recovery preflight sidecar mismatch")
    plan_sha = manifest.get("canonical_plan_sha256")
    worker_plan_sha = worker.get("plan_sha256") or worker.get("canonical_plan_sha256")
    worker_sha = hashlib.sha256(paths[2].read_bytes()).hexdigest()
    if (not isinstance(plan_sha, str) or not _SHA.fullmatch(plan_sha) or worker_plan_sha != plan_sha
            or preflight.get("package_manifest_sha256") != package_sha
            or worker.get("preflight_evidence_sha256") != preflight_sha
            or review_request.get("package_manifest_sha256") != package_sha
            or review_request.get("worker_result_sha256") != worker_sha
            or review_request.get("canonical_plan_sha256") != plan_sha):
        raise RecoveryError("post-result recovery evidence lineage mismatch")
    if worker.get("status") != "completed" or worker.get("completion_mode") != "GPT_OPERATOR_MANUAL_ACTION" or worker.get("hard_stop") is not True:
        raise RecoveryError("post-result recovery requires completed GPT manual-action evidence")
    rejected_attempt = worker.get("attempt")
    if not isinstance(rejected_attempt, int) or isinstance(rejected_attempt, bool) or rejected_attempt <= 0:
        raise RecoveryError("post-result recovery attempt is invalid")
    checkpoint = worker.get("checkpoint_commit"); baseline = worker.get("baseline_head")
    if not isinstance(checkpoint, str) or not re.fullmatch(r"[0-9a-f]{40,64}", checkpoint or ""):
        raise RecoveryError("post-result recovery checkpoint is invalid")
    if not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{40,64}", baseline or ""):
        raise RecoveryError("post-result recovery baseline is invalid")
    current_head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if subprocess.run(["git", "-C", str(project), "merge-base", "--is-ancestor", checkpoint, current_head], check=False).returncode != 0:
        raise RecoveryError("post-result recovery checkpoint is not an ancestor")
    owned = manifest.get("owned_files"); changed = worker.get("changed_files")
    if not isinstance(owned, list) or not owned or not isinstance(changed, list) or not changed:
        raise RecoveryError("post-result recovery scope evidence is incomplete")
    if any(not isinstance(item, str) or not _within_owned_scope(item, owned) for item in changed):
        raise RecoveryError("post-result recovery changed-file scope mismatch")
    checkpoint_files = set(filter(None, subprocess.run(["git", "-C", str(project), "diff-tree", "--no-commit-id", "--name-only", "-r", checkpoint], capture_output=True, text=True, check=True).stdout.splitlines()))
    if not set(changed).issubset(checkpoint_files):
        raise RecoveryError("post-result recovery checkpoint file evidence mismatch")
    later = set(filter(None, subprocess.run(["git", "-C", str(project), "diff", "--name-only", f"{checkpoint}..{current_head}"], capture_output=True, text=True, check=True).stdout.splitlines()))
    if any(_within_owned_scope(path, owned) for path in later):
        raise RecoveryError("post-result recovery checkpoint was invalidated by later owned-scope changes")
    relative_sources = [path.resolve().relative_to(root).as_posix() for path in paths]
    source_shas = {rel: hashlib.sha256(path.read_bytes()).hexdigest() for rel, path in zip(relative_sources, paths)}
    source = {"schema_version":"orchestration.post-result-missing-request-source.v1", **expected,
              "attempt":rejected_attempt, "canonical_plan_sha256":plan_sha,
              "approval_event_id":approval_event_id, "branch":branch,
              "baseline_head":baseline, "checkpoint_commit":checkpoint, "current_head":current_head,
              "owned_files":list(owned), "changed_files":list(changed),
              "package_manifest_sha256":package_sha, "preflight_evidence_sha256":preflight_sha,
              "worker_result_sha256":worker_sha, "review_request_sha256":source_shas[relative_sources[3]],
              "missing_bindings":["worker.request.json"], "completion_eligible":False, "hard_stop":True}
    source["source_payload_sha256"] = hashlib.sha256(_bytes(source)).hexdigest()
    source_path = package_root / "post-result-missing-request-source.json"
    if source_path.exists():
        if source_path.is_symlink() or not source_path.is_file():
            raise RecoveryError("post-result recovery source snapshot is unsafe")
        try:
            existing_source = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RecoveryError("post-result recovery source snapshot is malformed") from exc
        stable_keys = ("schema_version", "project_id", "gate_id", "lv_id", "run_id", "attempt",
                       "canonical_plan_sha256", "approval_event_id", "branch", "baseline_head",
                       "checkpoint_commit", "owned_files", "changed_files", "package_manifest_sha256",
                       "preflight_evidence_sha256", "worker_result_sha256", "review_request_sha256",
                       "missing_bindings", "completion_eligible", "hard_stop")
        if any(existing_source.get(key) != source.get(key) for key in stable_keys):
            raise RecoveryError("post-result recovery source snapshot replay conflict")
        expected_digest = existing_source.get("source_payload_sha256")
        if expected_digest != hashlib.sha256(_bytes({k:v for k,v in existing_source.items() if k != "source_payload_sha256"})).hexdigest():
            raise RecoveryError("post-result recovery source snapshot digest mismatch")
        source = existing_source
    else:
        _write_once(source_path, source)
    source_rel = source_path.resolve().relative_to(root).as_posix(); source_file_sha = hashlib.sha256(source_path.read_bytes()).hexdigest(); source_shas[source_rel] = source_file_sha
    record_current_head = str(source.get("current_head") or current_head)
    next_attempt = rejected_attempt + 1; recovery_id = f"{expected['run_id']}-recovery-{next_attempt:02d}"
    record = write_recovery_record(
        root, project_id=expected["project_id"], gate_id=expected["gate_id"], lv_id=expected["lv_id"], run_id=expected["run_id"],
        rejected_attempt=rejected_attempt, rejected_artifacts={source_rel:source_file_sha},
        reason_code="REJECTED_POST_RESULT_REQUEST_MISSING", missing_bindings=["worker.request.json"],
        recovery_attempt=next_attempt, approval_event_id=approval_event_id, plan_sha256=plan_sha,
        branch=branch, baseline_head=baseline, current_head=record_current_head,
        active_transition_sha256=source_file_sha, source_shas=source_shas, predecessor=None,
        supersedes=worker_sha, hard_stop=True, recovery_id=recovery_id,
        source_binding_kind="POST_RESULT_MISSING_REQUEST_SOURCE")
    checkpoint_payload = {"schema_version":"orchestration.production-recovery-checkpoint.v1", **expected,
        "recovery_id":record["recovery_id"], "rejected_attempt":rejected_attempt, "next_attempt":next_attempt,
        "recovery_record_hash":record["record_hash"], "completion_evidence":[],
        "status":"REJECTED_POST_RESULT_REQUEST_MISSING", "source_binding_kind":"POST_RESULT_MISSING_REQUEST_SOURCE", "hard_stop":True}
    checkpoint_payload["checkpoint_sha256"] = hashlib.sha256(_bytes(checkpoint_payload)).hexdigest()
    recovery_root = root / "_workspace" / "global-gate" / expected["project_id"] / "recovery"
    _write_once(recovery_root / f"{record['recovery_id']}.checkpoint.json", checkpoint_payload)
    return {"classification":{"status":"REJECTED_POST_RESULT_REQUEST_MISSING","completion_eligible":False,
            "missing_bindings":["worker.request.json"]}, "recovery":record, "checkpoint":checkpoint_payload,
            "next_attempt":next_attempt, "source":source, "source_path":str(source_path), "completion_evidence":[], "hard_stop":True}


def verify_post_result_checkpoint_recovery(*, project_root: str | Path,
                                           source_worker_path: str | Path,
                                           package_manifest_path: str | Path) -> dict[str, Any]:
    """Verify an already-committed worker checkpoint without mutating project files."""
    project = Path(project_root).resolve(); worker_path = Path(source_worker_path); manifest_path = Path(package_manifest_path)
    if not project.is_dir() or project.is_symlink() or not worker_path.is_file() or worker_path.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
        raise RecoveryError("checkpoint adoption recovery source is unsafe")
    worker = json.loads(worker_path.read_text(encoding="utf-8")); manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(worker, dict) or not isinstance(manifest, dict):
        raise RecoveryError("checkpoint adoption recovery source is malformed")
    checkpoint = worker.get("checkpoint_commit"); baseline = worker.get("baseline_head")
    current_head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if not isinstance(checkpoint, str) or subprocess.run(["git", "-C", str(project), "merge-base", "--is-ancestor", checkpoint, current_head], check=False).returncode != 0:
        raise RecoveryError("checkpoint adoption recovery checkpoint is invalid")
    owned = list(manifest.get("owned_files") or []); changed = list(worker.get("changed_files") or [])
    later = set(filter(None, subprocess.run(["git", "-C", str(project), "diff", "--name-only", f"{checkpoint}..{current_head}"], capture_output=True, text=True, check=True).stdout.splitlines()))
    if any(_within_owned_scope(path, owned) for path in later):
        raise RecoveryError("checkpoint adoption recovery owned scope was invalidated")
    source_commands = worker.get("commands")
    if not isinstance(source_commands, Mapping):
        raise RecoveryError("checkpoint adoption recovery command evidence is missing")
    commands: dict[str, Any] = {}
    provenance = subprocess.run(["git", "-C", str(project), "rev-parse", checkpoint], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    commands["checkpoint_provenance"] = {"command":["git","rev-parse",checkpoint], "exit_code":provenance.returncode, "timeout":False,
        "stdout_sha256":hashlib.sha256(provenance.stdout).hexdigest(), "stderr_sha256":hashlib.sha256(provenance.stderr).hexdigest()}
    if provenance.returncode != 0:
        raise RecoveryError("checkpoint adoption provenance verification failed")
    for key in ("focused_test", "full_regression", "compile_import", "git_diff_check"):
        item = source_commands.get(key); argv = item.get("command") if isinstance(item, Mapping) else None
        if not isinstance(argv, list):
            raise RecoveryError(f"checkpoint adoption command is missing: {key}")
        commands[key] = _run_checkpoint_verification_command(project, list(argv))
        if commands[key]["exit_code"] != 0 or commands[key]["timeout"]:
            raise RecoveryError(f"checkpoint adoption validation failed: {key}")
    status = subprocess.run(["git", "-C", str(project), "status", "--porcelain=v1", "-uall"], capture_output=True, text=True, check=True).stdout.strip()
    if status:
        raise RecoveryError("checkpoint adoption recovery requires a clean worktree")
    current_tree = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True, check=True).stdout.strip()
    return {"status":"completed", "plan_sha256":manifest.get("canonical_plan_sha256"),
            "completion_mode":"VERIFIED_CHECKPOINT_ADOPTION", "tests":list(worker.get("tests") or []),
            "owned_files":owned, "changed_files":changed, "baseline_head":baseline,
            "baseline_tree":worker.get("baseline_tree"), "current_head":current_head, "current_tree":current_tree,
            "checkpoint_commit":checkpoint, "commands":commands, "staged_changes":False, "unstaged_changes":False,
            "adoption":{"schema_version":"orchestration.verified-checkpoint-adoption.v1",
                        "checkpoint_commit":checkpoint, "approval_record_hash":manifest.get("approval_record_hash", "")},
            "artifact_sha_chain":{"source_worker":hashlib.sha256(worker_path.read_bytes()).hexdigest(),
                                  "package_manifest":hashlib.sha256(manifest_path.read_bytes()).hexdigest()},
            "executor":{"identity":"gpt-operator-recovery-verifier","version":"1"},
            "validation_events":["POST_RESULT_REQUEST_GAP_REJECTED","CHECKPOINT_PROVENANCE_VERIFIED","RECOVERY_VALIDATION_COMPLETED"]}


def prepare_completion_recovery(harness_root: str | Path, *, prior_record_path: str | Path,
                                rejection_path: str | Path) -> dict[str, Any]:
    """Advance exactly one attempt from an append-only completion rejection."""
    root=Path(harness_root).resolve(); prior_path=Path(prior_record_path); rejected_path=Path(rejection_path)
    for path in (prior_path,rejected_path):
        if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
            raise RecoveryError("unsafe completion recovery source")
    prior=json.loads(prior_path.read_text(encoding="utf-8")); rejected=json.loads(rejected_path.read_text(encoding="utf-8"))
    rejected_attempt=rejected.get("attempt"); next_attempt=rejected.get("next_attempt")
    if rejected.get("status") != "REJECTED_COMPLETION_UNPROVEN" or not isinstance(rejected_attempt,int) or next_attempt != rejected_attempt+1 or prior.get("recovery_attempt") != rejected_attempt:
        raise RecoveryError("completion recovery attempt sequence is invalid")
    keys=("project_id","gate_id","lv_id","run_id")
    if any(prior.get(k) != rejected.get(k) for k in keys): raise RecoveryError("completion recovery binding mismatch")
    relative=rejected_path.resolve().relative_to(root).as_posix(); digest=hashlib.sha256(rejected_path.read_bytes()).hexdigest()
    record=write_recovery_record(root,project_id=prior["project_id"],gate_id=prior["gate_id"],lv_id=prior["lv_id"],run_id=prior["run_id"],
        rejected_attempt=rejected_attempt,rejected_artifacts={relative:digest},reason_code="REJECTED_COMPLETION_UNPROVEN",
        missing_bindings=list(rejected.get("reasons",[])),recovery_attempt=next_attempt,approval_event_id=prior["approval_event_id"],
        plan_sha256=prior["plan_sha256"],branch=prior["branch"],baseline_head=prior["baseline_head"],current_head=prior["current_head"],
        active_transition_sha256=prior["active_transition_sha256"],source_shas={relative:digest},predecessor=prior["record_hash"],
        supersedes=rejected["record_hash"],hard_stop=True, source_binding_kind=prior.get("source_binding_kind", "ACTIVE_TRANSITION"))
    checkpoint={"schema_version":"orchestration.production-recovery-checkpoint.v1","project_id":prior["project_id"],"gate_id":prior["gate_id"],
        "lv_id":prior["lv_id"],"run_id":prior["run_id"],"recovery_id":record["recovery_id"],"rejected_attempt":rejected_attempt,
        "next_attempt":next_attempt,"recovery_record_hash":record["record_hash"],"completion_evidence":[],"status":"REJECTED_COMPLETION_UNPROVEN","hard_stop":True}
    checkpoint["checkpoint_sha256"]=hashlib.sha256(_bytes(checkpoint)).hexdigest()
    target=rejected_path.parent/f"{record['recovery_id']}.checkpoint.json"; _write_once(target,checkpoint)
    return {"classification":{"status":"REJECTED_COMPLETION_UNPROVEN","completion_eligible":False,"missing_bindings":list(rejected.get("reasons",[]))},
            "recovery":record,"checkpoint":checkpoint,"next_attempt":next_attempt,"completion_evidence":[],"hard_stop":True}

def execute_recovery_attempt(harness_root: str | Path, *, recovery_record_path: str | Path,
                             recovery_checkpoint_path: str | Path,
                             worker: Any) -> dict[str, Any]:
    """Execute package, preflight, and worker for the ledger-selected attempt.

    ``worker`` receives the sealed package and preflight objects and must return
    a mapping.  Every artifact is create-once and a replay must be byte-identical.
    """
    root = Path(harness_root).resolve()
    record_path, checkpoint_path = Path(recovery_record_path), Path(recovery_checkpoint_path)
    for path in (record_path, checkpoint_path):
        resolved = path.resolve()
        if not path.is_file() or path.is_symlink() or root not in resolved.parents:
            raise RecoveryError("unsafe recovery control artifact")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if record.get("record_hash") != hashlib.sha256(_bytes({k:v for k,v in record.items() if k != "record_hash"})).hexdigest():
        raise RecoveryError("recovery record hash mismatch")
    checkpoint_hash = checkpoint.get("checkpoint_sha256")
    if checkpoint_hash != hashlib.sha256(_bytes({k:v for k,v in checkpoint.items() if k != "checkpoint_sha256"})).hexdigest():
        raise RecoveryError("recovery checkpoint hash mismatch")
    attempt = record.get("recovery_attempt")
    if checkpoint.get("next_attempt") != attempt or not isinstance(attempt, int) or attempt <= record.get("rejected_attempt", 0):
        raise RecoveryError("recovery attempt sequence is invalid")
    run_root = root / "_workspace" / "orchestration-runs" / record["run_id"]
    attempt_root = run_root / attempt_directory(attempt)
    # Attempt numbers are monotonic per LV; shared run roots may contain the
    # same number for a different LV.  Namespace only on a binding collision.
    existing_package = attempt_root / "package.json"
    if existing_package.is_file():
        try:
            existing_binding = json.loads(existing_package.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise RecoveryError("recovery attempt package is malformed")
        if existing_binding.get("lv_id") != record.get("lv_id"):
            attempt_root = run_root / f"{attempt_directory(attempt)}-{record['lv_id']}"
    binding = canonical_recovery_binding(record, checkpoint)
    package = {"schema_version":"orchestration.recovery-package.v1", **binding,
               "branch":record.get("branch"), "baseline_head":record.get("baseline_head"),
               "current_head":record.get("current_head"),
               "recovery_reason_code":record.get("rejection_reason_code"),
               "recovery_source_kind":record.get("source_binding_kind", "ACTIVE_TRANSITION")}
    package["package_sha256"] = hashlib.sha256(_bytes(package)).hexdigest()
    package_path = attempt_root / "package.json"
    if package_path.exists():
        existing = json.loads(package_path.read_text(encoding="utf-8"))
        if existing.get("package_sha256") != hashlib.sha256(_bytes({k:v for k,v in existing.items() if k != "package_sha256"})).hexdigest():
            raise RecoveryError("recovery package hash mismatch")
        if any(existing.get(k) != binding.get(k) for k in binding):
            raise RecoveryError("recovery package binding mismatch")
        package = existing
    else:
        _write_once(package_path, package)
    preflight = {"schema_version":"orchestration.recovery-preflight.v1", **binding,
                 "package_sha256":package["package_sha256"], "status":"READY"}
    preflight["preflight_sha256"] = hashlib.sha256(_bytes(preflight)).hexdigest()
    preflight_path = attempt_root / "preflight.json"
    if preflight_path.exists():
        existing = json.loads(preflight_path.read_text(encoding="utf-8"))
        if existing.get("preflight_sha256") != hashlib.sha256(_bytes({k:v for k,v in existing.items() if k != "preflight_sha256"})).hexdigest():
            raise RecoveryError("recovery preflight hash mismatch")
        preflight = existing
    else:
        _write_once(preflight_path, preflight)
    existing_result = attempt_root / "worker.result.json"
    if existing_result.exists():
        result = json.loads(existing_result.read_text(encoding="utf-8"))
    else:
        raw = worker(dict(package), dict(preflight))
        if not isinstance(raw, Mapping):
            raise RecoveryError("recovery worker result must be an object")
        conflicts = [key for key, value in binding.items() if key in raw and raw[key] != value]
        if conflicts:
            raise RecoveryError(f"recovery worker canonical binding conflict: {', '.join(sorted(conflicts))}")
        result = {"schema_version":"orchestration.recovery-worker-result.v1", **dict(raw), **binding,
                  "package_sha256":package["package_sha256"],
                  "preflight_sha256":preflight["preflight_sha256"],
                  # Canonical producer binding (distinct from the internal
                  # recovery preflight field retained for lineage checks).
                  "preflight_evidence_sha256":preflight["preflight_sha256"]}
        if result.get("status") not in {"completed", "failed", "blocked"}:
            raise RecoveryError("recovery worker status is invalid")
        result["worker_result_sha256"] = hashlib.sha256(_bytes(result)).hexdigest()
        _write_once(existing_result, result)
    expected = {**binding, "package_sha256":package["package_sha256"],
                "preflight_sha256":preflight["preflight_sha256"],
                "preflight_evidence_sha256":preflight["preflight_sha256"]}
    if any(result.get(key) != value for key, value in expected.items()):
        raise RecoveryError("recovery worker binding mismatch")
    digest = result.get("worker_result_sha256")
    if digest != hashlib.sha256(_bytes({k:v for k,v in result.items() if k != "worker_result_sha256"})).hexdigest():
        raise RecoveryError("recovery worker result hash mismatch")
    return {"package":package, "preflight":preflight, "worker_result":result,
            "attempt_root":str(attempt_root), "hard_stop":True}

def review_recovery_attempt(harness_root: str | Path, *, recovery_record_path: str | Path,
                            recovery_checkpoint_path: str | Path, reviewer: Any) -> dict[str, Any]:
    """Validate one attempt lineage and append its independent review/consumption."""
    root = Path(harness_root).resolve()
    record_path, checkpoint_path = Path(recovery_record_path), Path(recovery_checkpoint_path)
    for path in (record_path, checkpoint_path):
        if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
            raise RecoveryError("unsafe recovery review control artifact")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if record.get("record_hash") != hashlib.sha256(_bytes({k:v for k,v in record.items() if k != "record_hash"})).hexdigest():
        raise RecoveryError("recovery record hash mismatch")
    if checkpoint.get("checkpoint_sha256") != hashlib.sha256(_bytes({k:v for k,v in checkpoint.items() if k != "checkpoint_sha256"})).hexdigest():
        raise RecoveryError("recovery checkpoint hash mismatch")
    binding = canonical_recovery_binding(record, checkpoint)
    attempt_root = root / "_workspace" / "orchestration-runs" / record["run_id"] / attempt_directory(record["recovery_attempt"])
    if not (attempt_root / "package.json").is_file() or json.loads((attempt_root / "package.json").read_text(encoding="utf-8")).get("lv_id") != record.get("lv_id"):
        candidate = attempt_root.parent / f"{attempt_directory(record['recovery_attempt'])}-{record['lv_id']}"
        if (candidate / "package.json").is_file():
            attempt_root = candidate
    artifacts: dict[str, dict[str, Any]] = {}
    for name in ("package.json", "preflight.json", "worker.result.json"):
        path = attempt_root / name
        if not path.is_file() or path.is_symlink():
            raise RecoveryError(f"recovery review artifact is missing or unsafe: {name}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or any(value.get(key) != expected for key, expected in binding.items()):
            raise RecoveryError(f"recovery review canonical binding mismatch: {name}")
        artifacts[name] = value
    package, preflight, worker_result = (artifacts[name] for name in ("package.json", "preflight.json", "worker.result.json"))
    if package.get("package_sha256") != hashlib.sha256(_bytes({k:v for k,v in package.items() if k != "package_sha256"})).hexdigest():
        raise RecoveryError("recovery review package hash mismatch")
    if preflight.get("package_sha256") != package["package_sha256"] or preflight.get("preflight_sha256") != hashlib.sha256(_bytes({k:v for k,v in preflight.items() if k != "preflight_sha256"})).hexdigest():
        raise RecoveryError("recovery review preflight lineage mismatch")
    worker_sha = worker_result.get("worker_result_sha256")
    if worker_result.get("package_sha256") != package["package_sha256"] or worker_result.get("preflight_sha256") != preflight["preflight_sha256"] or worker_result.get("preflight_evidence_sha256") != preflight["preflight_sha256"] or worker_sha != hashlib.sha256(_bytes({k:v for k,v in worker_result.items() if k != "worker_result_sha256"})).hexdigest():
        raise RecoveryError("recovery review worker lineage mismatch")
    existing = attempt_root / "review.json"
    if existing.exists():
        review = json.loads(existing.read_text(encoding="utf-8"))
    else:
        raw = reviewer(dict(worker_result), dict(binding))
        if not isinstance(raw, Mapping) or raw.get("verdict") not in {"PASS", "FAIL"}:
            raise RecoveryError("recovery reviewer verdict is invalid")
        review = {"schema_version":"orchestration.recovery-review.v1", **binding,
                  "package_sha256":package["package_sha256"], "preflight_sha256":preflight["preflight_sha256"],
                  "worker_result_sha256":worker_sha, "verdict":raw["verdict"],
                  "findings":list(raw.get("findings", [])), "consumption_eligible":raw["verdict"] == "PASS"}
        review["review_sha256"] = hashlib.sha256(_bytes(review)).hexdigest()
        _write_once(existing, review)
    if review.get("review_sha256") != hashlib.sha256(_bytes({k:v for k,v in review.items() if k != "review_sha256"})).hexdigest():
        raise RecoveryError("recovery review hash mismatch")
    consumption = None
    if review.get("verdict") == "PASS" and review.get("consumption_eligible") is True:
        consumption = {"schema_version":"orchestration.recovery-consumption.v1", **binding,
                       "review_sha256":review["review_sha256"], "worker_result_sha256":worker_sha,
                       "status":"CONSUMED", "completion_eligible":True}
        consumption["consumption_sha256"] = hashlib.sha256(_bytes(consumption)).hexdigest()
        _write_once(attempt_root / "consumption.json", consumption)
    return {"review":review, "consumption":consumption, "hard_stop":True}

def finalize_recovery_lifecycle(harness_root: str | Path, *, run_id: str, attempt: int = 2,
                                remaining_lvs: list[str], gate_complete: bool, lv_id: str | None = None) -> dict[str, Any]:
    """Seal checkpoint, LV exit, optional Gate exit, and structured handoff."""
    root = Path(harness_root).resolve()
    attempt_root = root / "_workspace" / "orchestration-runs" / run_id / attempt_directory(attempt)
    package_path = attempt_root / "package.json"
    if package_path.is_file():
        try:
            package_value = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            package_value = {}
        # Locate a namespaced LV attempt when the shared numeric directory is
        # occupied by another recovery lineage.
        if lv_id and package_value.get("lv_id") and package_value.get("lv_id") != lv_id:
            matches = sorted(attempt_root.parent.glob(f"{attempt_directory(attempt)}-*"))
            for candidate in matches:
                if (candidate / "consumption.json").is_file():
                    attempt_root = candidate; break
    consumption_path = attempt_root / "consumption.json"
    if not consumption_path.is_file() or consumption_path.is_symlink():
        raise RecoveryError("reviewed recovery consumption is required")
    consumption = json.loads(consumption_path.read_text(encoding="utf-8"))
    if consumption.get("status") != "CONSUMED" or consumption.get("completion_eligible") is not True:
        raise RecoveryError("recovery consumption is not completion-eligible")
    digest = consumption.get("consumption_sha256")
    if digest != hashlib.sha256(_bytes({k:v for k,v in consumption.items() if k != "consumption_sha256"})).hexdigest():
        raise RecoveryError("recovery consumption hash mismatch")
    binding_keys = ("project_id","gate_id","lv_id","run_id","recovery_id","attempt",
                    "canonical_plan_sha256","approval_event_id","active_transition_sha256",
                    "recovery_record_hash","recovery_checkpoint_sha256","hard_stop")
    binding = {key:consumption[key] for key in binding_keys}
    checkpoint = {"schema_version":"orchestration.recovery-lifecycle-checkpoint.v1", **binding,
                  "consumption_sha256":digest, "status":"CHECKPOINTED"}
    checkpoint["lifecycle_checkpoint_sha256"] = hashlib.sha256(_bytes(checkpoint)).hexdigest()
    _write_once(attempt_root / "lifecycle.checkpoint.json", checkpoint)
    lv_exit = {"schema_version":"orchestration.recovery-lv-exit.v1", **binding,
               "lifecycle_checkpoint_sha256":checkpoint["lifecycle_checkpoint_sha256"], "status":"EXITED"}
    lv_exit["lv_exit_sha256"] = hashlib.sha256(_bytes(lv_exit)).hexdigest()
    _write_once(attempt_root / "lv.exit.json", lv_exit)
    if gate_complete != (len(remaining_lvs) == 0):
        raise RecoveryError("Gate completeness and remaining LV set disagree")
    gate_exit = None
    if gate_complete:
        gate_exit = {"schema_version":"orchestration.recovery-gate-exit.v1", **binding,
                     "lv_exit_sha256":lv_exit["lv_exit_sha256"], "status":"EXITED",
                     "next_gate_status":"USER_APPROVAL_REQUIRED"}
        gate_exit["gate_exit_sha256"] = hashlib.sha256(_bytes(gate_exit)).hexdigest()
        _write_once(attempt_root / "gate.exit.json", gate_exit)
    handoff = {"schema_version":"orchestration.recovery-handoff.v1", **binding,
               "lifecycle_checkpoint_sha256":checkpoint["lifecycle_checkpoint_sha256"],
               "lv_exit_sha256":lv_exit["lv_exit_sha256"], "remaining_lvs":list(remaining_lvs),
               "next_lv":remaining_lvs[0] if remaining_lvs else None,
               "gate_complete":gate_complete,
               "gate_exit_sha256":gate_exit["gate_exit_sha256"] if gate_exit else None,
               "next_gate_status":"USER_APPROVAL_REQUIRED" if gate_complete else None,
               "status":"SEALED"}
    handoff["handoff_sha256"] = hashlib.sha256(_bytes(handoff)).hexdigest()
    _write_once(attempt_root / "handoff.json", handoff)
    return {"checkpoint":checkpoint,"lv_exit":lv_exit,"gate_exit":gate_exit,"handoff":handoff,"hard_stop":True}
