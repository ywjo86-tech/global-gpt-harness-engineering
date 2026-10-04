"""Governed P4 preflight, cutover admission, atomic switch, and rollback drill."""
from __future__ import annotations

import hashlib, json, os, re, subprocess
from pathlib import Path
from typing import Any, Mapping

from .runtime_release import _active_registered_jobs, activate_runtime_release, verify_runtime_release

_SHA = re.compile(r"[0-9a-f]{64}\Z")

class P4TransitionError(ValueError): pass

def _canonical(v: object) -> bytes:
    return json.dumps(v, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()

def _digest(v: object) -> str: return hashlib.sha256(_canonical(v)).hexdigest()

def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file(): raise P4TransitionError("required receipt missing")
    value=json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes()!=_canonical(value): raise P4TransitionError("noncanonical receipt")
    return value

def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload=_canonical(value)
    if path.exists():
        if path.is_symlink() or path.read_bytes()!=payload: raise P4TransitionError("receipt conflict")
        return
    fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as f: f.write(payload); f.flush(); os.fsync(f.fileno())

def prepare_p4_cutover(*, state_root: str|Path, runtime_link: str|Path, source_release: str|Path,
                       target_release: str|Path, target_head: str, admission_digest: str,
                       qualification_digest: str, p4_entry_digest: str,
                       job_search_root: str|Path) -> dict[str, Any]:
    state=Path(state_root).absolute(); link=Path(runtime_link).absolute()
    if not _SHA.fullmatch(admission_digest) or not _SHA.fullmatch(qualification_digest) or not _SHA.fullmatch(p4_entry_digest): raise P4TransitionError("invalid lineage digest")
    entry=_read(state/"p4-read-only-entries"/f"{admission_digest}.json")
    qualification=_read(state/"p3-final-qualifications"/f"{admission_digest}.json")
    if entry.get("entry_digest")!=p4_entry_digest or entry.get("qualification_digest")!=qualification_digest or qualification.get("qualification_digest")!=qualification_digest or entry.get("status")!="P4_READ_ONLY_ENTERED": raise P4TransitionError("P4 lineage mismatch")
    source=verify_runtime_release(source_release, Path(source_release).name)
    target=verify_runtime_release(target_release,target_head)
    blockers=[]
    if not link.is_symlink() or link.resolve(strict=True).resolve()!=Path(source.release_path).resolve(): blockers.append("RUNTIME_CURRENT_SOURCE_MISMATCH")
    jobs=_active_registered_jobs(job_search_root)
    blockers.extend(f"ACTIVE_RUN:{j.project_id}:{j.run_id}:{j.state}" for j in jobs)
    for unit in ("ocpv2.service","ocpv2.timer","ocpv2-lifecycle-v2-p2.service","ocpv2-lifecycle-v2-p2.timer"):
        active=subprocess.run(["systemctl","--user","is-active","--quiet",unit],check=False).returncode==0
        if active: blockers.append(f"ACTIVE_UNIT:{unit}")
    unsigned={"schema_version":"orchestration.lifecycle-v2-p4-cutover-admission.v1","admission_digest":admission_digest,"qualification_digest":qualification_digest,"p4_entry_digest":p4_entry_digest,"source_head":source.source_head,"source_manifest_sha256":source.manifest_sha256,"target_head":target.source_head,"target_manifest_sha256":target.manifest_sha256,"blockers":blockers,"runtime_current_switch_authorized":not blockers,"predecessor_shutdown_authorized":False,"existing_run_migration_authorized":False,"successor_polling_authorized":False,"status":"P4_CUTOVER_READY" if not blockers else "P4_CUTOVER_BLOCKED"}
    receipt={**unsigned,"cutover_admission_digest":_digest(unsigned)}
    _write_once(state/"p4-cutover-admissions"/f"{admission_digest}.json",receipt)
    return receipt

def execute_p4_cutover(*, state_root: str|Path, runtime_link: str|Path, source_release: str|Path,
                       target_release: str|Path, target_head: str, admission_digest: str,
                       cutover_admission_digest: str, job_search_root: str|Path) -> dict[str, Any]:
    state=Path(state_root).absolute(); admission=_read(state/"p4-cutover-admissions"/f"{admission_digest}.json")
    if admission.get("status")!="P4_CUTOVER_READY" or admission.get("runtime_current_switch_authorized") is not True or admission.get("cutover_admission_digest")!=cutover_admission_digest: raise P4TransitionError("cutover is not admitted")
    source=verify_runtime_release(source_release,Path(source_release).name); target=verify_runtime_release(target_release,target_head)
    link=Path(runtime_link).absolute()
    activate_runtime_release(target,link,job_search_root=job_search_root)
    activate_runtime_release(source,link,job_search_root=job_search_root)
    rollback_verified=link.resolve(strict=True)==Path(source.release_path).resolve()
    if not rollback_verified: raise P4TransitionError("rollback drill failed")
    activate_runtime_release(target,link,job_search_root=job_search_root)
    if link.resolve(strict=True)!=Path(target.release_path).resolve(): raise P4TransitionError("target activation failed")
    unsigned={"schema_version":"orchestration.lifecycle-v2-p4-cutover-result.v1","admission_digest":admission_digest,"cutover_admission_digest":cutover_admission_digest,"source_manifest_sha256":source.manifest_sha256,"target_manifest_sha256":target.manifest_sha256,"rollback_verified":True,"runtime_current_switched":True,"predecessor_shutdown_performed":False,"existing_run_migration_performed":False,"successor_polling_enabled":False,"status":"P4_CUTOVER_COMPLETE"}
    result={**unsigned,"result_digest":_digest(unsigned)}; _write_once(state/"p4-cutover-results"/f"{admission_digest}.json",result); return result
