"""Durable production terminal lifecycle consuming persisted artifacts only."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any,Mapping,Sequence
from .gate_terminal import GateTerminalController,GateTerminalError
from .persisted_artifact import publish,validate

class ProductionTerminalError(ValueError):pass

STAGES=("checkpoint","lv_exit","gate_completeness","gate_checkpoint","gate_exit","handoff")

class ProductionTerminalLifecycle:
 def __init__(self,root:str|Path,binding:Mapping[str,Any],lvs:Sequence[str],*,source_sha256:str,predecessor:str,mode:str="GATE_BY_GATE"):
  self.root=Path(root);self.binding=dict(binding);self.lvs=list(lvs);self.source=source_sha256;self.predecessor=predecessor;self.mode=mode
  self.controller=GateTerminalController(self.root/"state",binding,lvs,mode=mode)
 def _persist(self,kind:str,key:str,payload:Mapping[str,Any]):
  rel=f"artifacts/{key}.{kind}.json";path=self.root/rel
  if not path.exists():publish(self.root,rel,kind=kind,payload=payload,binding=self.binding,source_artifact_sha256=self.source,predecessor_digest=self.predecessor)
  return validate(self.root,rel,expected_kind=kind,expected_binding=self.binding,expected_source_sha256=self.source,expected_predecessor=self.predecessor)
 def review_pass(self,lv_id:str)->dict[str,Any]:
  before=self.controller.load();completed=set(before["completed_lvs"])
  if lv_id not in completed:
   self._persist("checkpoint",lv_id,{"lv_id":lv_id,"status":"CHECKPOINTED"})
   self._persist("lv_exit",lv_id,{"lv_id":lv_id,"status":"EXITED","active_scope":"CLOSED"})
  state=self.controller.review_pass(lv_id)
  if state["stage"]=="HANDOFF_SEALED":
   self._persist("gate_completeness","gate",{"completed_lvs":state["completed_lvs"],"status":"COMPLETE"})
   self._persist("gate_checkpoint","gate",{"status":"CHECKPOINTED"})
   self._persist("gate_exit","gate",{"status":"EXITED"})
   self._persist("handoff","gate",{"status":"SEALED","next_gate_status":"USER_APPROVAL_REQUIRED","hard_stop":True})
  return state
 def replay(self)->dict[str,Any]:
  state=self.controller.load()
  for lv in state["completed_lvs"]:
   self._persist("checkpoint",lv,{"lv_id":lv,"status":"CHECKPOINTED"});self._persist("lv_exit",lv,{"lv_id":lv,"status":"EXITED","active_scope":"CLOSED"})
  if state["stage"]=="HANDOFF_SEALED":
   for kind in STAGES[2:]:self._persist(kind,"gate",({"completed_lvs":state["completed_lvs"],"status":"COMPLETE"} if kind=="gate_completeness" else {"status":"SEALED","next_gate_status":"USER_APPROVAL_REQUIRED","hard_stop":True} if kind=="handoff" else {"status":"EXITED"} if kind=="gate_exit" else {"status":"CHECKPOINTED"}))
  return state

def run_terminal_entry(*,root:str|Path,binding:Mapping[str,Any],lvs:Sequence[str],reviewed_lvs:Sequence[str],source_sha256:str,predecessor:str,mode:str="GATE_BY_GATE")->dict[str,Any]:
 lifecycle=ProductionTerminalLifecycle(root,binding,lvs,source_sha256=source_sha256,predecessor=predecessor,mode=mode)
 state=lifecycle.controller.load()
 for lv in reviewed_lvs:
  if lv not in state["completed_lvs"]:state=lifecycle.review_pass(lv)
 if state["stage"]=="HANDOFF_SEALED" and state.get("next_gate_status")!="USER_APPROVAL_REQUIRED":raise ProductionTerminalError("next Gate approval boundary missing")
 return state

def run_plan_fixture(root:str|Path,gates:Sequence[Mapping[str,Any]],*,mode:str)->dict[str,Any]:
 results=[]
 for index,gate in enumerate(gates):
  if mode=="GATE_BY_GATE" and index>0:break
  results.append(run_terminal_entry(root=Path(root)/str(gate["gate_id"]),binding=gate["binding"],lvs=gate["lvs"],reviewed_lvs=gate["lvs"],source_sha256=gate["source_sha256"],predecessor=gate["predecessor"],mode=mode))
 return {"mode":mode,"completed_gates":len(results),"next_gate_status":"USER_APPROVAL_REQUIRED" if mode=="GATE_BY_GATE" else None,"hard_stop":True}
