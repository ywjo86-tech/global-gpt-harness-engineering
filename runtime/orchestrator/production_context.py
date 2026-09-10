"""Bound, minimal production contexts resolved from validated artifact indexes."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from typing import Any,Mapping,Sequence
from .lifecycle_binding import canonical_bytes
from .persisted_artifact import validate,PersistedArtifactError

class ProductionContextError(ValueError):pass

class ProductionContextBuilder:
 def __init__(self):self.cache={};self.calls=0;self.bytes_sent=0;self.hits=0;self.misses=0
 def build(self,*,artifact_root:str|Path,index:Sequence[Mapping[str,Any]],binding:Mapping[str,Any],source_sha256:str,predecessor:str,completed_lvs:Sequence[str],audience:str)->dict[str,Any]:
  if audience not in {"worker","reviewer"}:raise ProductionContextError("invalid context audience")
  binding_key=hashlib.sha256(canonical_bytes(binding)).hexdigest();items=[];seen=set()
  for row in index:
   if row.get("lv_id") in completed_lvs:continue
   identity=(str(row.get("path")),str(row.get("kind")))
   if identity in seen:continue
   seen.add(identity);cache_key=(binding_key,*identity)
   try:
    artifact=validate(artifact_root,identity[0],expected_kind=identity[1],expected_binding=binding,expected_source_sha256=source_sha256,expected_predecessor=predecessor)
   except PersistedArtifactError:
    self.cache.pop(cache_key,None);raise
   fingerprint=artifact.raw_payload_sha256
   cached=self.cache.get(cache_key)
   if cached and cached[0]==fingerprint:self.hits+=1;item=cached[1]
   else:
    self.misses+=1;item={"lv_id":row.get("lv_id"),"kind":artifact.kind,"sha256":fingerprint}
    # Workers only need identity/integrity metadata.  Free-form summaries can
    # contain examples or source echoes and must not propagate into a
    # production implementation prompt.  Reviewers retain the descriptive
    # fields because their job explicitly requires evidence interpretation.
    if audience=="reviewer":
     item["checkpoint_summary"]=row.get("checkpoint_summary") or artifact.payload.get("summary","")
     item["review_evidence"]=artifact.payload.get("review_evidence",[])
    self.cache[cache_key]=(fingerprint,item);self.calls+=1
   items.append(item)
  context={"schema_version":"orchestration.production-context.v1","audience":audience,"artifacts":items,"binding_sha256":binding_key,"validation":"PERSISTED_BYTES_VALIDATED"}
  size=len(canonical_bytes(context));self.bytes_sent+=size
  return {**context,"metrics":{"calls":self.calls,"bytes":size,"cumulative_bytes":self.bytes_sent,"estimated_tokens":(size+3)//4,"cache_hits":self.hits,"cache_misses":self.misses}}

def build_production_context(request:Mapping[str,Any])->dict[str,Any]:
 builder=request.get("builder")
 if not isinstance(builder,ProductionContextBuilder):raise ProductionContextError("production context builder required")
 return builder.build(**{k:v for k,v in request.items() if k!="builder"})
