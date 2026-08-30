"""Official production entry for safely adopting a terminated bound workspace."""
from __future__ import annotations
import json,os,tempfile
from pathlib import Path
from typing import Any,Callable,Mapping,Sequence
from .lifecycle_binding import canonical_bytes
from .partial_workspace_recovery import PartialRecoveryMachine,PartialRecoveryError
from .persisted_artifact import validate,publish,PersistedArtifactError

class OfficialAdoptionError(ValueError):pass

def _atomic(path:Path,data:bytes)->None:
 path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=path.name+".",dir=path.parent)
 try:
  with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def reconcile(root:Path,generation:int)->str:
 base=root/f"publication-{generation:02d}";canonical=base/"worker.result.json";alias=root/"worker.result.current.json";commit=base/"COMMITTED"
 if commit.exists():
  if not canonical.is_file() or not alias.is_file():raise OfficialAdoptionError("committed adoption publication is incomplete")
  pointer=json.loads(alias.read_text());
  if pointer.get("canonical")!=canonical.relative_to(root).as_posix():raise OfficialAdoptionError("conflicting adoption alias")
  return "COMMITTED"
 if alias.exists():raise OfficialAdoptionError("alias exists without committed canonical publication")
 return "INVISIBLE"

def official_adopt(*,control_root:str|Path,artifact_root:str|Path,binding:Mapping[str,Any],
 run_id:str,recorded_pid:int,recorded_start:str,process_probe:Callable[[int],str|None],diff:Mapping[str,str],owned_scope:Sequence[str],
 source_sha256:str,predecessor:str,result_payload:Mapping[str,Any],failpoint:str|None=None)->dict[str,Any]:
 root=Path(control_root);art=Path(artifact_root)
 # These are the persisted controls consumed by the official path.
 for name,kind in (("package.json","package"),("preflight.json","preflight"),("worker.request.json","worker_request")):
  validate(art,name,expected_kind=kind,expected_binding=binding,expected_source_sha256=source_sha256,expected_predecessor=predecessor)
 machine=PartialRecoveryMachine(root,binding)
 if machine.state is None:
  for state in ("WORKER_REQUESTED","WORKER_RUNNING","PARTIAL_WORKSPACE_DETECTED"):machine.advance(state)
 if machine.state=="PARTIAL_WORKSPACE_DETECTED":machine.classify_worker(recorded_pid=recorded_pid,recorded_start=recorded_start,process_probe=process_probe,diff=diff,owned_scope=owned_scope)
 if machine.state=="LIVE_BOUND_WORKER":raise OfficialAdoptionError("live bound worker blocks adoption")
 if machine.state=="INVALID_OR_AMBIGUOUS_PARTIAL":raise OfficialAdoptionError("partial workspace is outside owned scope")
 if machine.state=="TERMINATED_ADOPTABLE_PARTIAL":machine.adopt(diff,owned_scope)
 generation=1;base=root/f"publication-{generation:02d}"
 status=reconcile(root,generation)
 if status=="COMMITTED":
  if machine.state=="ADOPTION_VALIDATED":machine.advance("RESULT_PUBLISHED",{"publication":base.name});machine.advance("REVIEW_PENDING")
  _atomic(root/"review.queue.json",canonical_bytes({"schema_version":"orchestration.review-queue.v1","publication":base.name}))
  return {"status":"REVIEW_PENDING","idempotent":True,"review_queued":True}
 canonical,_=publish(base,"worker.result.json",kind="worker_result",payload=result_payload,binding=binding,source_artifact_sha256=source_sha256,predecessor_digest=predecessor)
 if failpoint=="after_canonical":raise OfficialAdoptionError("injected crash after canonical")
 pointer={"schema_version":"orchestration.adoption-alias.v1","canonical":canonical.relative_to(root).as_posix()}
 _atomic(root/"worker.result.current.json",canonical_bytes(pointer))
 if failpoint=="after_alias":raise OfficialAdoptionError("injected crash after alias")
 _atomic(base/"COMMITTED",b"COMMITTED\n")
 if machine.state=="ADOPTION_VALIDATED":machine.advance("RESULT_PUBLISHED",{"publication":base.name});machine.advance("REVIEW_PENDING")
 _atomic(root/"review.queue.json",canonical_bytes({"schema_version":"orchestration.review-queue.v1","publication":base.name}))
 return {"status":"REVIEW_PENDING","idempotent":False,"review_queued":True,"publication":base.name}

def reconcile_and_resume(**kwargs:Any)->dict[str,Any]:
 root=Path(kwargs["control_root"]);base=root/"publication-01";alias=root/"worker.result.current.json"
 if base.joinpath("worker.result.json").exists() and not alias.exists():
  canonical=base/"worker.result.json";_atomic(alias,canonical_bytes({"schema_version":"orchestration.adoption-alias.v1","canonical":canonical.relative_to(root).as_posix()}))
 if alias.exists() and base.joinpath("worker.result.json").exists() and not base.joinpath("COMMITTED").exists():_atomic(base/"COMMITTED",b"COMMITTED\n")
 return official_adopt(**kwargs)
