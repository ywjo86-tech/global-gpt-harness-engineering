"""Durable, versioned Gate continuation transaction evidence."""
from __future__ import annotations
import fcntl, hashlib, json, os, re, time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from .durable_io import atomic_write_json
from .durable_continuation import enter_continuation_transaction_lock, exit_continuation_transaction_lock

SCHEMA = "orchestration.gate-continuation-transaction.v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,160}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SUCCESS_PHASES = ("PREPARED","EXECUTION_OBSERVED","VERIFIED","COMMIT_INTENT","COMMITTED","RECEIPT_SEALED","ADVANCED")
DISPOSITIONS = ("BLOCKED","USER_DECISION_REQUIRED","DELEGATED_RUNTIME_MIGRATION","ROLLED_BACK")
_ALLOWED = set(SUCCESS_PHASES) | set(DISPOSITIONS)

class TransactionError(ValueError): pass

def _now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _digest(v: Mapping[str, Any]): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def _sid(v: str, name: str):
    if not _SAFE_ID.fullmatch(str(v or "")): raise TransactionError(f"invalid {name}")
    return str(v)
def _sha(v: str, name: str):
    if not _SHA256.fullmatch(str(v or "")): raise TransactionError(f"invalid {name}")
    return str(v)

class GateContinuationTransactionStore:
    def __init__(self,state_root: str|Path,*,project_id:str,run_id:str):
        self.root=Path(state_root).resolve(); self.project_id=_sid(project_id,"project_id"); self.run_id=_sid(run_id,"run_id")
        self.base=self.root/"_workspace"/"dcc-transactions"/self.project_id/self.run_id
    def path(self,gate_id:str)->Path: return self.base/f"{_sid(gate_id,'gate_id')}.json"
    def lock_path(self,gate_id:str)->Path: return self.base/f"{_sid(gate_id,'gate_id')}.lock"

    @contextmanager
    def transaction_lock(self, gate_id: str, *, timeout_seconds: float = 2.0):
        if timeout_seconds <= 0:
            raise TransactionError("transaction lock timeout must be positive")
        enter_continuation_transaction_lock()
        handle = None
        try:
            path = self.lock_path(gate_id); path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(str(path), flags, 0o600)
            except OSError as exc:
                raise TransactionError("unsafe continuation transaction lock") from exc
            handle = os.fdopen(fd, "a+")
            deadline = time.monotonic() + float(timeout_seconds)
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise TransactionError("continuation transaction lock timeout") from exc
                    time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            yield handle
        finally:
            if handle is not None:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()
            exit_continuation_transaction_lock()
    def _seal(self,payload:dict[str,Any])->dict[str,Any]:
        unsigned={k:v for k,v in payload.items() if k!="transaction_sha256"}; return {**unsigned,"transaction_sha256":_digest(unsigned)}
    def _write(self,gate_id:str,payload:dict[str,Any])->dict[str,Any]:
        path=self.path(gate_id); path.parent.mkdir(parents=True,exist_ok=True)
        if path.parent.is_symlink(): raise TransactionError("unsafe transaction root")
        sealed=self._seal(payload); atomic_write_json(path,sealed); return sealed
    def create(self,*,gate_id:str,authority_core_sha256:str,contract_sha256:str)->dict[str,Any]:
        gate=_sid(gate_id,"gate_id"); binding={"schema_version":SCHEMA,"project_id":self.project_id,"run_id":self.run_id,"gate_id":gate,
            "authority_core_sha256":_sha(authority_core_sha256,"authority_core_sha256"),"contract_sha256":_sha(contract_sha256,"contract_sha256"),
            "phase":"PREPARED","prior_phase":None,"reason":"PREPARED","binding_digests":{},"recovery_eligible":True,"created_at":_now(),"updated_at":_now()}
        if self.path(gate).exists():
            existing=self.load(gate)
            if existing["authority_core_sha256"]==binding["authority_core_sha256"] and existing["contract_sha256"]==binding["contract_sha256"]: return existing
            raise TransactionError("conflicting transaction already exists")
        return self._write(gate,binding)
    def load(self,gate_id:str)->dict[str,Any]:
        path=self.path(gate_id)
        if path.is_symlink() or not path.is_file(): raise TransactionError("transaction missing")
        try: raw=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise TransactionError("transaction malformed") from exc
        if not isinstance(raw,dict) or raw.get("schema_version")!=SCHEMA: raise TransactionError("transaction schema mismatch")
        observed=raw.get("transaction_sha256"); unsigned={k:v for k,v in raw.items() if k!="transaction_sha256"}
        if observed!=_digest(unsigned): raise TransactionError("transaction digest mismatch")
        if raw.get("phase") not in _ALLOWED: raise TransactionError("transaction phase invalid")
        return raw
    def transition(self,gate_id:str,*,prior_phase:str,disposition:str,reason:str,binding_digests:Mapping[str,str],recovery_eligible:bool)->dict[str,Any]:
        current=self.load(gate_id)
        if current["phase"]!=prior_phase: raise TransactionError("transaction prior phase mismatch")
        if disposition not in _ALLOWED: raise TransactionError("transaction disposition invalid")
        bindings={str(k):_sha(str(v),"binding digest") for k,v in binding_digests.items()}
        if not str(reason or "").strip(): raise TransactionError("transaction reason required")
        payload={k:v for k,v in current.items() if k!="transaction_sha256"}
        payload.update(phase=disposition,prior_phase=prior_phase,reason=str(reason),binding_digests=bindings,recovery_eligible=bool(recovery_eligible),updated_at=_now())
        return self._write(gate_id,payload)
