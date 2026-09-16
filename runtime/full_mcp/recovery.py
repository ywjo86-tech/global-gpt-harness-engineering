from __future__ import annotations

from dataclasses import dataclass

POLICY_BLOCK_ERRORS = frozenset({"AUTHENTICATION_FAILED","AUTHORIZATION_DENIED","INPUT_SCHEMA_INVALID","WORKSPACE_VIOLATION",
    "PATH_POLICY_VIOLATION","SYMLINK_VIOLATION","SENSITIVE_PATH_BLOCKED","COMMAND_NOT_ALLOWED","GIT_BOUNDARY_VIOLATION",
    "EFFECT_REPLAY_BLOCKED","RECOVERY_AMBIGUOUS"})
OPERATIONAL_ERRORS = frozenset({"PROCESS_SPAWN_FAILED","PROCESS_TIMEOUT","PROCESS_CANCELLED","PERSISTENCE_FAILED","INTERNAL_ERROR"})
REMEDIATION_ERRORS = frozenset({"NONZERO_EXIT","OUTPUT_LIMIT_EXCEEDED","SECRET_OUTPUT_BLOCKED","PATCH_CONFLICT","VALIDATION_FAILED"})
EFFECT_STATES = frozenset({"NOT_STARTED","BLOCKED_RECOVERY_AMBIGUOUS","COMPLETED_NO_RERUN"})


class RecoveryPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    classification: str
    auto_retry_allowed: bool
    requires_restore_or_remediation: bool
    reason_code: str


def classify_recovery(*, error_code: str, effect_state: str, state_changing: bool) -> RecoveryDecision:
    if not isinstance(state_changing,bool) or effect_state not in EFFECT_STATES:
        raise RecoveryPolicyError("recovery inputs are invalid")
    if effect_state=="COMPLETED_NO_RERUN":
        return RecoveryDecision("COMPLETED_NO_RERUN",False,False,"TRUSTED_RECEIPT_PRESENT")
    if effect_state=="BLOCKED_RECOVERY_AMBIGUOUS":
        return RecoveryDecision("RECOVERY_REQUIRED",False,True,"EFFECT_INTENT_WITHOUT_TRUSTED_RECEIPT")
    if error_code in POLICY_BLOCK_ERRORS:
        return RecoveryDecision("BLOCKED",False,False,"POLICY_OR_GOVERNANCE_BLOCK")
    if error_code in OPERATIONAL_ERRORS:
        if state_changing: return RecoveryDecision("REMEDIATION_REQUIRED",False,True,"STATE_CHANGE_NOT_AUTO_REPLAYED")
        return RecoveryDecision("RETRY_ELIGIBLE",True,False,"READ_ONLY_OPERATIONAL_FAILURE")
    if error_code in REMEDIATION_ERRORS:
        return RecoveryDecision("REMEDIATION_REQUIRED",False,True,"VALIDATION_OR_EXECUTION_REMEDIATION")
    raise RecoveryPolicyError("error code is outside recovery primitive taxonomy")
