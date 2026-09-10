from __future__ import annotations

"""SC-1.1-CANDIDATE contract-governed Worker tool authorization."""

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


WORKING_SEMANTIC_CONTRACT_VERSION = "SC-4.0-CANDIDATE"
WORKING_DEVELOPMENT_PLAN_VERSION = "DP-5.0-CANDIDATE"
TOOL_AUTH_CONTRACT_VERSION = "tool-authorization.v1"
DEC007_DECISION_REF = "DEC-007"
DEC007_WORKER_TASK_ID = "TASK-4A-08"
DEC007_CONTRACT_IDS = {
    "PROJECT_OWNED_FILE_LIST": "TAC_TASK_4A_08_PROJECT_OWNED_FILE_LIST_V1",
    "PROJECT_OWNED_FILE_READ": "TAC_TASK_4A_08_PROJECT_OWNED_FILE_READ_V1",
    "PROJECT_OWNED_FILE_WRITE": "TAC_TASK_4A_08_PROJECT_OWNED_FILE_WRITE_V1",
}
SECURE_OUTPUT_EXTENSION_POINT = "SECURE_OUTPUT_HANDLING_CONTRACT_REQUIRED"

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_STATUSES = {"CANDIDATE", "APPROVED", "ACTIVE", "REVOKED", "EXPIRED", "SUPERSEDED"}
_CAPABILITIES = {"FILE_READ", "FILE_WRITE", "SEARCH", "SHELL", "TEST", "GIT", "NETWORK", "MODEL_TOOL", "OTHER"}
_INTENTS = {"READ", "WRITE", "SEARCH", "EXECUTE", "VALIDATE", "TRANSFORM", "OTHER"}
_REQUIREMENTS = {"REQUIRED", "OPTIONAL", "UNRELATED"}
_SCOPES = {"IN_SCOPE", "OUT_OF_SCOPE", "PARTIAL"}
_SOURCES = {"REQUIREMENT", "PLAN_TASK", "OWNED_SCOPE", "APPROVAL_RECORD", "POLICY", "USER_DECISION", "MULTIPLE"}
_VALIDITY = {"TASK_ONLY", "PLAN_TASK", "REQUIREMENT"}
_AUTHORITIES = {"REQUIREMENT", "PLAN_TASK", "POLICY", "PRODUCTION_APPROVAL", "USER_DECISION"}
_FORBIDDEN_AUTHORITIES = {"WORKER", "REVIEWER", "TOOL_PROCESS"}
_RAW_KEYS = {"command", "argv", "stdout", "stderr", "output", "path", "url", "host", "query", "secret", "token"}


class ToolAuthorizationError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ToolAuthorizationError(f"{field} is not a safe stable identifier")
    return value


def _refs(values: Sequence[str], field: str) -> tuple[str, ...]:
    result = tuple(_safe_id(value, field) for value in values)
    if len(result) != len(set(result)):
        raise ToolAuthorizationError(f"{field} contains duplicate references")
    return result


@dataclass(frozen=True, slots=True)
class ToolAuthorizationContract:
    contract_id: str
    contract_version: str
    contract_status: str
    worker_task_id: str
    requirement_refs: tuple[str, ...]
    plan_task_refs: tuple[str, ...]
    operation_class_id: str
    capability_class: str
    operation_intent: str
    requirement_binding: str
    scope_binding: str
    scope_authorization_source: str
    authorization_decision_ref: str
    validity_scope: str
    security_obligation_profile: str
    approval_authority: str
    project_id: str = ""
    gate_id: str = ""
    lv_id: str = ""
    run_id: str = ""
    canonical_plan_sha256: str = ""
    requirement_digest: str = ""
    owned_scope_sha256: str = ""
    package_binding_sha256: str = ""
    contract_digest: str = ""

    def unsigned(self) -> dict[str, Any]:
        value = asdict(self); value.pop("contract_digest")
        return value

    def sealed(self) -> "ToolAuthorizationContract":
        validate_contract(self, require_digest=False)
        return replace(self, contract_digest=_digest(self.unsigned()))

    def to_dict(self) -> dict[str, Any]:
        validate_contract(self)
        return asdict(self)


def validate_contract(contract: ToolAuthorizationContract, *, require_digest: bool = True) -> None:
    for field in ("contract_id", "worker_task_id", "operation_class_id", "authorization_decision_ref",
                  "security_obligation_profile", "approval_authority"):
        _safe_id(getattr(contract, field), field)
    _refs(contract.requirement_refs, "requirement_refs")
    _refs(contract.plan_task_refs, "plan_task_refs")
    if contract.contract_version != TOOL_AUTH_CONTRACT_VERSION or contract.contract_status not in _STATUSES:
        raise ToolAuthorizationError("contract version or status is unsupported")
    if contract.operation_class_id == "UNBOUND_OPERATION_CLASS" and contract.contract_status != "CANDIDATE":
        raise ToolAuthorizationError("unbound operation class cannot be approved or active")
    if contract.capability_class not in _CAPABILITIES or contract.operation_intent not in _INTENTS:
        raise ToolAuthorizationError("tool capability or intent is unsupported")
    if contract.requirement_binding not in _REQUIREMENTS or contract.scope_binding not in _SCOPES:
        raise ToolAuthorizationError("requirement or scope binding is unsupported")
    if contract.scope_authorization_source not in _SOURCES or contract.validity_scope not in _VALIDITY:
        raise ToolAuthorizationError("scope authority or validity scope is unsupported")
    if contract.approval_authority in _FORBIDDEN_AUTHORITIES or contract.approval_authority not in _AUTHORITIES:
        raise ToolAuthorizationError("contract approval authority is not permitted")
    if contract.contract_status in {"APPROVED", "ACTIVE"} and contract.requirement_binding == "UNRELATED":
        raise ToolAuthorizationError("unrelated operation cannot be authorized")
    if contract.contract_status in {"APPROVED", "ACTIVE"} and contract.scope_binding != "IN_SCOPE":
        raise ToolAuthorizationError("authorized operation must be in scope")
    if contract.contract_status == "ACTIVE" and not _SHA.fullmatch(contract.package_binding_sha256):
        raise ToolAuthorizationError("active contract lacks package binding")
    if contract.contract_status == "ACTIVE":
        for field in ("project_id", "gate_id", "lv_id", "run_id"):
            _safe_id(getattr(contract, field), field)
        for field in ("canonical_plan_sha256", "requirement_digest", "owned_scope_sha256"):
            if not _SHA.fullmatch(getattr(contract, field)):
                raise ToolAuthorizationError("active contract lifecycle binding is incomplete")
    if require_digest and contract.contract_digest != _digest(contract.unsigned()):
        raise ToolAuthorizationError("contract digest mismatch")


def activate_contract(contract: ToolAuthorizationContract, *, package_binding_sha256: str,
                      authorized_decisions: Mapping[str, str]) -> ToolAuthorizationContract:
    validate_contract(contract)
    decision_authority = authorized_decisions.get(contract.authorization_decision_ref)
    if (contract.contract_status != "APPROVED" or not _SHA.fullmatch(package_binding_sha256)
            or decision_authority != contract.approval_authority
            or decision_authority not in _AUTHORITIES):
        raise ToolAuthorizationError("only a package-bound approved contract can activate")
    return replace(contract, contract_status="ACTIVE", package_binding_sha256=package_binding_sha256,
                   contract_digest="").sealed()


@dataclass(frozen=True, slots=True)
class ToolAuthorizationRequest:
    worker_task_id: str
    worker_action_id: str
    operation_class_id: str
    capability_class: str
    operation_intent: str
    scope_binding: str
    package_binding_sha256: str
    project_id: str = ""
    gate_id: str = ""
    lv_id: str = ""
    run_id: str = ""
    canonical_plan_sha256: str = ""
    requirement_digest: str = ""
    owned_scope_sha256: str = ""


def authorize_tool_operation(contract: ToolAuthorizationContract | None,
                             request: ToolAuthorizationRequest) -> dict[str, Any]:
    if contract is None:
        return {"authorization_status": "BLOCK", "authorization_reason": "CONTRACT_MISSING"}
    try:
        validate_contract(contract)
    except ToolAuthorizationError:
        return {"authorization_status": "BLOCK", "authorization_reason": "CONTRACT_INVALID"}
    if contract.contract_status != "ACTIVE":
        return {"authorization_status": "BLOCK", "authorization_reason": "CONTRACT_NOT_ACTIVE"}
    checks = (
        contract.worker_task_id == request.worker_task_id,
        contract.operation_class_id == request.operation_class_id,
        contract.capability_class == request.capability_class,
        contract.operation_intent == request.operation_intent,
        contract.scope_binding == request.scope_binding == "IN_SCOPE",
        contract.package_binding_sha256 == request.package_binding_sha256,
        contract.project_id == request.project_id,
        contract.gate_id == request.gate_id,
        contract.lv_id == request.lv_id,
        contract.run_id == request.run_id,
        contract.canonical_plan_sha256 == request.canonical_plan_sha256,
        contract.requirement_digest == request.requirement_digest,
        contract.owned_scope_sha256 == request.owned_scope_sha256,
    )
    if not all(checks):
        return {"authorization_status": "BLOCK", "authorization_reason": "CONTRACT_BINDING_MISMATCH"}
    return {"authorization_status": "AUTHORIZED", "authorization_reason": "ACTIVE_EXACT_MATCH",
            "contract_id": contract.contract_id, "worker_action_id": request.worker_action_id,
            "security_obligation_profile": contract.security_obligation_profile}


def owned_scope_digest(owned_files: Sequence[str]) -> str:
    if (not isinstance(owned_files, Sequence) or isinstance(owned_files, (str, bytes))
            or not owned_files or any(not isinstance(item, str) or not item for item in owned_files)
            or len(set(owned_files)) != len(owned_files)):
        raise ToolAuthorizationError("approved owned scope is missing or malformed")
    return _digest(sorted(owned_files))


def dec007_requirement_digest(operation_class_id: str) -> str:
    refs = ["REQ-002", "REQ-011", "REQ-013"]
    if operation_class_id == "PROJECT_OWNED_FILE_WRITE":
        refs.extend(["REQ-007", "REQ-008", "REQ-009", "REQ-010"])
    if operation_class_id not in DEC007_CONTRACT_IDS:
        raise ToolAuthorizationError("operation is outside DEC-007")
    return _digest(refs)


def build_dec007_approved_contracts(*, project_id: str, gate_id: str, lv_id: str,
                                    run_id: str, canonical_plan_sha256: str,
                                    owned_files: Sequence[str]) -> tuple[ToolAuthorizationContract, ...]:
    """Build the exact user-approved DEC-007 set; activation remains package-owned."""
    for value, field in ((project_id, "project_id"), (gate_id, "gate_id"),
                         (lv_id, "lv_id"), (run_id, "run_id")):
        _safe_id(value, field)
    if not _SHA.fullmatch(canonical_plan_sha256):
        raise ToolAuthorizationError("DEC-007 canonical plan binding is invalid")
    scope_digest = owned_scope_digest(owned_files)
    semantics = {
        "PROJECT_OWNED_FILE_LIST": ("FILE_READ", "READ", ("REQ-002", "REQ-011", "REQ-013")),
        "PROJECT_OWNED_FILE_READ": ("FILE_READ", "READ", ("REQ-002", "REQ-011", "REQ-013")),
        "PROJECT_OWNED_FILE_WRITE": ("FILE_WRITE", "WRITE",
            ("REQ-002", "REQ-007", "REQ-008", "REQ-009", "REQ-010", "REQ-011", "REQ-013")),
    }
    contracts = []
    for operation_class_id, (capability, intent, refs) in semantics.items():
        contracts.append(ToolAuthorizationContract(
            contract_id=DEC007_CONTRACT_IDS[operation_class_id],
            contract_version=TOOL_AUTH_CONTRACT_VERSION, contract_status="APPROVED",
            worker_task_id=DEC007_WORKER_TASK_ID, requirement_refs=refs,
            plan_task_refs=(DEC007_WORKER_TASK_ID,), operation_class_id=operation_class_id,
            capability_class=capability, operation_intent=intent, requirement_binding="REQUIRED",
            scope_binding="IN_SCOPE", scope_authorization_source="USER_DECISION",
            authorization_decision_ref=DEC007_DECISION_REF, validity_scope="TASK_ONLY",
            security_obligation_profile="SECRET_SCAN_REQUIRED", approval_authority="USER_DECISION",
            project_id=project_id, gate_id=gate_id, lv_id=lv_id, run_id=run_id,
            canonical_plan_sha256=canonical_plan_sha256,
            requirement_digest=dec007_requirement_digest(operation_class_id),
            owned_scope_sha256=scope_digest,
        ).sealed())
    return tuple(contracts)


def build_contract_candidate(provenance: Mapping[str, Any]) -> dict[str, Any]:
    operation = provenance.get("security_operation_class_id", "UNBOUND_OPERATION_CLASS")
    if not isinstance(operation, str) or not _ID.fullmatch(operation):
        operation = "UNBOUND_OPERATION_CLASS"
    bounded = {
        "worker_task_id": provenance.get("worker_task_id", "UNKNOWN"),
        "worker_action_id": provenance.get("worker_action_id", "UNKNOWN"),
        "operation_class_id": operation,
        "capability_class": provenance.get("security_tool_capability", "UNKNOWN"),
        "operation_intent": provenance.get("security_tool_operation_intent", "UNKNOWN"),
        "current_requirement_binding": provenance.get("tool_operation_requirement_binding", "UNKNOWN"),
        "current_scope_binding": provenance.get("tool_scope_binding", "UNKNOWN"),
    }
    missing = [field for field, value in (
        ("OPERATION_CLASS_ID", bounded["operation_class_id"]),
        ("REQUIREMENT_BINDING", bounded["current_requirement_binding"]),
        ("SCOPE_BINDING", bounded["current_scope_binding"]),
        ("AUTHORIZATION_DECISION_REF", "UNKNOWN"),
    ) if value in {"UNKNOWN", "UNBOUND_OPERATION_CLASS"}]
    candidate_id = "TAC-" + _digest(bounded)[:24]
    return {"candidate_id": candidate_id, **bounded, "missing_authority_fields": missing,
            "candidate_status": "DECISION_REQUIRED", "contract_status": "CANDIDATE",
            "authorization_status": "BLOCK"}


class ContractGovernedToolBroker:
    """Calls the launcher only after exact ACTIVE authorization succeeds."""

    def __init__(self, launcher: Callable[[], Any], security_scan: Callable[[Any], bool]) -> None:
        self._launcher = launcher
        self._security_scan = security_scan

    def execute(self, contract: ToolAuthorizationContract | None,
                request: ToolAuthorizationRequest) -> tuple[Any, dict[str, Any]]:
        authorization = authorize_tool_operation(contract, request)
        if authorization["authorization_status"] != "AUTHORIZED":
            raise ToolAuthorizationError("tool operation authorization blocked")
        result = self._launcher()
        if not self._security_scan(result):
            raise ToolAuthorizationError("authorized tool output failed security validation")
        trace = {"requirement_refs": list(contract.requirement_refs),
                 "plan_task_refs": list(contract.plan_task_refs),
                 "worker_task_id": request.worker_task_id, "contract_id": contract.contract_id,
                 "worker_action_id": request.worker_action_id,
                 "authorization_result": "AUTHORIZED", "security_result": "PASS"}
        return result, trace


@dataclass(frozen=True, slots=True)
class RegisteredOperation:
    operation_registration_id: str
    operation_class_id: str
    capability_class: str
    operation_intent: str
    effect_class: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]

    def validate(self) -> None:
        for field in ("operation_registration_id", "operation_class_id", "effect_class"):
            _safe_id(getattr(self, field), field)
        if self.operation_class_id == "UNBOUND_OPERATION_CLASS":
            raise ToolAuthorizationError("unbound operation cannot enter the closed registry")
        if self.capability_class not in _CAPABILITIES or self.operation_intent not in _INTENTS:
            raise ToolAuthorizationError("registered operation taxonomy is invalid")
        for schema in (self.input_schema, self.output_schema):
            if (not isinstance(schema, Mapping) or schema.get("type") != "object"
                    or schema.get("additionalProperties") is not False):
                raise ToolAuthorizationError("registered operation schema must be closed")


class ClosedOperationRegistry:
    """Exact registry: unknown names and duplicate identities are always blocked."""

    def __init__(self, operations: Sequence[RegisteredOperation]) -> None:
        self._operations: dict[str, RegisteredOperation] = {}
        for operation in operations:
            operation.validate()
            if operation.operation_class_id in self._operations:
                raise ToolAuthorizationError("duplicate operation class")
            self._operations[operation.operation_class_id] = operation
        if not self._operations:
            raise ToolAuthorizationError("closed operation registry is empty")

    def resolve(self, operation_class_id: str) -> RegisteredOperation:
        _safe_id(operation_class_id, "operation_class_id")
        try:
            return self._operations[operation_class_id]
        except KeyError as exc:
            raise ToolAuthorizationError("unknown operation blocked") from exc

    def dynamic_specs(self, operation_class_ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
        operations: list[RegisteredOperation] = []
        if operation_class_ids is None:
            operations = list(self._operations.values())
        else:
            seen: set[str] = set()
            for operation_class_id in operation_class_ids:
                operation = self.resolve(operation_class_id)
                if operation.operation_class_id in seen:
                    raise ToolAuthorizationError("duplicate operation class")
                seen.add(operation.operation_class_id)
                operations.append(operation)
            if not operations:
                raise ToolAuthorizationError("closed dynamic registry is empty")
        return [{"type": "function", "name": item.operation_class_id,
                 "description": (
                     f"Broker-governed {item.capability_class.lower()} operation. "
                     f"Use only this dynamic tool for approved {item.operation_intent.lower()} effects; "
                     "do not use native filesystem, shell, or environment access."
                 ),
                 "inputSchema": dict(item.input_schema)}
                for item in operations]

    def evidence(self) -> dict[str, Any]:
        return {"registry_kind": "CLOSED_EXACT", "operation_count": len(self._operations),
                "operation_class_ids": sorted(self._operations), "unknown_policy": "BLOCK",
                "wildcard_present": False}


@dataclass(frozen=True, slots=True)
class OperationIdentity:
    operation_registration_id: str
    operation_dispatch_id: str
    operation_callsite_id: str
    operation_class_id: str
    worker_task_id: str
    worker_action_id: str
    project_id: str
    gate_id: str
    lv_id: str
    run_id: str
    plan_digest: str
    requirement_digest: str
    package_digest: str
    owned_scope_sha256: str

    def validate(self) -> None:
        for field in ("operation_registration_id", "operation_dispatch_id", "operation_callsite_id",
                      "operation_class_id", "worker_task_id", "worker_action_id", "project_id",
                      "gate_id", "lv_id", "run_id"):
            _safe_id(getattr(self, field), field)
        for field in ("plan_digest", "requirement_digest", "package_digest", "owned_scope_sha256"):
            if not _SHA.fullmatch(getattr(self, field)):
                raise ToolAuthorizationError("operation identity digest binding is invalid")

    @property
    def effect_id(self) -> str:
        self.validate()
        return "TE-" + _digest(asdict(self))[:32]


class ToolEffectJournal:
    """Create-once intent/receipt journal with ambiguous recovery blocking."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, effect_id: str, kind: str) -> Path:
        _safe_id(effect_id, "effect_id")
        return self.root / f"{effect_id}.{kind}.json"

    def _append_once(self, path: Path, payload: Mapping[str, Any]) -> None:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ToolAuthorizationError("duplicate logical effect blocked") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
            handle.flush(); os.fsync(handle.fileno())
        directory = os.open(self.root, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)

    def _read_payload(self, path: Path) -> dict[str, Any]:
        if not path.is_file() or path.is_symlink():
            raise ToolAuthorizationError("tool effect evidence is missing or unsafe")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ToolAuthorizationError("tool effect evidence is malformed") from exc
        if not isinstance(payload, dict):
            raise ToolAuthorizationError("tool effect evidence is malformed")
        return payload

    def begin(
        self,
        identity: OperationIdentity,
        authorization: Mapping[str, Any],
        *,
        scope_ref: str = "",
    ) -> str:
        effect_id = identity.effect_id
        if not isinstance(scope_ref, str):
            raise ToolAuthorizationError("effect scope ref is malformed")
        if self._path(effect_id, "receipt").exists():
            raise ToolAuthorizationError("completed logical effect cannot rerun")
        self._append_once(
            self._path(effect_id, "intent"),
            {
                "schema_version": "orchestration.tool-effect-intent.v2",
                "effect_id": effect_id,
                "operation": identity.operation_class_id,
                "scope_ref": scope_ref,
                "identity": asdict(identity),
                "authorization_status": authorization.get("authorization_status"),
            },
        )
        return effect_id

    def complete(
        self,
        identity: OperationIdentity,
        *,
        execution_status: str,
        security_status: str,
    ) -> None:
        if execution_status not in {"COMPLETED", "FAILED"} or security_status not in {"PASS", "BLOCK"}:
            raise ToolAuthorizationError("bounded receipt taxonomy is invalid")
        effect_id = identity.effect_id
        intent_path = self._path(effect_id, "intent")
        if not intent_path.exists():
            raise ToolAuthorizationError("effect receipt lacks intent")
        intent = self._read_payload(intent_path)
        if (
            intent.get("schema_version") != "orchestration.tool-effect-intent.v2"
            or intent.get("effect_id") != effect_id
            or intent.get("operation") != identity.operation_class_id
            or intent.get("identity") != asdict(identity)
            or intent.get("authorization_status") != "AUTHORIZED"
        ):
            raise ToolAuthorizationError("effect intent binding is invalid")
        intent_digest = _digest(intent)
        self._append_once(
            self._path(effect_id, "receipt"),
            {
                "schema_version": "orchestration.tool-effect-receipt.v2",
                "effect_id": effect_id,
                "intent_digest": intent_digest,
                "execution_status": execution_status,
                "security_status": security_status,
                "authoritative_completion_binding": _digest(asdict(identity)),
            },
        )

    def recovery_state(self, identity: OperationIdentity) -> str:
        intent = self._path(identity.effect_id, "intent").exists()
        receipt = self._path(identity.effect_id, "receipt").exists()
        if receipt: return "COMPLETED_NO_RERUN"
        if intent: return "BLOCKED_RECOVERY_AMBIGUOUS"
        return "NOT_STARTED"


class SingleToolBroker:
    """Closed-registry, contract-authorized, journaled production effect path."""

    def __init__(self, *, registry: ClosedOperationRegistry,
                 contracts: Mapping[str, ToolAuthorizationContract],
                 journal: ToolEffectJournal,
                 launchers: Mapping[str, Callable[[Mapping[str, Any]], Any]],
                 security_scan: Callable[[Any], bool]) -> None:
        self.registry = registry
        self.contracts = dict(contracts)
        self.journal = journal
        self.launchers = dict(launchers)
        self.security_scan = security_scan

    def execute_with_private_result(
        self,
        identity: OperationIdentity,
        arguments: Mapping[str, Any],
        *,
        scope_ref: str = "",
    ) -> tuple[dict[str, Any], Any]:
        identity.validate()
        operation = self.registry.resolve(identity.operation_class_id)
        if not isinstance(arguments, Mapping):
            raise ToolAuthorizationError("operation arguments are malformed")
        properties = operation.input_schema.get("properties", {})
        required = operation.input_schema.get("required", [])
        if (not isinstance(properties, Mapping) or not isinstance(required, list)
                or any(key not in arguments for key in required)
                or any(key not in properties for key in arguments)):
            raise ToolAuthorizationError("operation arguments violate closed schema")
        if operation.operation_registration_id != identity.operation_registration_id:
            raise ToolAuthorizationError("operation registry identity mismatch")
        contract = self.contracts.get(identity.operation_class_id)
        request = ToolAuthorizationRequest(
            worker_task_id=identity.worker_task_id, worker_action_id=identity.worker_action_id,
            operation_class_id=identity.operation_class_id, capability_class=operation.capability_class,
            operation_intent=operation.operation_intent, scope_binding="IN_SCOPE",
            package_binding_sha256=identity.package_digest,
            project_id=identity.project_id, gate_id=identity.gate_id, lv_id=identity.lv_id,
            run_id=identity.run_id, canonical_plan_sha256=identity.plan_digest,
            requirement_digest=identity.requirement_digest,
            owned_scope_sha256=identity.owned_scope_sha256,
        )
        authorization = authorize_tool_operation(contract, request)
        if authorization["authorization_status"] != "AUTHORIZED":
            raise ToolAuthorizationError("tool operation authorization blocked")
        launcher = self.launchers.get(identity.operation_class_id)
        if launcher is None:
            raise ToolAuthorizationError("registered launcher unavailable")
        effect_id = self.journal.begin(identity, authorization, scope_ref=scope_ref)
        raw_private_result = launcher(dict(arguments))
        security_ok = bool(self.security_scan(raw_private_result))
        self.journal.complete(identity, execution_status="COMPLETED",
                              security_status="PASS" if security_ok else "BLOCK")
        if not security_ok:
            raise ToolAuthorizationError("authorized tool output failed security validation")
        return {"status": "COMPLETED", "result_presence": "PRESENT",
                "security_status": "PASS", "effect_id": effect_id,
                "bounded_result": {"status": "COMPLETED"}}, raw_private_result

    def execute(self, identity: OperationIdentity, arguments: Mapping[str, Any]) -> dict[str, Any]:
        bounded, _private = self.execute_with_private_result(identity, arguments)
        return bounded
