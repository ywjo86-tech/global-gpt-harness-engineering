"""Atomic persisted lifecycle artifacts with detached, byte-bound sidecars."""
from __future__ import annotations
import hashlib, json, os, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .lifecycle_binding import canonical_bytes

class PersistedArtifactError(ValueError): pass

KINDS=frozenset({"package","preflight","worker_request","worker_result","review","checkpoint","lv_exit","gate_completeness","gate_checkpoint","gate_exit","handoff","recovery_successor","partial_adoption"})
SCHEMA="orchestration.persisted-artifact.v1"
SIDECAR_SCHEMA="orchestration.persisted-sidecar.v1"

def _digest(data: bytes) -> str: return hashlib.sha256(data).hexdigest()

def _safe(root: Path, relative: str) -> Path:
    pure=PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts or pure.as_posix()!=relative:
        raise PersistedArtifactError("unsafe artifact path")
    root=root.resolve(); target=root.joinpath(*pure.parts)
    parent=target.parent.resolve()
    if root != parent and root not in parent.parents: raise PersistedArtifactError("artifact traversal")
    if target.is_symlink() or any(part.is_symlink() for part in [target.parent]): raise PersistedArtifactError("artifact symlink")
    return target

def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f: f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
        dfd=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def publish(root: str|Path, relative: str, *, kind: str, payload: Mapping[str,Any],
            binding: Mapping[str,Any], source_artifact_sha256: str,
            predecessor_digest: str) -> tuple[Path,Path]:
    if kind not in KINDS: raise PersistedArtifactError("unsupported artifact schema")
    target=_safe(Path(root),relative)
    body={"schema_version":SCHEMA,"kind":kind,"binding":dict(binding),"payload":dict(payload)}
    raw=canonical_bytes(body); projection=canonical_bytes({"kind":kind,"binding":dict(binding),"payload":dict(payload)})
    side={"schema_version":SIDECAR_SCHEMA,"kind":kind,"raw_payload_sha256":_digest(raw),
          "projection_sha256":_digest(b"projection\0"+projection),
          "source_artifact_sha256":source_artifact_sha256,"predecessor_digest":predecessor_digest,
          "envelope_sha256":_digest(b"envelope\0"+raw)}
    side_raw=canonical_bytes(side); side["sidecar_sha256"]=_digest(b"sidecar\0"+side_raw)
    _atomic(target,raw); _atomic(target.with_suffix(target.suffix+".sidecar.json"),canonical_bytes(side))
    return target,target.with_suffix(target.suffix+".sidecar.json")

@dataclass(frozen=True)
class ValidatedArtifact:
    kind:str; payload:Mapping[str,Any]; binding:Mapping[str,Any]; raw_bytes:bytes
    raw_payload_sha256:str; projection_sha256:str; sidecar_sha256:str; envelope_sha256:str

def validate(root: str|Path, relative: str, *, expected_kind: str,
             expected_binding: Mapping[str,Any], expected_source_sha256: str,
             expected_predecessor: str, after_open:Callable[[Path],None]|None=None) -> ValidatedArtifact:
    target=_safe(Path(root),relative); sidepath=_safe(Path(root),relative+".sidecar.json")
    if not target.is_file() or not sidepath.is_file(): raise PersistedArtifactError("artifact or sidecar missing")
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)
    fd=os.open(target,flags); sfd=os.open(sidepath,flags)
    try:
        st=os.fstat(fd);sst=os.fstat(sfd)
        raw=os.read(fd,st.st_size+1); side_raw=os.read(sfd,sst.st_size+1)
        if after_open: after_open(target)
        if os.fstat(fd).st_ino!=st.st_ino or os.fstat(sfd).st_ino!=sst.st_ino: raise PersistedArtifactError("artifact changed while validating")
    finally: os.close(fd);os.close(sfd)
    try: body=json.loads(raw);side=json.loads(side_raw)
    except (UnicodeError,json.JSONDecodeError) as exc: raise PersistedArtifactError("corrupt artifact JSON") from exc
    if not isinstance(body,dict) or set(body)!={"schema_version","kind","binding","payload"} or body.get("schema_version")!=SCHEMA or body.get("kind")!=expected_kind:
        raise PersistedArtifactError("unsupported artifact schema")
    required={"schema_version","kind","raw_payload_sha256","projection_sha256","source_artifact_sha256","predecessor_digest","envelope_sha256","sidecar_sha256"}
    if not isinstance(side,dict) or set(side)!=required or side.get("schema_version")!=SIDECAR_SCHEMA or side.get("kind")!=expected_kind:
        raise PersistedArtifactError("invalid detached sidecar")
    unsigned={k:v for k,v in side.items() if k!="sidecar_sha256"}
    checks={"raw_payload_sha256":_digest(raw),"projection_sha256":_digest(b"projection\0"+canonical_bytes({"kind":expected_kind,"binding":body["binding"],"payload":body["payload"]})),
            "envelope_sha256":_digest(b"envelope\0"+raw),"sidecar_sha256":_digest(b"sidecar\0"+canonical_bytes(unsigned)),
            "source_artifact_sha256":expected_source_sha256,"predecessor_digest":expected_predecessor}
    if any(side.get(k)!=v for k,v in checks.items()): raise PersistedArtifactError("persisted artifact digest binding mismatch")
    if canonical_bytes(body["binding"])!=canonical_bytes(expected_binding): raise PersistedArtifactError("persisted artifact lifecycle binding mismatch")
    return ValidatedArtifact(expected_kind,body["payload"],body["binding"],raw,side["raw_payload_sha256"],side["projection_sha256"],side["sidecar_sha256"],side["envelope_sha256"])
