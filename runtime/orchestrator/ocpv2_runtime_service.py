"""Deployed OCPv2 one-shot composition with canonical Full Plan mutation authority.

Transport remains non-authoritative.  Non-mutating modes only validate/project.  A
state-changing directive in CANARY/ACTIVE can call only the registered Full Plan resume
adapter, which owns exact state/owner CAS and then returns control to the existing Full
Plan -> Provider Router -> Production Execution Gateway -> Full MCP path.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from runtime.ai_office.activation import coordinate_approved_activation
from runtime.ai_office.full_plan_activation import coordinate_approved_full_plan_activation
from runtime.ai_office.state_store import AIOfficeStateStore
from runtime.operator_transport.github_control_adapter import GitHubControlAdapter, GitHubControlConfig
from runtime.operator_transport.github_rest_client import PUBLIC_SOURCE_REPOSITORY_ID, GitHubRESTClient
from .approved_full_plan_binding import validate_approved_full_plan_binding
from .approved_work_binding import validate_approved_work_binding
from .harness_state_root import resolve_harness_state_root
from .full_plan_activation import FullPlanActivationStore, activate_approved_full_plan
from .host_inspection_port import HostInspectionPort
from .plan_activation import PlanActivationStore, activate_approved_work
from .project_onboarding import OnboardingRegistry
from .project_onboarding_remote import ProjectOnboardingAdmission
from .ocpv2_canonical_recovery import recover_pending_canonical_results, resolve_registered_full_plan_completion
from .ocpv2_canonical_resume import execute_registered_full_plan_continuation
from .read_only_host_diagnostic import execute_read_only_host_diagnostic
from .read_only_host_diagnostic_contract import DiagnosticContractError, DiagnosticPolicy, diagnostic_feature_enabled
from .remote_diagnostic_outbox import RemoteDiagnosticOutbox, RemoteDiagnosticProjectionV1
from .remote_control_envelope import RemoteControlEnvelopeV1, decode_remote_control_payload
from .remote_operator_envelope import (
    RemoteControlEnvelope, RemoteOperatorEnvelopeV3,
    validate_remote_control_envelope as validate_remote_operator_control_envelope,
)
from .remote_operator_ingress import validate_ingress
from .remote_operator_outbox import (
    RemoteActivationProjectionV1, RemoteFullPlanActivationProjectionV1, RemoteInspectionProjectionV1, RemoteProjectionV1,
    RemoteResultOutbox, RemoteResultProjectionV1, parse_remote_projection,
)
from .remote_operator_receipt import RemoteOperatorReceiptStore
from .remote_operator_recovery_binding import RemoteExecutionBindingStore
from .production_run_authority import executor_runtime_identity
from .runtime_release import RuntimeReleaseError, RuntimeReleaseManifest, verify_runtime_release
from .remote_operator_service import CanaryScope, ControlMode, RemoteOperatorService, RemoteOperatorServiceError


_REQUIRED_ENV = {
    "OCP_MODE",
    "OCP_GITHUB_CONTROL_REPOSITORY_ID",
    "OCP_GITHUB_CONTROL_PR_NUMBER",
    "OCP_GITHUB_ALLOWED_ACTOR_IDS",
    "OCP_GITHUB_TOKEN_FILE",
    "OCP_STATE_ROOT",
    "OCP_REPO_ROOT",
}
_OPTIONAL_ENV = {
    "GCH_STATE_ROOT",
    "OCP_CANARY_PROJECT_ID",
    "OCP_CANARY_RUN_ID",
    "OCP_CANARY_TASK_ID",
    "OCP_CANARY_GATE_ID",
    "OCP_CANARY_DIRECTIVE_ID",
    "OCP_HOST_INSPECTION_ENABLED",
    "OCP_WORK_ACTIVATION_ENABLED",
    "OCP_WORK_ACTIVATION_POLICY_REF",
    "OCP_FULL_PLAN_ACTIVATION_ENABLED",
    "OCP_FULL_PLAN_ACTIVATION_POLICY_REF",
    "OCP_PROJECT_ONBOARDING_ENABLED",
    "OCP_PROJECT_ONBOARDING_POLICY_REF",
    "HARNESS_CONTRACT_MAPPING_ROOT",
    "GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED",
    "GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG",
}
_PROJECTION_SECRET = re.compile(
    rb"(?i)(api[_-]?key|authorization|bearer|password|token|credential|secret)\s*[:=]\s*([^\s,;}]+)"
)


class RuntimeServiceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    mode: ControlMode
    repo_root: Path
    control_repository_id: int
    control_pr_number: int
    allowed_actor_ids: tuple[str, ...]
    token_file: Path | None
    state_root: Path | None
    environment: Mapping[str, str]
    host_inspection_enabled: bool = False
    work_activation_enabled: bool = False
    activation_policy_ref: str = ""
    full_plan_activation_enabled: bool = False
    full_plan_activation_policy_ref: str = ""
    diagnostic_enabled: bool = False
    diagnostic_policy: DiagnosticPolicy | None = None
    project_onboarding_enabled: bool = False
    project_onboarding_policy_ref: str = ""


def host_inspection_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    """Enable only on the exact explicit value `1`; absent/invalid stays fail-closed."""
    return str(environment.get("OCP_HOST_INSPECTION_ENABLED") or "").strip() == "1"


def work_activation_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    """Enable only on exact `1`; all other values fail closed."""
    return str(environment.get("OCP_WORK_ACTIVATION_ENABLED") or "").strip() == "1"


def full_plan_activation_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    """Enable executable Full Plan registration only on exact `1`."""
    return str(environment.get("OCP_FULL_PLAN_ACTIVATION_ENABLED") or "").strip() == "1"


def project_onboarding_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    """Enable create-once project onboarding only on the exact explicit value `1`."""
    return str(environment.get("OCP_PROJECT_ONBOARDING_ENABLED") or "").strip() == "1"


def _runtime_release_for_root(root: Path) -> RuntimeReleaseManifest:
    manifest_path = root / "RUNTIME_RELEASE_MANIFEST.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeServiceError("WORK_ACTIVATION_RUNTIME_RELEASE_REQUIRED")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("manifest must be object")
        manifest = RuntimeReleaseManifest.from_mapping(value)
        return verify_runtime_release(root, manifest.source_head)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeServiceError("WORK_ACTIVATION_RUNTIME_RELEASE_INVALID") from exc


def finalize_remote_control_projection(
    outbox: RemoteResultOutbox, projection: Mapping[str, Any],
) -> None:
    schema = str(projection.get("schema_version") or "")
    if schema in {
        "orchestration.remote-inspection-status-projection.v1",
        "orchestration.remote-activation-status-projection.v1",
        "orchestration.remote-full-plan-activation-status-projection.v1",
        "orchestration.remote-project-onboarding-status-projection.v1",
    }:
        return
    parsed = parse_remote_projection(projection)
    if not isinstance(parsed, (RemoteInspectionProjectionV1, RemoteActivationProjectionV1, RemoteFullPlanActivationProjectionV1)):
        raise RuntimeServiceError("REMOTE_CONTROL_PROJECTION_MISMATCH")
    outbox.mark_published(parsed.projection_id, parsed.projection_sha256)


def _projection_secret_findings(payload: bytes) -> dict[str, int]:
    findings: dict[str, int] = {}
    for match in _PROJECTION_SECRET.finditer(payload):
        kind = match.group(1).decode("ascii", errors="ignore").lower()
        findings[kind] = findings.get(kind, 0) + 1
    return findings


def _safe_id(value: object, label: str) -> str:
    text = str(value or "")
    if not text or len(text) > 200 or "/" in text or "\\" in text or ".." in text:
        raise RuntimeServiceError(f"unsafe {label}")
    return text


def _read_env_file(path: str | Path) -> dict[str, str]:
    source = Path(path).expanduser().absolute()
    if source.is_symlink() or not source.is_file():
        raise RuntimeServiceError("environment file must be a regular non-symlink file")
    result: dict[str, str] = {}
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeServiceError("environment file contains malformed entry")
        key, value = line.split("=", 1)
        key = key.strip()
        if key in result:
            raise RuntimeServiceError("environment file contains duplicate key")
        result[key] = value.strip()
    if not _REQUIRED_ENV.issubset(result):
        raise RuntimeServiceError("environment file required key set mismatch")
    unexpected = set(result) - _REQUIRED_ENV - _OPTIONAL_ENV
    if unexpected:
        raise RuntimeServiceError("environment file contains unsupported key")
    return result


def load_runtime_config(path: str | Path, *, process_environment: Mapping[str, str] | None = None) -> RuntimeConfig:
    file_env = _read_env_file(path)
    environment = dict(process_environment or os.environ)
    environment.update(file_env)
    try:
        mode = ControlMode(file_env["OCP_MODE"])
    except ValueError as exc:
        raise RuntimeServiceError("UNKNOWN_MODE") from exc
    try:
        diagnostic_enabled = diagnostic_feature_enabled(file_env)
    except DiagnosticContractError as exc:
        raise RuntimeServiceError("invalid diagnostic feature flag") from exc
    diagnostic_policy: DiagnosticPolicy | None = None
    if diagnostic_enabled:
        raw_config = str(file_env.get("GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG", "")).strip()
        if not raw_config:
            raise RuntimeServiceError("diagnostic config is required when feature is enabled")
        try:
            diagnostic_policy = DiagnosticPolicy.load(Path(raw_config).expanduser())
        except DiagnosticContractError as exc:
            raise RuntimeServiceError("diagnostic config is invalid") from exc
    repo_root = Path(file_env["OCP_REPO_ROOT"]).expanduser().absolute()
    if repo_root.is_symlink() or not repo_root.is_dir():
        raise RuntimeServiceError("repo root must be an existing non-symlink directory")
    if mode == ControlMode.DISABLED:
        return RuntimeConfig(
            mode, repo_root, 0, 0, (), None, None, environment, False, False, "",
            diagnostic_enabled=diagnostic_enabled, diagnostic_policy=diagnostic_policy,
        )
    try:
        repository_id = int(file_env["OCP_GITHUB_CONTROL_REPOSITORY_ID"])
        pr_number = int(file_env["OCP_GITHUB_CONTROL_PR_NUMBER"])
    except ValueError as exc:
        raise RuntimeServiceError("control repository/PR IDs must be integers") from exc
    if repository_id <= 0 or repository_id == PUBLIC_SOURCE_REPOSITORY_ID or pr_number <= 0:
        raise RuntimeServiceError("control repository/PR binding is invalid")
    actor_ids = tuple(item.strip() for item in file_env["OCP_GITHUB_ALLOWED_ACTOR_IDS"].split(",") if item.strip())
    if not actor_ids or len(set(actor_ids)) != len(actor_ids) or any(not item.isdecimal() or int(item) <= 0 for item in actor_ids):
        raise RuntimeServiceError("allowed actor IDs are invalid")
    token_file = Path(file_env["OCP_GITHUB_TOKEN_FILE"]).expanduser().absolute()
    if token_file.is_symlink() or not token_file.is_file() or token_file.stat().st_mode & 0o077:
        raise RuntimeServiceError("token file is missing or permissions are unsafe")
    state_root = Path(file_env["OCP_STATE_ROOT"]).expanduser().absolute()
    if state_root.is_symlink() or (state_root.exists() and not state_root.is_dir()):
        raise RuntimeServiceError("OCP state root is unsafe")
    state_root.mkdir(parents=True, exist_ok=True)
    if state_root.is_symlink():
        raise RuntimeServiceError("OCP state root is unsafe")
    work_activation_enabled = work_activation_enabled_from_environment(environment)
    activation_policy_ref = str(environment.get("OCP_WORK_ACTIVATION_POLICY_REF") or "").strip()
    if work_activation_enabled:
        _safe_id(activation_policy_ref, "work activation policy ref")
    full_plan_activation_enabled = full_plan_activation_enabled_from_environment(environment)
    full_plan_activation_policy_ref = str(environment.get("OCP_FULL_PLAN_ACTIVATION_POLICY_REF") or "").strip()
    if full_plan_activation_enabled:
        _safe_id(full_plan_activation_policy_ref, "Full Plan activation policy ref")
    project_onboarding_enabled = project_onboarding_enabled_from_environment(environment)
    project_onboarding_policy_ref = str(environment.get("OCP_PROJECT_ONBOARDING_POLICY_REF") or "").strip()
    if project_onboarding_enabled:
        _safe_id(project_onboarding_policy_ref, "project onboarding policy ref")
    return RuntimeConfig(
        mode, repo_root, repository_id, pr_number, actor_ids, token_file, state_root, environment,
        host_inspection_enabled_from_environment(environment), work_activation_enabled, activation_policy_ref,
        full_plan_activation_enabled, full_plan_activation_policy_ref,
        diagnostic_enabled=diagnostic_enabled, diagnostic_policy=diagnostic_policy,
        project_onboarding_enabled=project_onboarding_enabled,
        project_onboarding_policy_ref=project_onboarding_policy_ref,
    )


def canary_scope_from_environment(mode: ControlMode | str, environment: Mapping[str, str]) -> CanaryScope | None:
    resolved = ControlMode(mode)
    if resolved != ControlMode.CONTROL_MUTATION_CANARY:
        return None
    fields = (
        "OCP_CANARY_PROJECT_ID",
        "OCP_CANARY_RUN_ID",
        "OCP_CANARY_TASK_ID",
        "OCP_CANARY_GATE_ID",
        "OCP_CANARY_DIRECTIVE_ID",
    )
    values = [str(environment.get(key) or "").strip() for key in fields]
    if any(not value for value in values):
        raise RuntimeServiceError("CANARY_SCOPE_REQUIRED")
    project_id, run_id, task_id, gate_id, directive_id = (
        _safe_id(value, key) for value, key in zip(values, fields, strict=True)
    )
    return CanaryScope(project_id, run_id, task_id, gate_id, directive_id)


def _diagnostic_provenance(repo_root: str | Path) -> tuple[str, str]:
    root = Path(repo_root).expanduser().absolute()
    identity = executor_runtime_identity(root)
    source_sha = str(identity.get("head") or "")
    runtime_sha = str(identity.get("runtime_source_sha256") or "")
    if not source_sha:
        manifest_path = root / "RUNTIME_RELEASE_MANIFEST.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise RuntimeServiceError("diagnostic provenance source is unavailable")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_head = str(payload.get("source_head") or "") if isinstance(payload, Mapping) else ""
            manifest = verify_runtime_release(root, expected_head)
        except (OSError, UnicodeError, json.JSONDecodeError, RuntimeReleaseError, ValueError) as exc:
            raise RuntimeServiceError("diagnostic provenance release verification failed") from exc
        source_sha = str(manifest.source_head or "")
    if (
        len(source_sha) not in {40, 64}
        or any(ch not in "0123456789abcdef" for ch in source_sha)
        or len(runtime_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in runtime_sha)
    ):
        raise RuntimeServiceError("diagnostic provenance is incomplete")
    return source_sha, runtime_sha


def execute_authorized_canonical(
    envelope: RemoteControlEnvelope | Any,
    directive: Any,
    *,
    harness_state_root: str | Path,
    executor: Callable[..., Mapping[str, Any]] = execute_registered_full_plan_continuation,
) -> Mapping[str, Any]:
    identity = (
        str(envelope.project_id), str(envelope.run_id), str(envelope.gate_id),
        str(envelope.task_id), str(envelope.task_execution_id),
    )
    directive_identity = (
        str(directive.project_id), str(directive.run_id), str(directive.gate_id),
        str(directive.task_id), str(directive.task_execution_id),
    )
    if identity != directive_identity:
        raise RuntimeServiceError("MUTATION_BINDING_REQUIRED: directive identity mismatch")
    if not bool(directive.state_change_required) or not (
        str(directive.current_stage) == "PREPARE" and str(directive.requested_next_stage) == "ACTION"
    ):
        raise RuntimeServiceError("MUTATION_BINDING_REQUIRED: ACTION directive required")
    message_id = str(getattr(envelope, "message_id", "") or "")
    directive_digest = str(getattr(envelope, "directive_digest", "") or "")
    expected = envelope.expected
    state_sha = str(expected.canonical_run_state_sha256 or "")
    source_head = str(expected.source_head or "")
    runtime_release = str(expected.runtime_release_digest or "")
    try:
        owner_epoch = int(expected.continuation_owner_epoch)
    except (TypeError, ValueError) as exc:
        raise RuntimeServiceError("MUTATION_BINDING_REQUIRED: owner epoch") from exc
    if (
        not message_id
        or len(directive_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in directive_digest)
        or len(state_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in state_sha)
        or owner_epoch <= 0
        or len(source_head) not in {40, 64}
        or any(ch not in "0123456789abcdef" for ch in source_head)
        or len(runtime_release) != 64
        or any(ch not in "0123456789abcdef" for ch in runtime_release)
    ):
        raise RuntimeServiceError("MUTATION_BINDING_REQUIRED")
    return dict(executor(
        harness_state_root=Path(harness_state_root),
        project_id=identity[0],
        run_id=identity[1],
        gate_id=identity[2],
        task_id=identity[3],
        task_execution_id=identity[4],
        expected_state_sha256=state_sha,
        expected_owner_epoch=owner_epoch,
        expected_source_head=source_head,
        expected_runtime_release_digest=runtime_release,
        remote_message_id=message_id,
        remote_directive_digest=directive_digest,
    ))


def _compose_service(config: RuntimeConfig) -> RemoteOperatorService:
    if config.mode == ControlMode.DISABLED:
        raise RuntimeServiceError("disabled mode has no service composition")
    assert config.token_file is not None
    assert config.state_root is not None
    rest_client = GitHubRESTClient(
        repository_id=config.control_repository_id,
        control_pr_number=config.control_pr_number,
        token_file=config.token_file,
    )
    adapter = GitHubControlAdapter(
        config=GitHubControlConfig(
            allowed_repository_id=config.control_repository_id,
            control_pr_number=config.control_pr_number,
            allowed_actor_ids=frozenset(config.allowed_actor_ids),
        ),
        rest_client=rest_client,
        secret_scan=_projection_secret_findings,
        delivery_ack_path=config.state_root / "transport" / "github-delivery-acks.json",
    )
    receipts = RemoteOperatorReceiptStore(config.state_root / "receipts")
    outbox = RemoteResultOutbox(config.state_root / "outbox")
    diagnostic_outbox = (
        RemoteDiagnosticOutbox(config.state_root / "diagnostic-outbox")
        if config.diagnostic_enabled else None
    )
    binding_store = RemoteExecutionBindingStore(config.state_root / "execution-bindings")
    harness_state_root = resolve_harness_state_root(
        project_root=config.repo_root,
        environ=config.environment,
    )
    inspection_port: HostInspectionPort | None = None
    if config.host_inspection_enabled:
        mapping_root_raw = str(config.environment.get("HARNESS_CONTRACT_MAPPING_ROOT") or "").strip()
        if not mapping_root_raw:
            raise RuntimeServiceError("HOST_INSPECTION_REGISTRY_REQUIRED")
        mapping_root = Path(mapping_root_raw).expanduser().absolute()
        if not mapping_root.is_dir() or mapping_root.is_symlink() or mapping_root.resolve() != mapping_root:
            raise RuntimeServiceError("HOST_INSPECTION_REGISTRY_UNSAFE")
        inspection_port = HostInspectionPort(
            registry_root=mapping_root,
            read_scopes=(".",),
            allowed_service_units=frozenset({"ocpv2.service"}),
            attention_search_root=harness_state_root,
        )

    activation_registry: OnboardingRegistry | None = None
    activation_release: RuntimeReleaseManifest | None = None
    activation_store: PlanActivationStore | None = None
    full_plan_authority_root: Path | None = None
    full_plan_activation_store: FullPlanActivationStore | None = None
    onboarding_admission: ProjectOnboardingAdmission | None = None
    if config.work_activation_enabled:
        mapping_root_raw = str(config.environment.get("HARNESS_CONTRACT_MAPPING_ROOT") or "").strip()
        if not mapping_root_raw:
            raise RuntimeServiceError("WORK_ACTIVATION_REGISTRY_REQUIRED")
        mapping_root = Path(mapping_root_raw).expanduser().absolute()
        if not mapping_root.is_dir() or mapping_root.is_symlink() or mapping_root.resolve() != mapping_root:
            raise RuntimeServiceError("WORK_ACTIVATION_REGISTRY_UNSAFE")
        activation_registry = OnboardingRegistry(mapping_root / "aliases")
        activation_release = _runtime_release_for_root(config.repo_root)
        activation_store = PlanActivationStore(harness_state_root)

    if config.full_plan_activation_enabled:
        authority_root_raw = str(config.environment.get("HARNESS_CONTRACT_MAPPING_ROOT") or "").strip()
        if not authority_root_raw:
            raise RuntimeServiceError("FULL_PLAN_ACTIVATION_REGISTRY_REQUIRED")
        full_plan_authority_root = Path(authority_root_raw).expanduser().absolute()
        if (
            not full_plan_authority_root.is_dir()
            or full_plan_authority_root.is_symlink()
            or full_plan_authority_root.resolve() != full_plan_authority_root
        ):
            raise RuntimeServiceError("FULL_PLAN_ACTIVATION_REGISTRY_UNSAFE")
        if activation_release is None:
            activation_release = _runtime_release_for_root(config.repo_root)
        full_plan_activation_store = FullPlanActivationStore(harness_state_root)

    if config.project_onboarding_enabled:
        onboarding_root_raw = str(config.environment.get("HARNESS_CONTRACT_MAPPING_ROOT") or "").strip()
        if not onboarding_root_raw:
            raise RuntimeServiceError("PROJECT_ONBOARDING_REGISTRY_REQUIRED")
        onboarding_root = Path(onboarding_root_raw).expanduser().absolute()
        if (
            not onboarding_root.is_dir()
            or onboarding_root.is_symlink()
            or onboarding_root.resolve() != onboarding_root
        ):
            raise RuntimeServiceError("PROJECT_ONBOARDING_REGISTRY_UNSAFE")
        onboarding_admission = ProjectOnboardingAdmission(
            OnboardingRegistry(onboarding_root / "aliases")
        )

    def durable_acknowledged(message_id: str) -> bool:
        binding = binding_store.get(message_id)
        if binding is None:
            return False
        return adapter.has_durable_ack(
            message_id,
            source_message_id=binding.source_message_id,
            content_sha256=binding.control_content_sha256,
        )

    def publish_pending(projection: RemoteProjectionV1) -> None:
        binding = binding_store.get(projection.message_id)
        if binding is None or binding.projection_id != projection.projection_id:
            raise RuntimeServiceError("RECONCILIATION_REQUIRED: outbox binding mismatch")
        adapter.prepare_recovery_delivery(
            source_message_id=binding.source_message_id,
            message_id=binding.message_id,
            content_sha256=binding.control_content_sha256,
        )
        adapter.publish_projection(projection.to_dict())
        adapter.acknowledge_delivery(projection.message_id)

    recover_pending_canonical_results(
        binding_store=binding_store,
        receipt_store=receipts,
        outbox=outbox,
        evidence_resolver=lambda binding: resolve_registered_full_plan_completion(
            binding,
            harness_state_root=harness_state_root,
        ),
        publisher=publish_pending,
        durable_acknowledged=durable_acknowledged,
    )

    # Read-only inspection and activation projections share the durable outbox with
    # canonical REC-* results, but they intentionally have no mutation execution
    # binding. Recover them through their normal transport lifecycle without invoking
    # canonical prepare_recovery_delivery or any execution callback.
    for projection in tuple(outbox.pending()):
        if isinstance(projection, RemoteResultProjectionV1):
            continue
        adapter.publish_projection(projection.to_dict())
        adapter.acknowledge_delivery(projection.message_id)
        outbox.mark_published(projection.projection_id, projection.projection_sha256)

    if diagnostic_outbox is not None:
        def publish_pending_diagnostic(projection: RemoteDiagnosticProjectionV1) -> None:
            adapter.publish_projection(projection.to_dict())
            adapter.acknowledge_delivery(projection.message_id)
        diagnostic_outbox.publish_pending(publish_pending_diagnostic)

    def decode(raw):
        try:
            value = json.loads(raw.content.decode("utf-8"))
        except Exception as exc:
            raise RuntimeServiceError("remote control payload is not valid JSON") from exc
        if str(value.get("schema_version") or "").startswith("orchestration.remote-operator-envelope."):
            envelope = validate_remote_operator_control_envelope(value)
        else:
            envelope = decode_remote_control_payload(value)
        if (
            envelope.transport.adapter_id != "GITHUB_CONTROL_V1"
            or envelope.transport.channel_id != f"PR:{config.control_pr_number}"
            or envelope.transport.source_actor_id != raw.source_actor_id
            or envelope.transport.source_message_id != raw.source_message_id
            or raw.source_repository_id != config.control_repository_id
        ):
            raise RuntimeServiceError("remote envelope transport binding mismatch")
        return envelope

    def bind_before_receipt(envelope, directive):
        if directive.state_change_required:
            binding_store.record(envelope)

    def ingress(envelope):
        decision = validate_ingress(
            envelope,
            receipt_store=receipts,
            allowed_adapter_id="GITHUB_CONTROL_V1",
            allowed_channel_id=f"PR:{config.control_pr_number}",
            allowed_source_actor_ids=config.allowed_actor_ids,
            expected_risk_envelope_digest=None,
            before_receipt_commit=bind_before_receipt,
        )
        if not decision.accepted and decision.result_class == "IDEMPOTENT_REPLAY":
            binding = binding_store.get(envelope.message_id)
            if binding is not None and binding.status != "PROJECTED":
                raise RuntimeServiceError("RECONCILIATION_REQUIRED: unresolved canonical execution binding")
        return decision

    def execute(envelope, directive):
        return execute_authorized_canonical(
            envelope,
            directive,
            harness_state_root=harness_state_root,
        )

    def execute_read_only(envelope, directive, request):
        if (
            not config.diagnostic_enabled
            or config.diagnostic_policy is None
            or diagnostic_outbox is None
            or not isinstance(envelope, RemoteOperatorEnvelopeV3)
            or request.request_digest != envelope.read_only_request_digest
            or directive.state_change_required
        ):
            raise RuntimeServiceError("READ_ONLY_DIAGNOSTIC_NOT_AUTHORIZED")
        source_sha, runtime_sha = _diagnostic_provenance(config.repo_root)
        result = execute_read_only_host_diagnostic(
            request,
            config.diagnostic_policy,
            project_id=envelope.project_id,
            correlation_id=envelope.message_id,
            source_sha=source_sha,
            runtime_sha=runtime_sha,
        )
        projection = RemoteDiagnosticProjectionV1(
            projection_id=f"DIAG-{envelope.message_id}", message_id=envelope.message_id,
            directive_digest=envelope.directive_digest, project_id=envelope.project_id,
            run_id=envelope.run_id, gate_id=envelope.gate_id, task_id=envelope.task_id,
            request_digest=envelope.read_only_request_digest, diagnostic_result=result,
            projected_at=result.captured_at,
        )
        diagnostic_outbox.enqueue(projection)
        return result.to_dict()

    def inspect(envelope: RemoteControlEnvelopeV1) -> Mapping[str, Any]:
        if inspection_port is None:
            raise RuntimeServiceError("HOST_INSPECTION_DISABLED")
        result = inspection_port.inspect(envelope.payload)
        projection = RemoteInspectionProjectionV1.from_result(result, message_id=envelope.message_id)
        outbox.enqueue_projection(projection)
        return projection.to_dict()

    def activate(envelope: RemoteControlEnvelopeV1) -> Mapping[str, Any]:
        if activation_registry is None or activation_release is None or activation_store is None:
            raise RuntimeServiceError("WORK_ACTIVATION_DISABLED")
        binding = validate_approved_work_binding(
            envelope.payload, registry=activation_registry, runtime_release=activation_release,
        )
        office_store = AIOfficeStateStore(
            harness_state_root, project_id=binding.project_id, run_id=binding.activation_request_id,
        )
        ai_context = coordinate_approved_activation(binding, office_store=office_store)
        receipt = activation_store.record_or_load(
            request_id=binding.activation_request_id, binding=binding,
            registrar=lambda: activate_approved_work(
                binding, ai_context=ai_context, harness_state_root=harness_state_root,
                runtime_code_root=binding.runtime_code_root,
            ),
        )
        projection = RemoteActivationProjectionV1.from_receipt(receipt, message_id=envelope.message_id)
        outbox.enqueue_projection(projection)
        return projection.to_dict()

    def activate_full_plan(envelope: RemoteControlEnvelopeV1) -> Mapping[str, Any]:
        if (
            full_plan_authority_root is None
            or activation_release is None
            or full_plan_activation_store is None
        ):
            raise RuntimeServiceError("FULL_PLAN_ACTIVATION_DISABLED")
        bundle = validate_approved_full_plan_binding(
            envelope.payload,
            authority_root=full_plan_authority_root,
            runtime_release=activation_release,
            harness_state_root=harness_state_root,
        )
        office_store = AIOfficeStateStore(
            harness_state_root, project_id=bundle.project_id, run_id=bundle.activation_request_id,
        )
        ai_context = coordinate_approved_full_plan_activation(bundle, office_store=office_store)
        receipt = full_plan_activation_store.record_or_load(
            request_id=bundle.activation_request_id,
            bundle=bundle,
            registrar=lambda: activate_approved_full_plan(
                bundle, ai_context=ai_context, harness_state_root=harness_state_root,
            ),
        )
        projection = RemoteFullPlanActivationProjectionV1.from_receipt(
            receipt, message_id=envelope.message_id,
        )
        outbox.enqueue_projection(projection)
        return projection.to_dict()

    def onboard(envelope: RemoteControlEnvelopeV1) -> Mapping[str, Any]:
        if onboarding_admission is None:
            raise RuntimeServiceError("PROJECT_ONBOARDING_DISABLED")
        result = onboarding_admission.execute(envelope.payload)
        return {
            "schema_version": "orchestration.remote-project-onboarding-status-projection.v1",
            "message_id": envelope.message_id,
            "alias": envelope.payload.alias,
            "request_digest": envelope.payload.request_digest,
            "mode": envelope.payload.mode,
            "result_class": str(result.get("status") or "PROJECT_ONBOARDING_ERROR"),
            "result": result,
        }

    def after_projection_published(envelope, projection):
        if isinstance(envelope, RemoteControlEnvelopeV1):
            finalize_remote_control_projection(outbox, projection)
            return
        if isinstance(envelope, RemoteOperatorEnvelopeV3) and diagnostic_outbox is not None:
            projection_id = f"DIAG-{envelope.message_id}"
            for pending in diagnostic_outbox.pending():
                if pending.projection_id == projection_id:
                    diagnostic_outbox.mark_published(projection_id, pending.projection_sha256)
                    break
        binding = binding_store.get(envelope.message_id)
        if binding is not None and binding.status != "PROJECTED":
            binding_store.mark_projected(envelope.message_id, binding.projection_id or None)

    return RemoteOperatorService(
        transport=adapter,
        decode_envelope=decode,
        ingress=ingress,
        execute_authorized=execute,
        execute_read_only=execute_read_only if config.diagnostic_enabled else None,
        canary_scope=canary_scope_from_environment(config.mode, config.environment),
        after_projection_published=after_projection_published,
        inspect_authorized=inspect,
        host_inspection_enabled=config.host_inspection_enabled,
        activate_authorized=activate,
        work_activation_enabled=config.work_activation_enabled,
        activation_policy_ref=config.activation_policy_ref,
        activate_full_plan_authorized=activate_full_plan,
        full_plan_activation_enabled=config.full_plan_activation_enabled,
        full_plan_activation_policy_ref=config.full_plan_activation_policy_ref,
        onboard_authorized=onboard,
        project_onboarding_enabled=config.project_onboarding_enabled,
        project_onboarding_policy_ref=config.project_onboarding_policy_ref,
    )


def run_once(config: RuntimeConfig) -> dict[str, Any]:
    if config.mode == ControlMode.DISABLED:
        return {"mode": "DISABLED", "received": 0, "validated": 0, "executed": 0,
                "diagnosed": 0, "projected": 0, "acknowledged": 0, "blocked": 0,
                "inspected": 0, "activated": 0, "full_plan_activated": 0, "onboarded": 0}
    service = _compose_service(config)
    result = service.poll_once(mode=config.mode)
    return {
        "mode": result.mode,
        "received": result.received,
        "validated": result.validated,
        "executed": result.executed,
        "diagnosed": result.diagnosed,
        "projected": result.projected,
        "acknowledged": result.acknowledged,
        "blocked": result.blocked,
        "inspected": result.inspected,
        "activated": result.activated,
        "full_plan_activated": result.full_plan_activated,
        "onboarded": result.onboarded,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one OCPv2 canonical control poll")
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args(argv)
    try:
        config = load_runtime_config(args.env_file)
        result = run_once(config)
    except (RuntimeServiceError, RemoteOperatorServiceError, ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True), file=os.sys.stderr)
        return 2
    print(json.dumps({"status": "OK", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
