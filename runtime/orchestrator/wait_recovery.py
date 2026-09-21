"""Typed wait reason classification; no recovery side effects."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping

class WaitRecoveryError(ValueError): pass
@dataclass(frozen=True,slots=True)
class WaitRecoveryAssessment:
    state:str; reason:str; owner:str; auto_recoverable:bool

_RULES={
 ("WAITING_RESOURCE","OPERATOR_TASK_RECEIPT_PENDING"):("DCC_OR_OPERATOR",True),
 ("WAITING_RESOURCE","CONTINUATION_RECOVERY_PENDING"):("DCC_RECONCILER",True),
 ("WAITING_RESOURCE","LOW_RESOURCE_BACKPRESSURE"):("RESOURCE_RECOVERY",True),
 ("WAITING_RESOURCE","RUNTIME_MIGRATION_QUIESCED"):("RUNTIME_MIGRATION",False),
 ("WAITING_PROVIDER","PROVIDER_UNAVAILABLE"):("PROVIDER_RECOVERY",True),
 ("WAITING_PROVIDER","PROVIDER_RECOVERY_PENDING"):("PROVIDER_RECOVERY",True),
}
def classify_wait_recovery(value:Mapping[str,Any])->WaitRecoveryAssessment:
    state=str(value.get("state") or ""); reason=str(value.get("last_error") or value.get("wait_reason") or "")
    if state=="WAITING_APPROVAL": return WaitRecoveryAssessment(state,reason,"USER_DECISION",False)
    rule=_RULES.get((state,reason))
    if rule is None: raise WaitRecoveryError("unknown or incompatible wait reason")
    return WaitRecoveryAssessment(state,reason,rule[0],rule[1])
