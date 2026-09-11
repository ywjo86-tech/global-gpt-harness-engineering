"""Persistent terminal Gate controller for reviewed LV completion."""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .lifecycle_binding import canonical_bytes, validate_binding


class GateTerminalError(ValueError): pass


class GateTerminalController:
    def __init__(self, root: str | Path, binding: Mapping[str,Any], lvs: Sequence[str],
                 *, mode: str = "GATE_BY_GATE"):
        if not lvs or len(lvs) != len(set(lvs)): raise GateTerminalError("Gate LV plan is invalid")
        if mode not in {"GATE_BY_GATE","FULL_PLAN"}: raise GateTerminalError("execution mode is invalid")
        self.root=Path(root); self.binding=validate_binding(binding); self.lvs=list(lvs); self.mode=mode
        self.state_path=self.root/"gate-terminal.state.json"

    def load(self) -> dict[str,Any]:
        if not self.state_path.exists():
            return {"schema_version":"orchestration.gate-terminal-state.v1","lvs":self.lvs,
                    "completed_lvs":[],"stage":"REVIEW_PENDING","gate_status":"IN_PROGRESS",
                    "mode":self.mode,"artifacts":{}}
        try: state=json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise GateTerminalError("corrupt Gate terminal state") from exc
        digest=state.get("state_sha256")
        if digest != hashlib.sha256(canonical_bytes({k:v for k,v in state.items() if k != "state_sha256"})).hexdigest():
            raise GateTerminalError("Gate terminal state digest mismatch")
        if state.get("lvs") != self.lvs or state.get("mode") != self.mode: raise GateTerminalError("Gate terminal plan binding mismatch")
        return state

    def _save(self,state: Mapping[str,Any]) -> None:
        self.root.mkdir(parents=True,exist_ok=True); state=dict(state)
        state["state_sha256"]=hashlib.sha256(canonical_bytes({k:v for k,v in state.items() if k != "state_sha256"})).hexdigest()
        data=canonical_bytes(state)
        fd,tmp=tempfile.mkstemp(prefix="gate-state.",dir=self.root)
        try:
            with os.fdopen(fd,"wb") as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp,self.state_path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def _artifact(self, kind: str, payload: Mapping[str,Any], state: dict[str,Any]) -> dict[str,Any]:
        key=f"{kind}:{payload.get('lv_id','gate')}"
        existing=state["artifacts"].get(key)
        artifact={"kind":kind,"payload":dict(payload)}
        if existing:
            if existing != artifact: raise GateTerminalError("terminal artifact replay conflict")
            return existing
        state["artifacts"][key]=artifact; return artifact

    def review_pass(self, lv_id: str) -> dict[str,Any]:
        state=self.load(); completed=state["completed_lvs"]
        expected=self.lvs[len(completed)] if len(completed)<len(self.lvs) else None
        if lv_id in completed: return self.load()
        if state["stage"] != "REVIEW_PENDING" or lv_id != expected: raise GateTerminalError("duplicate or out-of-order review PASS")
        checkpoint=self._artifact("checkpoint",{"lv_id":lv_id,"status":"CHECKPOINTED"},state)
        state["stage"]="CHECKPOINTED"; self._save(state)
        lv_exit=self._artifact("lv_exit",{"lv_id":lv_id,"status":"EXITED","checkpoint_sha256":hashlib.sha256(canonical_bytes(checkpoint)).hexdigest()},state)
        completed.append(lv_id); state["stage"]="LV_EXITED"; self._save(state)
        remaining=self.lvs[len(completed):]
        if remaining:
            state["stage"]="REVIEW_PENDING"; state["next_lv"]=remaining[0]; self._save(state); return self.load()
        completeness=self._artifact("gate_completeness",{"completed_lvs":completed,"status":"COMPLETE"},state)
        state["stage"]="GATE_COMPLETE"; self._save(state)
        gate_checkpoint=self._artifact("gate_checkpoint",{"status":"CHECKPOINTED","completeness_sha256":hashlib.sha256(canonical_bytes(completeness)).hexdigest()},state)
        state["stage"]="GATE_CHECKPOINTED"; self._save(state)
        gate_exit=self._artifact("gate_exit",{"status":"EXITED","checkpoint_sha256":hashlib.sha256(canonical_bytes(gate_checkpoint)).hexdigest()},state)
        state["stage"]="GATE_EXITED"; state["gate_status"]="EXITED"; self._save(state)
        handoff=self._artifact("handoff",{"status":"SEALED","completed_lvs":completed,
            "gate_exit_sha256":hashlib.sha256(canonical_bytes(gate_exit)).hexdigest(),"next_gate_status":"USER_APPROVAL_REQUIRED",
            "hard_stop":True},state)
        state["stage"]="HANDOFF_SEALED"; state["next_gate_status"]="USER_APPROVAL_REQUIRED"
        state["handoff_sha256"]=hashlib.sha256(canonical_bytes(handoff)).hexdigest(); self._save(state); return self.load()

    def replay_terminal(self) -> dict[str,Any]:
        state=self.load()
        if state["stage"] != "HANDOFF_SEALED": raise GateTerminalError("Gate is not terminal")
        # Persisted production terminal artifacts are validated by
        # ProductionTerminalLifecycle; this controller only verifies its own
        # immutable state/object replay and never consumes an in-memory envelope.
        return state

    def start_next_gate(self) -> None:
        if self.mode == "GATE_BY_GATE": raise GateTerminalError("USER_APPROVAL_REQUIRED")
        # FULL_PLAN is an explicit fixture mode; actual next-Gate dispatch belongs
        # to its separately bound controller and cannot reuse this Gate binding.
        raise GateTerminalError("next Gate requires a distinct canonical binding")
