"""Fail-closed verification of an approved admin migration from legacy ACTIVE Gate to sealed V2.

The legacy approval log, activation, and ledger stay immutable. This is an
admin trust-epoch transition record, NOT a user action approval or substitute
for a fresh sealed per-run Gate approval.
"""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Mapping

SCHEMA="orchestration.legacy-gate-retirement.v1"
_FIELDS={
 "schema_version","project_id","retired_source_head",
 "legacy_gate_state_sha256","legacy_first_gate_activation_sha256",
 "legacy_approval_log_sha256","new_gate_state_path","new_gate_state_sha256",
 "owner_authorization_ref","decision","record_sha256"}
_SHA=re.compile(r"[0-9a-f]{64}\Z")
_HEAD=re.compile(r"[0-9a-f]{40}\Z")
_REF=re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{3,199}\Z")
_RETIRE_DECISION="RETIRE_LEGACY_ACTIVE_GATE_FOR_SEALED_V2"
_FILE="docs/harness/legacy-gate-retirement.v1.json"
_OLD_LEDGER="docs/GATE_STATE.md"
_OLD_ACTIVATION="docs/harness/first-gate.activation.json"
_OLD_APPROVAL="docs/APPROVAL_LOG.md"
def digest(value):
 return hashlib.sha256(value).hexdigest()
def _canonical(payload):
 return json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
def make_retirement_record(root:Path,*,new_gate_state:str,owner_authorization_ref:str)->dict:
 """Build a PREVIEW; never writes anything. Caller must commit signed-off decision."""
 root=Path(root).resolve()
 old=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip()
 doc={
  "schema_version":SCHEMA,
  "project_id":root.name,
  "retired_source_head":old,
  "legacy_gate_state_sha256":digest((root/_OLD_LEDGER).read_bytes()),
  "legacy_first_gate_activation_sha256":digest((root/_OLD_ACTIVATION).read_bytes()),
  "legacy_approval_log_sha256":digest((root/_OLD_APPROVAL).read_bytes()),
  "new_gate_state_path":new_gate_state,
  "new_gate_state_sha256":digest((root/new_gate_state).read_bytes()),
  "owner_authorization_ref":owner_authorization_ref,
  "decision":_RETIRE_DECISION,
 }
 doc["record_sha256"]=digest(_canonical(doc))
 return doc
def verify_retirement(root:Path,*,project_id:str,gate_state:Path,ledger_path:Path,
                      business_approval:Path,record_rel:str,record_digest:str)->dict:
 root=Path(root).resolve()
 if record_rel!=_FILE or not _SHA.fullmatch(str(record_digest or "")):
  raise ValueError("legacy retirement proof path/digest invalid")
 p=root/_FILE
 if not p.is_file() or p.is_symlink() or p.stat().st_size>65536:
  raise ValueError("legacy retirement proof missing or unsafe")
 raw=p.read_bytes()
 if digest(raw)!=record_digest:
  raise ValueError("legacy retirement proof does not match registry")
 try:
  record=json.loads(raw.decode("utf-8"))
 except (ValueError,UnicodeError) as e:
  raise ValueError("legacy retirement proof malformed") from e
 if not isinstance(record,dict) or set(record)!=_FIELDS or record.get("schema_version")!=SCHEMA:
  raise ValueError("legacy retirement proof schema mismatch")
 if record["record_sha256"]!=digest(_canonical({k:v for k,v in record.items() if k!="record_sha256"})):
  raise ValueError("legacy retirement record checksum mismatch")
 if (record["project_id"]!=project_id or record["decision"]!=_RETIRE_DECISION
   or not _HEAD.fullmatch(str(record["retired_source_head"]))
   or not _REF.fullmatch(str(record["owner_authorization_ref"]))):
  raise ValueError("legacy retirement identity or decision invalid")
 for field in ("legacy_gate_state_sha256","legacy_first_gate_activation_sha256",
               "legacy_approval_log_sha256","new_gate_state_sha256"):
  if not _SHA.fullmatch(str(record[field])):
   raise ValueError("legacy retirement digest malformed")
 if gate_state!=ledger_path or gate_state.resolve()==(root/_OLD_LEDGER).resolve():
  raise ValueError("legacy retirement requires one separate V2 state+ledger source")
 new_rel=gate_state.relative_to(root).as_posix()
 if new_rel!=record["new_gate_state_path"] or digest(gate_state.read_bytes())!=record["new_gate_state_sha256"]:
  raise ValueError("V2 canonical state evidence mismatch")
 if business_approval!=(root/_OLD_APPROVAL):
  raise ValueError("legacy approval log location changed")
 for rel,field in ((_OLD_LEDGER,"legacy_gate_state_sha256"),(_OLD_ACTIVATION,"legacy_first_gate_activation_sha256"),(_OLD_APPROVAL,"legacy_approval_log_sha256")):
  q=root/rel
  if not q.is_file() or q.is_symlink() or digest(q.read_bytes())!=record[field]:
   raise ValueError("historical Gate authority was modified")
 head=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip()
 retired=record["retired_source_head"]
 lineage=subprocess.run(["git","-C",str(root),"merge-base","--is-ancestor",retired,head],capture_output=True)
 if lineage.returncode!=0 or retired==head:
  raise ValueError("legacy retirement Git ancestry invalid")
 for rel,expected in ((_OLD_LEDGER,record["legacy_gate_state_sha256"]),(_OLD_ACTIVATION,record["legacy_first_gate_activation_sha256"]),(_OLD_APPROVAL,record["legacy_approval_log_sha256"]),(_FILE,record_digest),(new_rel,record["new_gate_state_sha256"])):
  saved=subprocess.run(["git","-C",str(root),"show",f"HEAD:{rel}"],capture_output=True)
  if saved.returncode!=0 or digest(saved.stdout)!=expected:
   raise ValueError("retirement history or V2 proof is not committed at HEAD")
 return record
