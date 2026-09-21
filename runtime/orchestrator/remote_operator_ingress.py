"""Non-authoritative OCPv2 ingress validation and existing-operator bridge."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .operator_control import OperatorDirectiveV1
from .production_execution_gateway import GatewayError, HOST_GATEWAY, validate_gateway_request
from .production_full_plan_runner import ContinuationOwnerToken, DurableFullPlanSupervisor, ProductionFullPlanError
from .production_worker_executor import ProductionWorkerError, execute_production_worker
from .remote_operator_envelope import RemoteOperatorEnvelopeV2
from .remote_operator_outbox import RemoteResultOutbox, RemoteResultProjectionV1
from .remote_operator_receipt import ReceiptStatus, RemoteOperatorReceiptStore
from .runtime_migration_handoff import MigrationHandoffError, MigrationPhase, MigrationStore, RuntimeMigrationTransaction
from .schemas import WorkerRequest


class RemoteExecutionGatewayError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IngressDecision:
    accepted: bool
    result_class: str
    message_id: str
    directive_digest: str
    directive: OperatorDirectiveV1 | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    reconciled: bool
    result_class: str
    message_id: str
    projection_id: str = ""


@dataclass(frozen=True, slots=True)
class CanonicalCompletionEvidence:
    """Exact canonical proof used only to reconstruct OCP transport bookkeeping."""

    message_id: str
    directive_digest: str
    project_id: str
    run_id: str
    gate_id: str
    task_id: str
    canonical_state_ref: str
    canonical_state_sha256: str
    effect_evidence_refs: tuple[str, ...]
    checkpoint_ref: str
    checkpoint_sha256: str
    migration_transaction_sha256: str
    result_summary: str
    completed_at: str


def prepare_existing_operator_directive(envelope: RemoteOperatorEnvelopeV2) -> OperatorDirectiveV1:
    """Re-enter the existing operator contract; no OCP-specific stage authority is created."""
    return OperatorDirectiveV1.from_mapping(envelope.operator_directive.to_dict())


def _blocked(envelope: RemoteOperatorEnvelopeV2, result_class: str) -> IngressDecision:
    return IngressDecision(
        accepted=False,
        result_class=result_class,
        message_id=envelope.message_id,
        directive_digest=envelope.directive_digest,
        directive=None,
    )


def validate_ingress(
    envelope: RemoteOperatorEnvelopeV2,
    *,
    receipt_store: RemoteOperatorReceiptStore,
    allowed_adapter_id: str,
    allowed_channel_id: str,
    allowed_source_actor_ids: Iterable[str],
    expected_risk_envelope_digest: str | None,
) -> IngressDecision:
    """Validate transport/authorization/replay identity before any canonical dispatch.

    Successful validation records transport receipt only.  The returned directive still
    requires the existing Full Plan/continuation/execution-gateway path to perform work.
    """
    allowed_actors = frozenset(str(item) for item in allowed_source_actor_ids)
    if (
        envelope.transport.adapter_id != str(allowed_adapter_id)
        or envelope.transport.channel_id != str(allowed_channel_id)
        or envelope.transport.source_actor_id not in allowed_actors
    ):
        return _blocked(envelope, "SOURCE_NOT_ALLOWED")

    if expected_risk_envelope_digest is not None:
        if envelope.authorization.risk_envelope_digest != str(expected_risk_envelope_digest):
            return _blocked(envelope, "AUTHORIZATION_SCOPE_MISMATCH")

    classification = receipt_store.classify_delivery(envelope)
    if classification == ReceiptStatus.IDEMPOTENT_REPLAY:
        return _blocked(envelope, "IDEMPOTENT_REPLAY")
    if classification == ReceiptStatus.TAMPER_DETECTED:
        return _blocked(envelope, "TAMPER_DETECTED")
    if classification == ReceiptStatus.REPLAY_REJECTED:
        return _blocked(envelope, "REPLAY_REJECTED")

    directive = prepare_existing_operator_directive(envelope)
    receipt_store.record_received(envelope)
    return IngressDecision(
        accepted=True,
        result_class="MESSAGE_RECEIVED",
        message_id=envelope.message_id,
        directive_digest=envelope.directive_digest,
        directive=directive,
    )


def execute_remote_directive_in_canonical_transaction(
    supervisor: DurableFullPlanSupervisor,
    transaction_store: Any,
    *,
    expected_gate_id: str,
    expected_state_sha256: str,
    canonical_state_sha256: Callable[[], str],
    mutation: Callable[[ContinuationOwnerToken], Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Converge a remote mutation on the existing Full Plan single-writer boundary.

    ``canonical_state_sha256`` reads the authoritative external state that the remote
    directive bound before execution (for example a continuation or migration CAS
    projection).  It is checked both before owner claim and again inside the existing
    run-lock -> continuation-transaction lock order.  No OCP-owned lock is introduced.
    """
    expected = str(expected_state_sha256 or "")
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ProductionFullPlanError("STALE_DIRECTIVE: expected canonical state digest is invalid")
    if str(canonical_state_sha256()) != expected:
        raise ProductionFullPlanError("STALE_DIRECTIVE: pre-lock canonical state mismatch")

    owner_token = supervisor.claim_attested_continuation_owner(expected_gate_id=expected_gate_id)
    with supervisor.continuation_transaction(owner_token, transaction_store):
        supervisor.assert_current_epoch_locked(owner_token)
        if str(canonical_state_sha256()) != expected:
            raise ProductionFullPlanError("STALE_DIRECTIVE: in-lock canonical state mismatch")
        result = dict(mutation(owner_token))
        supervisor.assert_current_epoch_locked(owner_token)
        return result


def _assert_optional_runtime_binding(expected: str, current: Callable[[], str], label: str) -> None:
    if expected and str(current()) != expected:
        raise ProductionFullPlanError(f"STALE_DIRECTIVE: {label} mismatch")


def _validate_canonical_worker_request(
    request: WorkerRequest,
    directive: OperatorDirectiveV1,
    envelope: RemoteOperatorEnvelopeV2,
) -> WorkerRequest:
    if not isinstance(request, WorkerRequest):
        raise RemoteExecutionGatewayError("WORKER_REQUEST_BINDING_MISMATCH: canonical resolver returned invalid type")
    if (
        request.task.thread_id != directive.task_id
        or request.task.task_execution_id != directive.task_execution_id
        or request.task.state_change_required is not True
        or (request.task.runtime_stage and request.task.runtime_stage != "ACTION")
    ):
        raise RemoteExecutionGatewayError("WORKER_REQUEST_BINDING_MISMATCH: task identity")

    contract = request.contract_summary
    context = request.extra_context
    if (
        str(contract.get("project_id") or "") != directive.project_id
        or str(contract.get("gate_id") or "") != directive.gate_id
        or str(contract.get("lv_id") or "") != directive.task_id
        or str(context.get("run_id") or "") != directive.run_id
        or str(context.get("gate_id") or "") != directive.gate_id
        or str(context.get("lv_id") or "") != directive.task_id
    ):
        raise RemoteExecutionGatewayError("WORKER_REQUEST_BINDING_MISMATCH: canonical request identity")
    if context.get("execution_backend") != HOST_GATEWAY:
        raise RemoteExecutionGatewayError("HOST_GATEWAY_REQUIRED: remote mutation cannot select another execution backend")
    if envelope.expected.source_head and str(request.state_snapshot.get("head") or "") != envelope.expected.source_head:
        raise RemoteExecutionGatewayError("WORKER_REQUEST_BINDING_MISMATCH: source head")
    if (
        envelope.expected.runtime_release_digest
        and str(context.get("runtime_release_digest") or "") != envelope.expected.runtime_release_digest
    ):
        raise RemoteExecutionGatewayError("WORKER_REQUEST_BINDING_MISMATCH: runtime release")
    return request


def execute_remote_action_through_canonical_full_plan(
    envelope: RemoteOperatorEnvelopeV2,
    directive: OperatorDirectiveV1,
    *,
    supervisor: DurableFullPlanSupervisor,
    transaction_store: Any,
    canonical_continuation_state_sha256: Callable[[], str],
    canonical_run_state_sha256: Callable[[], str],
    current_source_head: Callable[[], str],
    current_runtime_release_digest: Callable[[], str],
    worker_request_resolver: Callable[
        [ContinuationOwnerToken, RemoteOperatorEnvelopeV2, OperatorDirectiveV1], WorkerRequest
    ],
) -> Mapping[str, Any]:
    """Execute a remote ACTION only through canonical Full Plan worker authority.

    OCPv2 contributes no shell, provider, broker, filesystem, or secondary execution
    authority.  The accepted directive is fenced by the existing Full Plan owner/epoch
    transaction, resolves an already-canonical WorkerRequest inside that transaction,
    requires the production HOST_GATEWAY backend, and delegates execution to the existing
    production worker which owns Provider Router and Production Execution Gateway / Full MCP
    integration.
    """
    if directive.directive_digest != envelope.directive_digest or (
        directive.project_id,
        directive.run_id,
        directive.task_id,
        directive.task_execution_id,
        directive.gate_id,
    ) != (
        envelope.project_id,
        envelope.run_id,
        envelope.task_id,
        envelope.task_execution_id,
        envelope.gate_id,
    ):
        raise RemoteExecutionGatewayError("OPERATOR_DIRECTIVE_BLOCKED: envelope/directive binding mismatch")
    if not directive.state_change_required or not (
        directive.current_stage == "PREPARE" and directive.requested_next_stage == "ACTION"
    ):
        raise RemoteExecutionGatewayError("EXECUTION_GATEWAY_BLOCKED: state-changing directive is not ACTION")

    _assert_optional_runtime_binding(
        envelope.expected.canonical_run_state_sha256,
        canonical_run_state_sha256,
        "canonical run state",
    )
    _assert_optional_runtime_binding(envelope.expected.source_head, current_source_head, "source head")
    _assert_optional_runtime_binding(
        envelope.expected.runtime_release_digest,
        current_runtime_release_digest,
        "runtime release",
    )

    def mutation(owner_token: ContinuationOwnerToken) -> Mapping[str, Any]:
        if (
            owner_token.project_id != directive.project_id
            or owner_token.run_id != directive.run_id
            or owner_token.gate_id != directive.gate_id
        ):
            raise ProductionFullPlanError("STALE_DIRECTIVE: continuation owner identity mismatch")
        if owner_token.epoch != envelope.expected.continuation_owner_epoch:
            raise ProductionFullPlanError("STALE_DIRECTIVE: continuation owner epoch mismatch")

        _assert_optional_runtime_binding(
            envelope.expected.canonical_run_state_sha256,
            canonical_run_state_sha256,
            "canonical run state",
        )
        _assert_optional_runtime_binding(envelope.expected.source_head, current_source_head, "source head")
        _assert_optional_runtime_binding(
            envelope.expected.runtime_release_digest,
            current_runtime_release_digest,
            "runtime release",
        )

        request = _validate_canonical_worker_request(
            worker_request_resolver(owner_token, envelope, directive),
            directive,
            envelope,
        )
        try:
            result = execute_production_worker(request)
        except ProductionWorkerError as exc:
            raise RemoteExecutionGatewayError(f"CANONICAL_WORKER_BLOCKED: {exc}") from exc
        if not isinstance(result, Mapping):
            raise RemoteExecutionGatewayError("CANONICAL_WORKER_BLOCKED: worker result is malformed")
        return dict(result)

    return execute_remote_directive_in_canonical_transaction(
        supervisor,
        transaction_store,
        expected_gate_id=directive.gate_id,
        expected_state_sha256=envelope.expected.continuation_state_sha256,
        canonical_state_sha256=canonical_continuation_state_sha256,
        mutation=mutation,
    )


def dispatch_action_through_production_gateway(
    directive: OperatorDirectiveV1,
    *,
    gateway_request: Mapping[str, Any],
    gateway_dispatch: Callable[[Mapping[str, Any]], Mapping[str, Any] | None],
) -> Mapping[str, Any] | None:
    """Route remote ACTION mutation through the existing production gateway contract.

    The transport never receives a broker/file/shell callback.  This bridge accepts only
    a fully built canonical gateway request and delegates execution to the canonical
    gateway dispatch supplied by the existing Harness execution path.
    """
    if not directive.state_change_required:
        return None
    if not (directive.current_stage == "PREPARE" and directive.requested_next_stage == "ACTION"):
        raise RemoteExecutionGatewayError("EXECUTION_GATEWAY_BLOCKED: state-changing directive is not ACTION")
    try:
        validated = validate_gateway_request(
            gateway_request,
            expected={
                "project_id": directive.project_id,
                "run_id": directive.run_id,
                "gate_id": directive.gate_id,
                "lv_id": directive.task_id,
            },
            require_canonical_authority=True,
        )
        result = gateway_dispatch(validated)
    except GatewayError as exc:
        raise RemoteExecutionGatewayError(f"EXECUTION_GATEWAY_BLOCKED: {exc}") from exc
    if result is None:
        raise RemoteExecutionGatewayError("EXECUTION_GATEWAY_BLOCKED: gateway produced no result")
    if not isinstance(result, Mapping):
        raise RemoteExecutionGatewayError("EXECUTION_GATEWAY_BLOCKED: gateway result is malformed")
    return dict(result)


def advance_migration_if_current(
    store: MigrationStore,
    migration_id: str,
    *,
    expected_transaction_sha256: str,
    expected_phase: MigrationPhase,
    next_phase: MigrationPhase,
    expected_qualification_evidence_sha256: str = "",
    updates: Mapping[str, Any] | None = None,
) -> RuntimeMigrationTransaction:
    """Compare exact migration identity/state before delegating to MigrationStore.advance.

    This wrapper deliberately leaves MigrationStore as the sole migration mutation
    authority.  Callers performing a remote mutation must invoke it inside
    ``execute_remote_directive_in_canonical_transaction`` so the existing Full Plan
    owner epoch and transaction lock provide the single-writer boundary.
    """
    tx = store.load(migration_id)
    expected_phase = MigrationPhase(expected_phase)
    next_phase = MigrationPhase(next_phase)
    if tx.transaction_sha256 != str(expected_transaction_sha256):
        raise MigrationHandoffError("STALE_DIRECTIVE: migration transaction CAS mismatch")
    if tx.phase != expected_phase:
        raise MigrationHandoffError("STALE_DIRECTIVE: migration phase CAS mismatch")
    if expected_qualification_evidence_sha256:
        if tx.qualification_evidence_sha256 != str(expected_qualification_evidence_sha256):
            raise MigrationHandoffError("STALE_DIRECTIVE: qualification evidence CAS mismatch")
    elif next_phase == MigrationPhase.PREDECESSOR_CLOSED and tx.schema_version.endswith(".v2"):
        if not tx.qualification_evidence_sha256:
            return store.advance(migration_id, next_phase, updates=updates)
    return store.advance(migration_id, next_phase, updates=updates)


def reconcile_committed_delivery(
    envelope: RemoteOperatorEnvelopeV2,
    *,
    receipt_store: RemoteOperatorReceiptStore,
    outbox: RemoteResultOutbox,
    evidence_resolver: Callable[[str, str], RemoteResultProjectionV1 | None],
) -> ReconciliationDecision:
    """Recover transport bookkeeping only when canonical evidence proves completion.

    This function has no execution callback by construction.  A missing/ambiguous or
    incorrectly bound proof returns ``RECONCILIATION_REQUIRED`` and cannot replay a
    canonical mutation.
    """
    projection = evidence_resolver(envelope.message_id, envelope.directive_digest)
    if projection is None:
        return ReconciliationDecision(False, "RECONCILIATION_REQUIRED", envelope.message_id)
    if (
        projection.message_id != envelope.message_id
        or projection.directive_digest != envelope.directive_digest
        or projection.project_id != envelope.project_id
        or projection.run_id != envelope.run_id
        or projection.gate_id != envelope.gate_id
        or projection.task_id != envelope.task_id
        or projection.result_class != "CANONICAL_ACTION_COMPLETED"
    ):
        return ReconciliationDecision(False, "RECONCILIATION_REQUIRED", envelope.message_id)

    classification = receipt_store.classify_delivery(envelope)
    if classification == ReceiptStatus.NEW:
        receipt_store.record_received(envelope)
    elif classification != ReceiptStatus.IDEMPOTENT_REPLAY:
        return ReconciliationDecision(False, "RECONCILIATION_REQUIRED", envelope.message_id)

    outbox.enqueue_projection(projection)
    canonical_refs = []
    if projection.canonical_state_ref:
        canonical_refs.append(projection.canonical_state_ref)
    canonical_refs.extend(projection.effect_evidence_refs)
    if projection.checkpoint_ref:
        canonical_refs.append(projection.checkpoint_ref)
    receipt_store.record_terminal_projection(
        message_id=envelope.message_id,
        projection_digest=projection.projection_sha256,
        canonical_receipt_refs=tuple(canonical_refs),
    )
    return ReconciliationDecision(
        True,
        "CANONICAL_ACTION_COMPLETED",
        envelope.message_id,
        projection.projection_id,
    )


def reconcile_canonical_completion(
    envelope: RemoteOperatorEnvelopeV2,
    *,
    receipt_store: RemoteOperatorReceiptStore,
    outbox: RemoteResultOutbox,
    canonical_evidence_resolver: Callable[[str, str], CanonicalCompletionEvidence | None],
) -> IngressDecision:
    """Project a proven prior canonical completion without re-accepting execution.

    The returned ``accepted`` flag is always false: reconciliation may rebuild receipt and
    outbox state, but it can never re-enter the mutation path.
    """
    evidence = canonical_evidence_resolver(envelope.message_id, envelope.directive_digest)
    if evidence is None:
        return _blocked(envelope, "RECONCILIATION_REQUIRED")
    if (
        evidence.message_id != envelope.message_id
        or evidence.directive_digest != envelope.directive_digest
        or evidence.project_id != envelope.project_id
        or evidence.run_id != envelope.run_id
        or evidence.gate_id != envelope.gate_id
        or evidence.task_id != envelope.task_id
    ):
        return _blocked(envelope, "RECONCILIATION_REQUIRED")
    projection = RemoteResultProjectionV1(
        projection_id=f"REC-{envelope.envelope_sha256[:24]}",
        message_id=evidence.message_id,
        directive_digest=evidence.directive_digest,
        project_id=evidence.project_id,
        run_id=evidence.run_id,
        gate_id=evidence.gate_id,
        task_id=evidence.task_id,
        canonical_state_ref=evidence.canonical_state_ref,
        canonical_state_sha256=evidence.canonical_state_sha256,
        effect_evidence_refs=tuple(evidence.effect_evidence_refs),
        checkpoint_ref=evidence.checkpoint_ref,
        checkpoint_sha256=evidence.checkpoint_sha256,
        migration_transaction_sha256=evidence.migration_transaction_sha256,
        result_class="CANONICAL_ACTION_COMPLETED",
        result_summary=evidence.result_summary,
        projected_at=evidence.completed_at,
    )
    reconciled = reconcile_committed_delivery(
        envelope,
        receipt_store=receipt_store,
        outbox=outbox,
        evidence_resolver=lambda _message_id, _directive_digest: projection,
    )
    if not reconciled.reconciled:
        return _blocked(envelope, "RECONCILIATION_REQUIRED")
    return _blocked(envelope, "CANONICAL_ACTION_COMPLETED")
