"""Isolated one-shot OCP runner for typed production-control actions.

This module is intentionally not enabled by any timer or unit. It accepts exactly one
request kind, requires ACTIVE mode, requires the source checkout to differ from the
serving root, and rejects every unrelated OCP capability.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from . import ocpv2_runtime_service as base
from .harness_state_root import resolve_harness_state_root
from .production_control_action import (
    CanonicalProductionControlBackend,
    ProductionControlActionExecutor,
    ProductionControlServerConfig,
)
from .remote_control_envelope import PRODUCTION_CONTROL_ACTION_KIND
from .remote_operator_service import ControlMode, RemoteOperatorServiceError

_ENV_KEYS = {
    "OCP_PRODUCTION_CONTROL_ENABLED",
    "OCP_PRODUCTION_CONTROL_POLICY_REF",
}
_POLICY_REF = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")

# Parser visibility does not enable the capability. The dedicated runner validates
# exact-one capability semantics below.
base._OPTIONAL_ENV.update(_ENV_KEYS)


class ProductionControlRuntimeError(ValueError):
    pass


def production_control_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    return str(environment.get("OCP_PRODUCTION_CONTROL_ENABLED") or "").strip() == "1"


def _policy_ref(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_PRODUCTION_CONTROL_POLICY_REF") or "").strip()
    if not _POLICY_REF.fullmatch(value):
        raise ProductionControlRuntimeError("PRODUCTION_CONTROL_POLICY_REF_INVALID")
    return value


def _forbidden_capability_enabled(environment: Mapping[str, str]) -> bool:
    forbidden = (
        "OCP_HOST_INSPECTION_ENABLED",
        "OCP_WORK_ACTIVATION_ENABLED",
        "OCP_FULL_PLAN_ACTIVATION_ENABLED",
        "OCP_GATE_APPROVAL_ISSUE_ENABLED",
        "OCP_PROJECT_ONBOARDING_ENABLED",
        "OCP_SUCCESSOR_RELEASE_STAGE_ENABLED",
        "OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED",
        "OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_ENABLED",
        "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_ENABLED",
        "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_ENABLED",
    )
    return any(str(environment.get(key) or "").strip() == "1" for key in forbidden)


def _validate_config(config: base.RuntimeConfig) -> None:
    source = Path.cwd().resolve()
    serving = config.repo_root.resolve()
    if source == serving:
        raise ProductionControlRuntimeError("PRODUCTION_CONTROL_SOURCE_MUST_BE_SEPARATE_FROM_SERVING_ROOT")
    if config.mode != ControlMode.ACTIVE:
        raise ProductionControlRuntimeError("PRODUCTION_CONTROL_ACTIVE_MODE_REQUIRED")
    if not production_control_enabled_from_environment(config.environment):
        raise ProductionControlRuntimeError("PRODUCTION_CONTROL_GATE_REQUIRED")
    _policy_ref(config.environment)
    if _forbidden_capability_enabled(config.environment):
        raise ProductionControlRuntimeError("PRODUCTION_CONTROL_UNRELATED_CAPABILITY_FORBIDDEN")


def _server_config(config: base.RuntimeConfig) -> ProductionControlServerConfig:
    source = Path.cwd().resolve()
    manifest = source / "RUNTIME_RELEASE_MANIFEST.json"
    if source.is_symlink() or not source.is_dir() or not manifest.is_file():
        raise ProductionControlRuntimeError("PRODUCTION_CONTROL_IMMUTABLE_RUNTIME_REQUIRED")
    releases_root = source.parent
    state_root = resolve_harness_state_root(
        project_root=config.repo_root,
        environ=config.environment,
    )
    home = Path.home()
    return ProductionControlServerConfig(
        harness_state_root=state_root,
        releases_root=releases_root,
        runtime_link=home / ".local/share/global-gpt-harness/runtime-current",
        runtime_compatibility_manifest=home / ".config/gch/operational-runtime-compatibility.json",
        operational_identity_files=(
            home / ".config/systemd/user/global-gpt-harness-operational-acceptance.service",
            home / ".config/systemd/user/global-gpt-harness-ai-office-dashboard-publisher.service",
            home / ".config/systemd/user/global-gpt-harness-attention-delivery.service",
        ),
        job_search_root=state_root,
    )


def compose_service(config: base.RuntimeConfig):
    _validate_config(config)
    service = base._compose_service(config)
    policy_ref = _policy_ref(config.environment)
    backend = CanonicalProductionControlBackend(_server_config(config))
    executor = ProductionControlActionExecutor(
        harness_state_root=backend.config.harness_state_root,
        backend=backend,
    )

    def execute_action(envelope) -> Mapping[str, Any]:
        request = envelope.payload
        if request.approval_ref != policy_ref:
            raise ProductionControlRuntimeError("PRODUCTION_CONTROL_POLICY_MISMATCH")
        result = executor.execute(request)
        return result.to_dict()

    service.execute_production_control_authorized = execute_action
    service.production_control_enabled = True
    service.production_control_policy_ref = policy_ref
    return service


class _ProductionControlFilteredTransport:
    def __init__(self, transport) -> None:
        self._transport = transport

    def receive(self, *, limit: int = 16):
        receiver = getattr(self._transport, "receive_request_kind", None)
        if not callable(receiver):
            raise ProductionControlRuntimeError("PRODUCTION_CONTROL_TRANSPORT_FILTER_REQUIRED")
        return receiver(PRODUCTION_CONTROL_ACTION_KIND, limit=limit)

    def acknowledge_delivery(self, message_id: str) -> None:
        self._transport.acknowledge_delivery(message_id)

    def publish_projection(self, projection: Mapping[str, Any]) -> None:
        self._transport.publish_projection(projection)


def run_once(config: base.RuntimeConfig) -> dict[str, Any]:
    service = compose_service(config)
    service.transport = _ProductionControlFilteredTransport(service.transport)
    result = service.poll_once(mode=config.mode)
    return {
        "mode": result.mode,
        "received": result.received,
        "validated": result.validated,
        "projected": result.projected,
        "acknowledged": result.acknowledged,
        "blocked": result.blocked,
        "production_control_actions": result.production_control_actions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one isolated OCP production-control poll"
    )
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args(argv)
    try:
        config = base.load_runtime_config(args.env_file)
        result = run_once(config)
    except (
        base.RuntimeServiceError,
        ProductionControlRuntimeError,
        RemoteOperatorServiceError,
        ValueError,
        OSError,
    ) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True), file=os.sys.stderr)
        return 2
    print(json.dumps({"status": "OK", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
