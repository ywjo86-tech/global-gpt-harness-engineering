"""Append-only recovery records for rejected partial production attempts."""
from __future__ import annotations
import hashlib, json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

class RecoveryError(ValueError): pass

def _bytes(v: object) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def write_recovery_record(harness_root: str | Path, *, project_id: str, gate_id: str, lv_id: str, run_id: str,
                          rejected_attempt: int, rejected_artifacts: Mapping[str, str], reason_code: str,
                          missing_bindings: list[str], recovery_attempt: int, approval_event_id: str,
                          plan_sha256: str, branch: str, baseline_head: str, current_head: str,
                          active_transition_sha256: str, source_shas: Mapping[str, str], predecessor: str | None,
                          supersedes: str, hard_stop: bool = True) -> dict[str, Any]:
    if rejected_attempt <= 0 or recovery_attempt <= rejected_attempt or not hard_stop:
        raise RecoveryError("invalid recovery attempt or hard-stop binding")
    if not all(isinstance(v, str) and v for v in (project_id, gate_id, lv_id, run_id, reason_code, approval_event_id, plan_sha256, branch, baseline_head, current_head, active_transition_sha256, supersedes)):
        raise RecoveryError("recovery binding is incomplete")
    for path, digest in {**rejected_artifacts, **source_shas}.items():
        p = Path(path)
        if p.is_absolute() or ".." in p.parts or not isinstance(digest, str) or len(digest) != 64:
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
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return payload
