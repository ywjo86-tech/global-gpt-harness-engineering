"""Append-only recovery records for rejected partial production attempts."""
from __future__ import annotations
import hashlib, json, os, re, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

class RecoveryError(ValueError): pass
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")

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

def write_recovery_record(harness_root: str | Path, *, project_id: str, gate_id: str, lv_id: str, run_id: str,
                          rejected_attempt: int, rejected_artifacts: Mapping[str, str], reason_code: str,
                          missing_bindings: list[str], recovery_attempt: int, approval_event_id: str,
                          plan_sha256: str, branch: str, baseline_head: str, current_head: str,
                          active_transition_sha256: str, source_shas: Mapping[str, str], predecessor: str | None,
                          supersedes: str, hard_stop: bool = True) -> dict[str, Any]:
    if rejected_attempt <= 0 or recovery_attempt <= rejected_attempt or not hard_stop:
        raise RecoveryError("invalid recovery attempt or hard-stop binding")
    if not all(isinstance(v, str) and v for v in (project_id, gate_id, lv_id, run_id, reason_code, approval_event_id, plan_sha256, branch, baseline_head, current_head, active_transition_sha256, supersedes)) or not all(_ID.fullmatch(v) for v in (project_id, gate_id, lv_id, run_id, reason_code, approval_event_id, branch, supersedes)):
        raise RecoveryError("recovery binding is incomplete")
    for path, digest in {**rejected_artifacts, **source_shas}.items():
        p = Path(path)
        if p.is_absolute() or ".." in p.parts or not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise RecoveryError("invalid recovery source path or SHA")
    payload = {"schema_version":"orchestration.production-recovery.v1","recovery_id":f"{run_id}-recovery-{recovery_attempt:02d}","project_id":project_id,"gate_id":gate_id,"lv_id":lv_id,"run_id":run_id,"rejected_attempt":rejected_attempt,"rejected_artifacts":dict(rejected_artifacts),"rejection_reason_code":reason_code,"missing_bindings":list(missing_bindings),"recovery_attempt":recovery_attempt,"approval_event_id":approval_event_id,"plan_sha256":plan_sha256,"branch":branch,"baseline_head":baseline_head,"current_head":current_head,"active_transition_sha256":active_transition_sha256,"source_shas":dict(source_shas),"predecessor":predecessor,"supersedes":supersedes,"created_at":datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),"hard_stop":True}
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
    missing = [field for field in ("project_id", "canonical_plan_sha256", "hard_stop") if not manifest.get(field) and field != "hard_stop"]
    if worker is None:
        missing.append("worker.result")
    else:
        missing.extend(field for field in ("project_id", "canonical_plan_sha256", "hard_stop") if not worker.get(field))
    return {"status": "REJECTED_UNBOUND_LEGACY" if missing else "BOUND", "missing_bindings": sorted(set(missing)), "completion_eligible": not missing}

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
    if worker.get("attempt") != 1:
        raise RecoveryError("partial worker attempt is not the rejected first attempt")
    classification = classify_partial_attempt(manifest, worker)
    if classification["status"] != "REJECTED_UNBOUND_LEGACY":
        raise RecoveryError("partial attempt is not eligible for legacy recovery")
    relative = [path.resolve().relative_to(root).as_posix() for path in paths]
    shas = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in zip(relative, paths)}
    run_id = expected["run_id"]
    recovery_id = f"{run_id}-recovery-02"
    recovery_root = root / "_workspace" / "global-gate" / expected["project_id"] / "recovery"
    if recovery_root.is_symlink():
        raise RecoveryError("recovery root must not be a symlink")
    if recovery_root.is_dir():
        for candidate in recovery_root.glob(f"{run_id}-recovery-*.json"):
            if candidate.name.endswith(".checkpoint.json"):
                continue
            if candidate.name != f"{recovery_id}.json":
                raise RecoveryError("conflicting active recovery exists")
    transition_sha = shas[relative[2]]
    record = write_recovery_record(
        root, project_id=expected["project_id"], gate_id=expected["gate_id"],
        lv_id=expected["lv_id"], run_id=run_id, rejected_attempt=1,
        rejected_artifacts={relative[0]: shas[relative[0]], relative[1]: shas[relative[1]]},
        reason_code=classification["status"], missing_bindings=classification["missing_bindings"],
        recovery_attempt=2, approval_event_id=approval_event_id,
        plan_sha256=str(manifest.get("canonical_plan_sha256", "")),
        branch=str(transition.get("branch", "")), baseline_head=str(transition.get("baseline_head", "")),
        current_head=str(transition.get("current_head", "")), active_transition_sha256=transition_sha,
        source_shas=shas, predecessor=None, supersedes=shas[relative[1]], hard_stop=True,
    )
    checkpoint = {
        "schema_version": "orchestration.production-recovery-checkpoint.v1",
        "project_id": expected["project_id"], "gate_id": expected["gate_id"],
        "lv_id": expected["lv_id"], "run_id": run_id, "recovery_id": record["recovery_id"],
        "rejected_attempt": 1, "next_attempt": 2, "recovery_record_hash": record["record_hash"],
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
            "next_attempt": 2, "completion_evidence": [], "hard_stop": True}

def execute_recovery_attempt(harness_root: str | Path, *, recovery_record_path: str | Path,
                             recovery_checkpoint_path: str | Path,
                             worker: Any) -> dict[str, Any]:
    """Execute package, preflight, and worker for attempt 2 in the existing run.

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
    keys = ("project_id", "gate_id", "lv_id", "run_id", "recovery_id")
    if any(record.get(key) != checkpoint.get(key) for key in keys):
        raise RecoveryError("recovery control binding mismatch")
    if checkpoint.get("next_attempt") != 2 or record.get("recovery_attempt") != 2:
        raise RecoveryError("recovery attempt must be 2")
    run_root = root / "_workspace" / "orchestration-runs" / record["run_id"]
    attempt_root = run_root / "attempt-02"
    binding = {key: record[key] for key in ("project_id", "gate_id", "lv_id", "run_id")}
    binding.update({
        "attempt": 2, "recovery_id": record["recovery_id"],
        "recovery_record_hash": record["record_hash"],
        "recovery_checkpoint_sha256": checkpoint_hash,
        "canonical_plan_sha256": record["plan_sha256"], "hard_stop": True,
    })
    package = {"schema_version":"orchestration.recovery-package.v1", **binding}
    package["package_sha256"] = hashlib.sha256(_bytes(package)).hexdigest()
    _write_once(attempt_root / "package.json", package)
    preflight = {"schema_version":"orchestration.recovery-preflight.v1", **binding,
                 "package_sha256":package["package_sha256"], "status":"READY"}
    preflight["preflight_sha256"] = hashlib.sha256(_bytes(preflight)).hexdigest()
    _write_once(attempt_root / "preflight.json", preflight)
    existing_result = attempt_root / "worker.result.json"
    if existing_result.exists():
        result = json.loads(existing_result.read_text(encoding="utf-8"))
    else:
        raw = worker(dict(package), dict(preflight))
        if not isinstance(raw, Mapping):
            raise RecoveryError("recovery worker result must be an object")
        result = {"schema_version":"orchestration.recovery-worker-result.v1", **binding,
                  "package_sha256":package["package_sha256"],
                  "preflight_sha256":preflight["preflight_sha256"], **dict(raw)}
        if result.get("status") not in {"completed", "failed", "blocked"}:
            raise RecoveryError("recovery worker status is invalid")
        result["worker_result_sha256"] = hashlib.sha256(_bytes(result)).hexdigest()
        _write_once(existing_result, result)
    expected = {**binding, "package_sha256":package["package_sha256"],
                "preflight_sha256":preflight["preflight_sha256"]}
    if any(result.get(key) != value for key, value in expected.items()):
        raise RecoveryError("recovery worker binding mismatch")
    digest = result.get("worker_result_sha256")
    if digest != hashlib.sha256(_bytes({k:v for k,v in result.items() if k != "worker_result_sha256"})).hexdigest():
        raise RecoveryError("recovery worker result hash mismatch")
    return {"package":package, "preflight":preflight, "worker_result":result,
            "attempt_root":str(attempt_root), "hard_stop":True}
