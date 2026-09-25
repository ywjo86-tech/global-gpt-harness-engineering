"""Additive production composition for the P2 successor-stage capability.

The legacy OCP runtime remains the implementation of transport, recovery, Full Plan,
and all pre-existing request kinds.  This module adds only the separately gated
SUCCESSOR_RELEASE_STAGE callback and then delegates the normal one-shot service loop.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

from . import ocpv2_runtime_service as base
from .project_onboarding import OnboardingRegistry
from .remote_operator_service import ControlMode, RemoteOperatorServiceError
from .successor_release_stage_gateway import (
    SuccessorReleaseStageGatewayRequest,
    dispatch_successor_release_stage,
)
from .successor_release_staging import (
    SuccessorLifecycleIdentity,
    SuccessorReleaseReceiptStore,
    SuccessorReleaseStager,
)

_STAGE_ENV_KEYS = {
    "OCP_SUCCESSOR_RELEASE_STAGE_ENABLED",
    "OCP_SUCCESSOR_RELEASE_STAGE_POLICY_REF",
}

# The wrapper owns these two additive keys.  Extending the legacy parser allow-list
# does not enable the capability; the feature still defaults fail-closed below.
base._OPTIONAL_ENV.update(_STAGE_ENV_KEYS)


class SuccessorStageRuntimeError(ValueError):
    pass


def successor_release_stage_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    return str(environment.get("OCP_SUCCESSOR_RELEASE_STAGE_ENABLED") or "").strip() == "1"


def _safe_policy_ref(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_SUCCESSOR_RELEASE_STAGE_POLICY_REF") or "").strip()
    if not value:
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_POLICY_REQUIRED")
    base._safe_id(value, "successor release stage policy ref")
    return value


def _mapping_root(config: base.RuntimeConfig) -> Path:
    raw = str(config.environment.get("HARNESS_CONTRACT_MAPPING_ROOT") or "").strip()
    if not raw:
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_REGISTRY_REQUIRED")
    root = Path(raw).expanduser().absolute()
    if not root.is_dir() or root.is_symlink() or root.resolve() != root:
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_REGISTRY_UNSAFE")
    aliases = root / "aliases"
    if not aliases.is_dir() or aliases.is_symlink() or aliases.resolve() != aliases:
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_ALIAS_REGISTRY_UNSAFE")
    return root


def _load_stage_callback(repo_root: Path):
    path = repo_root / "deploy" / "operator-control-plane-v2" / "bootstrap.py"
    if path.is_symlink() or not path.is_file():
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_BOOTSTRAP_UNAVAILABLE")
    spec = importlib.util.spec_from_file_location("_ocpv2_successor_stage_bootstrap", path)
    if spec is None or spec.loader is None:
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_BOOTSTRAP_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    callback = getattr(module, "stage_successor_artifacts", None)
    if not callable(callback):
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_CALLBACK_UNAVAILABLE")
    return callback


class _ReadOnlySuccessorServiceStateProbe:
    """Fixed-name read-only systemd observation; exposes no mutation operation."""

    _PROFILE = "lifecycle-v2-p2"

    @staticmethod
    def _query(*args: str) -> bool:
        completed = subprocess.run(
            ["systemctl", "--user", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            text=True,
        )
        return completed.returncode == 0

    def observe(self, profile: str) -> dict[str, bool]:
        if str(profile) != self._PROFILE:
            raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_PROFILE_INVALID")
        service = f"ocpv2-{self._PROFILE}.service"
        timer = f"ocpv2-{self._PROFILE}.timer"
        service_active = self._query("is-active", "--quiet", service)
        service_enabled = self._query("is-enabled", "--quiet", service)
        timer_active = self._query("is-active", "--quiet", timer)
        timer_enabled = self._query("is-enabled", "--quiet", timer)
        return {
            "service_active": service_active,
            "service_enabled": service_enabled,
            "timer_active": timer_active,
            "timer_enabled": timer_enabled,
            "polling_enabled": timer_active or timer_enabled,
        }


def _successor_stager(config: base.RuntimeConfig) -> SuccessorReleaseStager:
    assert config.state_root is not None
    mapping_root = _mapping_root(config)
    serving_root = config.repo_root.resolve(strict=True)
    config_root = (Path.home() / ".config" / "gch").absolute()
    unit_root = (Path.home() / ".config" / "systemd" / "user").absolute()
    return SuccessorReleaseStager(
        OnboardingRegistry(mapping_root / "aliases"),
        lifecycle_identity_provider=lambda: SuccessorLifecycleIdentity(
            serving_root=serving_root,
            predecessor_root=None,
        ),
        receipt_store=SuccessorReleaseReceiptStore(
            config.state_root / "successor-release-stage-receipts"
        ),
        lock_root=config.state_root / "successor-release-stage-locks",
        stage_artifacts=_load_stage_callback(config.repo_root),
        service_state_probe=_ReadOnlySuccessorServiceStateProbe(),
        user_config_root=config_root,
        user_unit_root=unit_root,
    )


def compose_service(config: base.RuntimeConfig):
    service = base._compose_service(config)
    enabled = successor_release_stage_enabled_from_environment(config.environment)
    if not enabled:
        return service
    policy_ref = _safe_policy_ref(config.environment)
    stager = _successor_stager(config)

    def stage_successor(envelope) -> Mapping[str, Any]:
        gateway_request = SuccessorReleaseStageGatewayRequest.from_stage_request(envelope.payload)
        result = dispatch_successor_release_stage(gateway_request, stager=stager)
        return {
            "schema_version": "orchestration.remote-successor-release-stage-status-projection.v1",
            "message_id": envelope.message_id,
            "request_id": envelope.payload.request_id,
            "project_alias": envelope.payload.project_alias,
            "phase_request_digest": envelope.payload.phase_request_digest,
            "mode": envelope.payload.mode,
            "result_class": str(result.get("status") or result.get("outcome") or "SUCCESSOR_RELEASE_STAGE_ERROR"),
            "result": result,
        }

    service.stage_successor_authorized = stage_successor
    service.successor_release_stage_enabled = True
    service.successor_release_stage_policy_ref = policy_ref
    return service


def run_once(config: base.RuntimeConfig) -> dict[str, Any]:
    if config.mode == ControlMode.DISABLED:
        result = base.run_once(config)
        result["successor_release_staged"] = 0
        return result
    service = compose_service(config)
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
        "successor_release_staged": result.successor_release_staged,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one OCPv2 poll with bounded successor staging")
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args(argv)
    try:
        config = base.load_runtime_config(args.env_file)
        result = run_once(config)
    except (base.RuntimeServiceError, SuccessorStageRuntimeError, RemoteOperatorServiceError, ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True), file=os.sys.stderr)
        return 2
    print(json.dumps({"status": "OK", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
