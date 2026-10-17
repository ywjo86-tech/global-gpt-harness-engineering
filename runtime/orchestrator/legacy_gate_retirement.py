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
 "owner_authorization_ref","owner_proof","decision","record_sha256"}
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
# Github-owner-comment binding for the retired legacy Gate.  An owner's
# authenticated comment MUST be fetched from the official GitHub API during
# the retirement transaction; snapshots supplied by chat are not evidence.
_OWNER_SCHEMA = "gch.legacy-gate-retirement-owner-proof.v1"
_OWNER_REQUEST_SCHEMA = "gch.legacy-gate-retirement-preflight.v1"
_GITHUB_OWNER_ID = 235775273
_GITHUB_REPOSITORY_ID = 1379497136
_GITHUB_CONTROL_PR = 1
_REQUEST_ID = "RC1-G1-LEGACY-RETIREMENT-20261017-01"
_NEW_GATE_RELPATH = "docs/harness/g1-rc1-v2-sealed-anchor.md"

def owner_preflight(root:Path, *, new_gate_state:str=_NEW_GATE_RELPATH, request_id:str=_REQUEST_ID) -> dict:
    root=Path(root).resolve()
    if new_gate_state != _NEW_GATE_RELPATH or request_id != _REQUEST_ID:
        raise ValueError("unrecognized G1 legacy authority retirement request")
    source_head=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],
                               check=True,capture_output=True,text=True).stdout.strip()
    content=(root/new_gate_state).read_bytes()
    return {
        "schema_version":_OWNER_REQUEST_SCHEMA,
        "request_id":request_id,
        "decision":_RETIRE_DECISION,
        "project_id":root.name,
        "gate_id":"GATE-001",
        "source_head":source_head,
        "legacy_gate_state_sha256":digest((root/_OLD_LEDGER).read_bytes()),
        "legacy_first_gate_activation_sha256":digest((root/_OLD_ACTIVATION).read_bytes()),
        "legacy_approval_log_sha256":digest((root/_OLD_APPROVAL).read_bytes()),
        "new_gate_state_path":new_gate_state,
        "new_gate_state_sha256":digest(content),
        "github_repo_id":_GITHUB_REPOSITORY_ID,
        "github_pr_number":_GITHUB_CONTROL_PR,
        "owner_actor_id":_GITHUB_OWNER_ID,
    }

def owner_comment_body(preflight_digest:str) -> str:
    if not _SHA.fullmatch(str(preflight_digest)):
        raise ValueError("owner retirement preflight digest invalid")
    return "OCP_LEGACY_GATE_RETIREMENT_V1\n" + _canonical({
        "decision":_RETIRE_DECISION,
        "preflight_digest":preflight_digest,
        "request_id":_REQUEST_ID,
    }).decode('utf-8')

def require_exact_owner_comment(comment:Mapping, *, preflight_digest:str) -> dict:
    """Validate the server-fetched Github payload; caller must fetch it live."""
    from datetime import datetime, timezone
    if not isinstance(comment, Mapping):
        raise ValueError("verified owner Github comment required")
    fields=("id","body","created_at","updated_at","user","html_url")
    if any(f not in comment for f in fields):
        raise ValueError("Github owner proof fields missing")
    actor=comment.get("user")
    if not isinstance(actor,Mapping) or actor.get("id")!=_GITHUB_OWNER_ID:
        raise ValueError("Github owner actor mismatched")
    cid=comment.get("id")
    if type(cid) is not int or cid <= 0:
        raise ValueError("Github owner comment ID missing")
    if comment.get("body") != owner_comment_body(preflight_digest):
        raise ValueError("Github owner retirement intent mismatched")
    if comment.get("created_at") != comment.get("updated_at") or not isinstance(comment.get("created_at"),str):
        raise ValueError("Github owner approval has been edited")
    created=comment["created_at"]
    try:
        dt=datetime.fromisoformat(created.replace("Z","+00:00"))
    except ValueError as e:
        raise ValueError("Github owner creation timestamp invalid") from e
    if dt.tzinfo is None or dt > datetime.now(timezone.utc):
        raise ValueError("Github owner timestamp invalid")
    url=f"https://github.com/ywjo86-tech/ocpv2-control/pull/1#issuecomment-{cid}"
    if comment.get("html_url") != url or comment.get("performed_via_github_app") is not None:
        raise ValueError("Github owner evidence source invalid")
    return {
        "schema_version":_OWNER_SCHEMA,
        "repository_id":_GITHUB_REPOSITORY_ID,
        "control_pr_number":_GITHUB_CONTROL_PR,
        "actor_id":_GITHUB_OWNER_ID,
        "comment_id":cid,
        "created_at":created,
        "updated_at":created,
        "url":url,
        "body":comment["body"],
        "preflight_digest":preflight_digest,
    }

def _fetch_live_owner_comment(comment_id:int) -> Mapping:
    """Fetch actual source of truth through existing OCPv2 GitHub owner control.

    No operator-provided proof or local JSON alone can authorize retirement.
    Network/auth errors fail closed, never silently downgrade to a cached claim.
    """
    import stat
    from runtime.operator_transport.github_rest_client import GitHubRESTClient
    env_file=Path.home()/".config/gch/ocpv2.env"
    if not env_file.is_file() or env_file.is_symlink() or (env_file.stat().st_mode & 0o077):
        raise ValueError("Github owner control configuration missing or unsafe")
    env={}
    for line in env_file.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key,value=line.split("=",1)
            env[key.strip()]=value.strip()
    if (env.get("OCP_GITHUB_CONTROL_REPOSITORY_ID") != str(_GITHUB_REPOSITORY_ID)
        or env.get("OCP_GITHUB_CONTROL_PR_NUMBER") != str(_GITHUB_CONTROL_PR)
        or env.get("OCP_GITHUB_ALLOWED_ACTOR_IDS") != str(_GITHUB_OWNER_ID)):
        raise ValueError("Github owner control config identity mismatch")
    token_path=env.get("OCP_GITHUB_TOKEN_FILE","")
    if not token_path:
        raise ValueError("Github owner control credential unavailable")
    client=GitHubRESTClient(repository_id=_GITHUB_REPOSITORY_ID,
                           control_pr_number=_GITHUB_CONTROL_PR,token_file=token_path)
    repo=client.verify_repository()
    return client._request_json("GET",f"https://api.github.com/repos/{repo.full_name}/issues/comments/{comment_id}")

def _verify_owner_proof(record:dict) -> None:
    proof=record.get("owner_proof")
    if not isinstance(proof,dict) or set(proof)!={"schema_version","repository_id","control_pr_number","actor_id","comment_id","created_at","updated_at","url","body","preflight_digest"}:
        raise ValueError("owner Github approval proof missing or malformed")
    if (proof["schema_version"]!=_OWNER_SCHEMA or proof["repository_id"]!=_GITHUB_REPOSITORY_ID
        or proof["control_pr_number"]!=_GITHUB_CONTROL_PR or proof["actor_id"]!=_GITHUB_OWNER_ID):
        raise ValueError("owner Github approval source mismatch")
    if record["owner_authorization_ref"]!=_REQUEST_ID:
        raise ValueError("owner retirement authorization request mismatch")
    req={
        "schema_version":_OWNER_REQUEST_SCHEMA,
        "request_id":_REQUEST_ID,
        "decision":record["decision"],
        "project_id":record["project_id"],
        "gate_id":"GATE-001",
        "source_head":record["retired_source_head"],
        "legacy_gate_state_sha256":record["legacy_gate_state_sha256"],
        "legacy_first_gate_activation_sha256":record["legacy_first_gate_activation_sha256"],
        "legacy_approval_log_sha256":record["legacy_approval_log_sha256"],
        "new_gate_state_path":record["new_gate_state_path"],
        "new_gate_state_sha256":record["new_gate_state_sha256"],
        "github_repo_id":_GITHUB_REPOSITORY_ID,
        "github_pr_number":_GITHUB_CONTROL_PR,
        "owner_actor_id":_GITHUB_OWNER_ID,
    }
    expected=digest(_canonical(req))
    if proof["preflight_digest"]!=expected:
        raise ValueError("owner Github approval preflight binding mismatch")
    if proof["body"]!=owner_comment_body(expected):
        raise ValueError("owner Github approval exact body mismatch")
    if (type(proof["comment_id"]) is not int or proof["comment_id"]<=0
        or proof["url"]!=f"https://github.com/ywjo86-tech/ocpv2-control/pull/1#issuecomment-{proof['comment_id']}"):
        raise ValueError("owner Github approval URL/ID invalid")
    if not isinstance(proof["created_at"],str) or proof["created_at"]!=proof["updated_at"]:
        raise ValueError("owner Github approval edit/timestamp mismatch")
    # Revalidate the live GitHub comment rather than trusting a saved assertion.
    # This enforces the owner identity and exact bound intent at runtime.
    try:
        actual=_fetch_live_owner_comment(proof["comment_id"])
        verified=require_exact_owner_comment(actual,preflight_digest=expected)
    except Exception as exc:
        raise ValueError("live owner Github approval verification failed") from exc
    if verified!=proof:
        raise ValueError("owner Github approval source changed since issuance")

def make_retirement_record(root:Path,*,new_gate_state:str,owner_authorization_ref:str,owner_comment:Mapping|None=None)->dict:
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
 request=owner_preflight(root,new_gate_state=new_gate_state,request_id=owner_authorization_ref)
 proof=require_exact_owner_comment(owner_comment,preflight_digest=digest(_canonical(request)))
 doc["owner_proof"]=proof
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
 _verify_owner_proof(record)
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
