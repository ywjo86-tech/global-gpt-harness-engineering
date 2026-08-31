"""Durable single-invocation runner from the first incomplete LV to Gate boundary."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


class ProductionGateRunnerError(ValueError):
    pass


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_bytes(value)); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class ProductionGateRunner:
    def __init__(self, harness_root: str | Path, *, project_id: str, gate_id: str, run_id: str,
                 mode: str, canonical_lvs: Sequence[str], inherited_completed_lvs: Sequence[str]):
        if mode != "GATE_BY_GATE":
            raise ProductionGateRunnerError("single-Gate runner requires GATE_BY_GATE authorization")
        self.lvs = tuple(canonical_lvs); inherited = tuple(inherited_completed_lvs)
        if not self.lvs or len(set(self.lvs)) != len(self.lvs):
            raise ProductionGateRunnerError("canonical LV order is invalid")
        if inherited != self.lvs[:len(inherited)]:
            raise ProductionGateRunnerError("completed LV inheritance is out of order")
        self.project_id=project_id; self.gate_id=gate_id; self.run_id=run_id; self.mode=mode
        self.initial_completed=inherited
        base=Path(harness_root).resolve()/"_workspace"/"production-gate-runner"/project_id
        self.state_path=base/f"{run_id}.state.json"; self.events_path=base/f"{run_id}.events.jsonl"

    def _initial(self) -> dict[str, Any]:
        value={"schema_version":"orchestration.production-gate-runner.v1","project_id":self.project_id,
               "gate_id":self.gate_id,"run_id":self.run_id,"mode":self.mode,"canonical_lvs":list(self.lvs),
               "completed_lvs":list(self.initial_completed),"stage":"LV_LOOP","terminal":False,
               "external_supervisor_invocations":1,"user_resume_requests":0,"user_lv_approval_requests":0,
               "worker_invocations":{},"hard_stop":True}
        value["state_sha256"]=_sha(value); return value

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists(): return self._initial()
        if self.state_path.is_symlink(): raise ProductionGateRunnerError("runner state is unsafe")
        value=json.loads(self.state_path.read_text(encoding="utf-8")); digest=value.pop("state_sha256",None)
        if digest != _sha(value): raise ProductionGateRunnerError("runner state hash mismatch")
        value["state_sha256"]=digest
        if tuple(value.get("canonical_lvs",())) != self.lvs or value.get("run_id") != self.run_id:
            raise ProductionGateRunnerError("runner state binding mismatch")
        completed=tuple(value.get("completed_lvs",()))
        if completed != self.lvs[:len(completed)]: raise ProductionGateRunnerError("runner LV order mismatch")
        return value

    def _persist(self, state: dict[str, Any], event: Mapping[str, Any]) -> None:
        unsigned={k:v for k,v in state.items() if k!="state_sha256"}; state["state_sha256"]=_sha(unsigned)
        _atomic(self.state_path,state)
        row=dict(event); row["state_sha256"]=state["state_sha256"]; row["event_sha256"]=_sha(row)
        self.events_path.parent.mkdir(parents=True,exist_ok=True)
        with self.events_path.open("ab") as handle: handle.write(_bytes(row)+b"\n"); handle.flush(); os.fsync(handle.fileno())

    def run(self, execute_lv: Callable[[str], Mapping[str, Any]],
            finalize_gate: Callable[[Sequence[str]], Mapping[str, Any]]) -> dict[str, Any]:
        state=self.load()
        if state.get("terminal"):
            return {"status":state["status"],"state":state,"mutation_performed":False,"invoked_lvs":[]}
        invoked=[]; budget=(len(self.lvs)-len(state["completed_lvs"]))*2+2; transitions=0
        while len(state["completed_lvs"]) < len(self.lvs):
            if transitions+2 > budget: raise ProductionGateRunnerError("canonical transition budget exceeded")
            lv=self.lvs[len(state["completed_lvs"])]
            counts=dict(state.get("worker_invocations",{}))
            if int(counts.get(lv,0)) != 0: raise ProductionGateRunnerError("duplicate worker invocation blocked")
            before=state["state_sha256"]; outcome=dict(execute_lv(lv)); transitions+=1
            if outcome.get("status") != "SYSTEM_TRANSITION" or outcome.get("lv_id") != lv:
                raise ProductionGateRunnerError("LV lifecycle made no canonical progress")
            counts[lv]=1; state["worker_invocations"]=counts; state["last_lv_outcome"]=outcome
            self._persist(state,{"event":"LV_LIFECYCLE_COMPLETE","lv_id":lv})
            state["completed_lvs"].append(lv); state["stage"]="LV_EXIT"; transitions+=1
            self._persist(state,{"event":"LV_EXIT","lv_id":lv}); invoked.append(lv)
            if state["state_sha256"] == before: raise ProductionGateRunnerError("NO_PROGRESS")
            state["stage"]="LV_LOOP"
        terminal=dict(finalize_gate(tuple(state["completed_lvs"])))
        if terminal.get("next_gate_status") != "USER_APPROVAL_REQUIRED" or terminal.get("gate_status") != "EXITED":
            raise ProductionGateRunnerError("Gate terminal boundary is incomplete")
        state.update({"stage":"HANDOFF_SEALED","status":"USER_APPROVAL_REQUIRED","terminal":True,
                      "gate_terminal":terminal,"hard_stop":True})
        self._persist(state,{"event":"GATE_EXIT","next_gate_status":"USER_APPROVAL_REQUIRED"})
        return {"status":"USER_APPROVAL_REQUIRED","state":state,"mutation_performed":True,
                "invoked_lvs":invoked,"transition_budget":budget,"hard_stop":True}
