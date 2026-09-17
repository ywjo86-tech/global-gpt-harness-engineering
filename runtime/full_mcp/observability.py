from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .contracts import canonical_json_bytes

ERROR_CODES = {
    "AUTHENTICATION_FAILED", "AUTHORIZATION_DENIED", "INPUT_SCHEMA_INVALID", "WORKSPACE_VIOLATION",
    "PATH_POLICY_VIOLATION", "SYMLINK_VIOLATION", "SENSITIVE_PATH_BLOCKED", "COMMAND_NOT_ALLOWED",
    "PROCESS_SPAWN_FAILED", "PROCESS_TIMEOUT", "PROCESS_CANCELLED", "NONZERO_EXIT", "OUTPUT_LIMIT_EXCEEDED",
    "SECRET_OUTPUT_BLOCKED", "GIT_BOUNDARY_VIOLATION", "GIT_INDEX_NOT_CLEAN", "GIT_HEAD_DRIFT",
    "GIT_WORKTREE_DRIFT", "GIT_CANDIDATE_DRIFT", "GIT_INDEX_DRIFT", "GIT_BRANCH_MISMATCH",
    "GIT_REMOTE_STALE", "GIT_NON_FAST_FORWARD", "GIT_PUSH_REJECTED", "GIT_REMOTE_HEAD_UNAVAILABLE",
    "ACTION_SIDE_EFFECT_AMBIGUOUS", "PATCH_CONFLICT", "VALIDATION_FAILED",
    "EFFECT_REPLAY_BLOCKED", "RECOVERY_AMBIGUOUS", "PERSISTENCE_FAILED", "INTERNAL_ERROR",
}
STATES = {"RECEIVED", "AUTHENTICATED", "AUTHORIZED", "EFFECT_INTENT", "RUNNING", "EFFECT_RECEIPT",
          "RESULT_SEALED", "VALIDATED", "BLOCKED", "FAILED", "CANCELLED", "RECOVERY_REQUIRED", "RESTORED_PENDING_VALIDATION"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_FORBIDDEN_KEYS = {"content", "stdout", "stderr", "arguments", "argv", "authorization", "auth", "secret", "token", "credentials"}


class ObservabilityError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value): raise ObservabilityError(f"{field} is invalid")
    return value


def _safe_digest(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable: return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value): raise ObservabilityError(f"{field} is invalid")
    return value


def _reject_forbidden(mapping: Mapping[str, object]) -> None:
    for key, value in mapping.items():
        lowered=str(key).lower()
        if lowered in _FORBIDDEN_KEYS or any(word in lowered for word in ("raw_", "password", "credential", "secret")):
            raise ObservabilityError("durable observability contains a forbidden field")
        if isinstance(value, Mapping): _reject_forbidden(value)
        if isinstance(value, str) and "runtime.full_mcp." in value:
            raise ObservabilityError("durable observability may not expose Full MCP internal class names")


class ObservabilityStore:
    def __init__(self, workspace_root: str | Path, run_id: str) -> None:
        self.workspace_root=Path(workspace_root); _safe_id(run_id,"run_id"); self.run_id=run_id
        if not self.workspace_root.is_absolute() or self.workspace_root.resolve(strict=True) != self.workspace_root:
            raise ObservabilityError("workspace root must be canonical")
        self.base=self.workspace_root/"_workspace"/"full-mcp"/run_id
        self.events_path=self.base/"events"/"execution-events.jsonl"; self.results_dir=self.base/"results"
        self.events_path.parent.mkdir(parents=True,exist_ok=True); self.results_dir.mkdir(parents=True,exist_ok=True)

    def append_event(self, *, operation_request_id: str, correlation_id: str, operation: str, state: str,
                     result_digest: str | None = None, effect_id: str | None = None, error_code: str | None = None) -> dict[str, object]:
        _safe_id(operation_request_id,"operation_request_id"); _safe_id(correlation_id,"correlation_id"); _safe_id(operation,"operation")
        if state not in STATES: raise ObservabilityError("event state is invalid")
        _safe_digest(result_digest,"result_digest",nullable=True)
        if effect_id is not None: _safe_id(effect_id,"effect_id")
        if error_code is not None and error_code not in ERROR_CODES: raise ObservabilityError("error code is outside closed taxonomy")
        try:
            with self.events_path.open("a+",encoding="utf-8") as handle:
                os.chmod(self.events_path,0o600); fcntl.flock(handle.fileno(),fcntl.LOCK_EX); handle.seek(0)
                last=0
                for line in handle:
                    try: item=json.loads(line)
                    except json.JSONDecodeError as exc: raise ObservabilityError("existing event log is malformed") from exc
                    if item.get("operation_request_id")==operation_request_id: last=max(last,int(item.get("sequence",0)))
                record={"schema_version":"gch.full-mcp.execution-event.v1","operation_request_id":operation_request_id,
                        "correlation_id":correlation_id,"operation":operation,"state":state,"sequence":last+1,
                        "occurred_at_utc":_utc_now(),"result_digest":result_digest,"effect_id":effect_id,"error_code":error_code}
                _reject_forbidden(record); handle.seek(0,os.SEEK_END); handle.write(json.dumps(record,sort_keys=True,separators=(",",":"))+"\n"); handle.flush(); os.fsync(handle.fileno())
        except OSError as exc: raise ObservabilityError("event persistence failed") from exc
        record["audit_ref"] = f"_workspace/full-mcp/{self.run_id}/events/execution-events.jsonl#{operation_request_id}:{record['sequence']}"
        return record

    def seal_result(self, *, operation_request_id: str, correlation_id: str, operation: str, state: str,
                    started_at: str, ended_at: str, audit_ref: str, effect_id: str | None = None,
                    error_code: str | None = None, exit_code: int | None = None, security_block: bool = False,
                    restore_equivalent: bool = False) -> dict[str, object]:
        _safe_id(operation_request_id,"operation_request_id"); _safe_id(correlation_id,"correlation_id"); _safe_id(operation,"operation")
        if state not in {"COMPLETED","BLOCKED","FAILED","CANCELLED","VALIDATED"}: raise ObservabilityError("terminal state is invalid")
        if effect_id is not None: _safe_id(effect_id,"effect_id")
        if error_code is not None and error_code not in ERROR_CODES: raise ObservabilityError("error code is outside closed taxonomy")
        body={"schema_version":"gch.full-mcp.result-index.v1","operation_request_id":operation_request_id,"correlation_id":correlation_id,
              "operation":operation,"state":state,"started_at":started_at,"ended_at":ended_at,"audit_ref":audit_ref,"effect_id":effect_id,
              "error_code":error_code,"exit_code":exit_code,"security_block":bool(security_block),"restore_equivalent":bool(restore_equivalent)}
        _reject_forbidden(body); digest=hashlib.sha256(canonical_json_bytes(body)).hexdigest(); record={**body,"result_digest":digest}
        path=self.results_dir/f"{operation_request_id}.json"
        try:
            descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,"w",encoding="utf-8") as handle:
                json.dump(record,handle,sort_keys=True,separators=(",",":")); handle.flush(); os.fsync(handle.fileno())
        except FileExistsError as exc: raise ObservabilityError("terminal result is create-once") from exc
        except OSError as exc: raise ObservabilityError("result persistence failed") from exc
        return record

    def status(self, operation_request_id: str) -> dict[str, object] | None:
        _safe_id(operation_request_id,"operation_request_id"); path=self.results_dir/f"{operation_request_id}.json"
        if not path.exists(): return None
        if path.is_symlink() or not path.is_file(): raise ObservabilityError("result record is unsafe")
        try: value=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise ObservabilityError("result record is malformed") from exc
        if not isinstance(value,dict) or value.get("operation_request_id")!=operation_request_id: raise ObservabilityError("result record identity mismatch")
        digest=value.get("result_digest"); body=dict(value); body.pop("result_digest",None)
        if digest != hashlib.sha256(canonical_json_bytes(body)).hexdigest(): raise ObservabilityError("result record digest mismatch")
        return value
