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

from runtime.operator_transport.github_control_adapter import GitHubControlAdapter, GitHubControlConfig
from runtime.operator_transport.github_rest_client import PUBLIC_SOURCE_REPOSITORY_ID, GitHubRESTClient
from .harness_state_root import resolve_harness_state_root
from .host_inspection_port import HostInspectionPort
from .ocpv2_canonical_recovery import recover_pending_canonical_results, resolve_registered_full_plan_completion
from .ocpv2_canonical_resume import execute_registered_full_plan_continuation
from .remote_control_envelope import RemoteControlEnvelopeV1, decode_remote_control_payload
from .remote_operator_envelope import RemoteOperatorEnvelopeV2
from .remote_operator_ingress import validate_ingress
from .remote_operator_outbox import (
    RemoteInspectionProjectionV1, RemoteResultOutbox, RemoteResultProjectionV1, parse_remote_projection,
)
from .remote_operator_receipt import RemoteOperatorReceiptStore
from .remote_operator_recovery_binding import RemoteExecutionBindingStore
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
    "HARNESS_CONTRACT_MAPPING_ROOT",
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


def host_inspection_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    """Enable only on the exact explicit value `1`; absent/invalid stays fail-closed."""
    return str(environment.get("OCP_HOST_INSPECTION_ENABLED") or "").strip() == "1"


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
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
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
    repo_root = Path(file_env["OCP_REPO_ROOT"]).expanduser().absolute()
    if repo_root.is_symlink() or not repo_root.is_dir():
        raise RuntimeServiceError("repo root must be an existing non-symlink directory")
    if mode == ControlMode.DISABLED:
        return RuntimeConfig(mode, repo_root, 0, 0, (), None, None, environment, False)
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
    return RuntimeConfig(
        mode, repo_root, repository_id, pr_number, actor_ids, token_file, state_root, environment,
        host_inspection_enabled_from_environment(environment),
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


def execute_authorized_canonical(
    envelope: RemoteOperatorEnvelopeV2 | Any,
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

    def durable_acknowledged(message_id: str) -> bool:
        binding = binding_store.get(message_id)
        if binding is None:
            return False
        return adapter.has_durable_ack(
            message_id,
            source_message_id=binding.source_message_id,
            content_sha256=binding.control_content_sha256,
        )

    def publish_pending(projection: RemoteResultProjectionV1) -> None:
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

    def decode(raw):
        try:
            value = json.loads(raw.content.decode("utf-8"))
        except Exception as exc:
            raise RuntimeServiceError("remote control payload is not valid JSON") from exc
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

    def inspect(envelope: RemoteControlEnvelopeV1) -> Mapping[str, Any]:
        if inspection_port is None:
            raise RuntimeServiceError("HOST_INSPECTION_DISABLED")
        result = inspection_port.inspect(envelope.payload)
        projection = RemoteInspectionProjectionV1.from_result(result, message_id=envelope.message_id)
        outbox.enqueue_projection(projection)
        return projection.to_dict()

    def after_projection_published(envelope, projection):
        if isinstance(envelope, RemoteControlEnvelopeV1):
            parsed = parse_remote_projection(projection)
            if not isinstance(parsed, RemoteInspectionProjectionV1):
                raise RuntimeServiceError("HOST_INSPECTION_PROJECTION_MISMATCH")
            outbox.mark_published(parsed.projection_id, parsed.projection_sha256)
            return
        binding = binding_store.get(envelope.message_id)
        if binding is not None and binding.status != "PROJECTED":
            binding_store.mark_projected(envelope.message_id, binding.projection_id or None)

    return RemoteOperatorService(
        transport=adapter,
        decode_envelope=decode,
        ingress=ingress,
        execute_authorized=execute,
        canary_scope=canary_scope_from_environment(config.mode, config.environment),
        after_projection_published=after_projection_published,
        inspect_authorized=inspect,
        host_inspection_enabled=config.host_inspection_enabled,
    )


def run_once(config: RuntimeConfig) -> dict[str, Any]:
    if config.mode == ControlMode.DISABLED:
        return {"mode": "DISABLED", "received": 0, "validated": 0, "executed": 0,
                "projected": 0, "acknowledged": 0, "blocked": 0, "inspected": 0}
    service = _compose_service(config)
    result = service.poll_once(mode=config.mode)
    return {
        "mode": result.mode,
        "received": result.received,
        "validated": result.validated,
        "executed": result.executed,
        "projected": result.projected,
        "acknowledged": result.acknowledged,
        "blocked": result.blocked,
        "inspected": result.inspected,
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
