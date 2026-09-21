"""Immutable run-supersession evidence for Attention archival decisions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .durable_io import atomic_write_json

SCHEMA_VERSION = "orchestration.run-supersession.v1"
CONTROL_AUTHORITY = "NONE"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,179}\Z")
_TERMINAL = frozenset({"BLOCKED","FAILED","COMPLETED","CANCELLED"})


class RunSupersessionError(ValueError):
    pass


def _digest(value: object) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(value: object, label: str) -> str:
    text=str(value or "")
    if _SAFE.fullmatch(text) is None: raise RunSupersessionError(f"invalid {label}")
    return text


def _sha(value: object, label: str) -> str:
    text=str(value or "")
    if _SHA256.fullmatch(text) is None: raise RunSupersessionError(f"invalid {label}")
    return text


@dataclass(frozen=True,slots=True)
class RunSupersessionRecord:
    schema_version:str
    project_id:str
    predecessor_run_id:str
    predecessor_authority_sha256:str
    successor_run_id:str
    successor_authority_sha256:str
    reason:str
    evidence_refs:tuple[str,...]
    created_at:str
    control_authority:str
    record_sha256:str

    @classmethod
    def create(cls,*,project_id:str,predecessor_run_id:str,predecessor_authority_sha256:str,
               successor_run_id:str,successor_authority_sha256:str,reason:str,
               evidence_refs:Sequence[str]) -> "RunSupersessionRecord":
        predecessor=_id(predecessor_run_id,"predecessor run ID"); successor=_id(successor_run_id,"successor run ID")
        if predecessor==successor: raise RunSupersessionError("successor must differ from predecessor")
        refs=tuple(str(x).strip() for x in evidence_refs if str(x).strip())
        if not refs or len(refs)!=len(set(refs)): raise RunSupersessionError("supersession evidence refs are invalid")
        reason_text=str(reason or "").strip()
        if not reason_text or len(reason_text)>512: raise RunSupersessionError("supersession reason is invalid")
        unsigned={
            "schema_version":SCHEMA_VERSION,"project_id":_id(project_id,"project ID"),
            "predecessor_run_id":predecessor,"predecessor_authority_sha256":_sha(predecessor_authority_sha256,"predecessor authority"),
            "successor_run_id":successor,"successor_authority_sha256":_sha(successor_authority_sha256,"successor authority"),
            "reason":reason_text,"evidence_refs":list(refs),"created_at":_now(),"control_authority":CONTROL_AUTHORITY,
        }
        return cls(
            schema_version=unsigned["schema_version"],project_id=unsigned["project_id"],
            predecessor_run_id=predecessor,predecessor_authority_sha256=unsigned["predecessor_authority_sha256"],
            successor_run_id=successor,successor_authority_sha256=unsigned["successor_authority_sha256"],
            reason=reason_text,evidence_refs=refs,created_at=unsigned["created_at"],control_authority=CONTROL_AUTHORITY,
            record_sha256=_digest(unsigned),
        )

    def unsigned_dict(self)->dict[str,Any]:
        d=asdict(self); d["evidence_refs"]=list(self.evidence_refs); d.pop("record_sha256"); return d
    def to_dict(self)->dict[str,Any]:
        d=self.unsigned_dict(); d["record_sha256"]=self.record_sha256; return d
    def validate(self)->None:
        if self.schema_version!=SCHEMA_VERSION or self.control_authority!=CONTROL_AUTHORITY: raise RunSupersessionError("supersession schema/authority mismatch")
        _id(self.project_id,"project ID"); _id(self.predecessor_run_id,"predecessor run ID"); _id(self.successor_run_id,"successor run ID")
        _sha(self.predecessor_authority_sha256,"predecessor authority"); _sha(self.successor_authority_sha256,"successor authority")
        if self.predecessor_run_id==self.successor_run_id or not self.evidence_refs: raise RunSupersessionError("supersession identity/evidence invalid")
        if self.record_sha256!=_digest(self.unsigned_dict()): raise RunSupersessionError("supersession record digest mismatch")

    @classmethod
    def from_dict(cls,value:Mapping[str,Any])->"RunSupersessionRecord":
        fields={"schema_version","project_id","predecessor_run_id","predecessor_authority_sha256","successor_run_id","successor_authority_sha256","reason","evidence_refs","created_at","control_authority","record_sha256"}
        if not isinstance(value,Mapping) or set(value)!=fields or not isinstance(value.get("evidence_refs"),list): raise RunSupersessionError("supersession record fields mismatch")
        r=cls(schema_version=str(value["schema_version"]),project_id=str(value["project_id"]),predecessor_run_id=str(value["predecessor_run_id"]),
              predecessor_authority_sha256=str(value["predecessor_authority_sha256"]),successor_run_id=str(value["successor_run_id"]),
              successor_authority_sha256=str(value["successor_authority_sha256"]),reason=str(value["reason"]),evidence_refs=tuple(value["evidence_refs"]),
              created_at=str(value["created_at"]),control_authority=str(value["control_authority"]),record_sha256=str(value["record_sha256"]))
        r.validate(); return r


@dataclass(frozen=True,slots=True)
class SupersessionAssessment:
    archived:bool
    disposition:str
    reason:str
    record_sha256:str=""
    control_authority:str=CONTROL_AUTHORITY


class RunSupersessionStore:
    def __init__(self,state_root:str|Path)->None:
        root=Path(state_root).resolve()
        if not root.is_dir() or root.is_symlink(): raise RunSupersessionError("supersession state root is unsafe")
        self.base=root/"_workspace"/"run-supersession"
    def save(self,record:RunSupersessionRecord)->RunSupersessionRecord:
        record.validate(); path=self.base/record.project_id/record.predecessor_run_id/f"{record.successor_run_id}.json"
        if path.exists():
            existing=RunSupersessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if existing!=record: raise RunSupersessionError("conflicting supersession record")
            return existing
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.parent.is_symlink(): raise RunSupersessionError("supersession path is unsafe")
        atomic_write_json(path,record.to_dict()); return record
    def find(self,*,project_id:str,predecessor_run_id:str)->tuple[RunSupersessionRecord,...]:
        root=self.base/_id(project_id,"project ID")/_id(predecessor_run_id,"predecessor run ID")
        if not root.is_dir() or root.is_symlink(): return ()
        rows=[]
        for path in sorted(root.glob("*.json")):
            if path.is_symlink() or not path.is_file(): continue
            try: rows.append(RunSupersessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError,UnicodeError,json.JSONDecodeError,RunSupersessionError): continue
        return tuple(rows)


def evaluate_supersession(event:Mapping[str,Any],candidate_run:Mapping[str,Any],*,record:RunSupersessionRecord|None)->SupersessionAssessment:
    if record is None: return SupersessionAssessment(False,"CURRENT","NO_BOUND_SUPERSESSION_RECORD")
    try: record.validate()
    except RunSupersessionError: return SupersessionAssessment(False,"CURRENT","INVALID_SUPERSESSION_RECORD")
    if (str(event.get("project_id") or "")!=record.project_id or str(event.get("run_id") or "")!=record.predecessor_run_id):
        return SupersessionAssessment(False,"CURRENT","PREDECESSOR_IDENTITY_MISMATCH")
    event_auth=str(event.get("authority_core_sha256") or "")
    if event_auth and event_auth!=record.predecessor_authority_sha256:
        return SupersessionAssessment(False,"CURRENT","PREDECESSOR_AUTHORITY_MISMATCH")
    if (str(candidate_run.get("project_id") or "")!=record.project_id or str(candidate_run.get("run_id") or "")!=record.successor_run_id
            or str(candidate_run.get("authority_core_sha256") or "")!=record.successor_authority_sha256):
        return SupersessionAssessment(False,"CURRENT","SUCCESSOR_BINDING_MISMATCH")
    progressed=bool(candidate_run.get("semantic_progress_verified")) or str(candidate_run.get("state") or "") in _TERMINAL
    if not progressed: return SupersessionAssessment(False,"CURRENT","SUCCESSOR_PROGRESS_UNVERIFIED")
    return SupersessionAssessment(True,"ARCHIVED_SUPERSEDED","BOUND_SUCCESSOR_SUPERSEDES_INCIDENT",record.record_sha256)
