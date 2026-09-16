from __future__ import annotations

import re
from typing import Callable, Mapping, Sequence

from .contracts import InvocationContext, validate_invocation_context
from .process_service import ProcessService, ProcessServiceError
from .validation_profiles import ValidationProfileCatalog, ValidationProfileError

EXPECTATIONS = {"RESULT_PRESENT", "AUDIT_PRESENT", "EFFECT_RECEIPT_PRESENT", "EXIT_ZERO", "NO_SECURITY_BLOCK", "RESTORE_EQUIVALENT"}
_OP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class ValidationServiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


class ValidationService:
    def __init__(self, context: InvocationContext, catalog: ValidationProfileCatalog, process_service: ProcessService,
                 *, status_provider: Callable[[str], Mapping[str, object] | None] | None = None) -> None:
        validate_invocation_context(context)
        self.context=context; self.catalog=catalog; self.process_service=process_service; self.status_provider=status_provider

    def execute(self, profile_id: str) -> dict[str, object]:
        try: profile=self.catalog.get(profile_id)
        except ValidationProfileError as exc: raise ValidationServiceError("VALIDATION_FAILED", "unknown validation profile") from exc
        if profile.profile_digest not in self.context.validation_profile_digests:
            raise ValidationServiceError("AUTHORIZATION_DENIED", "validation profile is not bound to InvocationContext")
        if profile.env_allowlist:
            raise ValidationServiceError("VALIDATION_FAILED", "non-empty profile env inheritance is not approved")
        try:
            result=self.process_service.execute(argv=profile.argv,cwd=profile.cwd,timeout_seconds=profile.timeout_seconds,env={})
        except ProcessServiceError as exc:
            raise ValidationServiceError(exc.code, "validation process failed") from exc
        return {"profile_id":profile.profile_id,"profile_digest":profile.profile_digest,"kind":profile.kind,
                "exit_code":result["exit_code"],"stdout":result["stdout"],"stderr":result["stderr"]}

    def _raw_status(self, operation_request_id: str) -> Mapping[str, object]:
        if not isinstance(operation_request_id,str) or not _OP_ID.fullmatch(operation_request_id) or self.status_provider is None:
            raise ValidationServiceError("INPUT_SCHEMA_INVALID","operation request id is invalid")
        value=self.status_provider(operation_request_id)
        if not isinstance(value,Mapping) or value.get("operation_request_id") != operation_request_id:
            raise ValidationServiceError("INPUT_SCHEMA_INVALID","operation request id is invalid")
        return value

    def execution_status(self, operation_request_id: str) -> dict[str, object]:
        value=self._raw_status(operation_request_id)
        keys=("operation_request_id","state","started_at","ended_at","result_digest","audit_ref","effect_id")
        if any(key not in value for key in keys): raise ValidationServiceError("INTERNAL_ERROR","status provider is incomplete")
        return {key:value[key] for key in keys}

    def validate(self, operation_request_id: str, expectations: Sequence[str]) -> dict[str, object]:
        if isinstance(expectations,(str,bytes)) or not expectations or len(set(expectations)) != len(tuple(expectations)) or any(v not in EXPECTATIONS for v in expectations):
            raise ValidationServiceError("INPUT_SCHEMA_INVALID","expectations are invalid")
        value=self._raw_status(operation_request_id); checks=[]
        predicates={
            "RESULT_PRESENT": bool(value.get("result_digest")),
            "AUDIT_PRESENT": bool(value.get("audit_ref")),
            "EFFECT_RECEIPT_PRESENT": bool(value.get("effect_id")),
            "EXIT_ZERO": value.get("exit_code") == 0,
            "NO_SECURITY_BLOCK": value.get("security_block") is not True,
            "RESTORE_EQUIVALENT": value.get("restore_equivalent") is True,
        }
        for expectation in expectations:
            ok=predicates[expectation]
            checks.append({"expectation":expectation,"status":"PASS" if ok else "BLOCK",
                           "reason_code":"EXPECTATION_MET" if ok else "EXPECTATION_NOT_MET"})
        return {"verdict":"PASS" if all(item["status"]=="PASS" for item in checks) else "BLOCK","checks":checks}
