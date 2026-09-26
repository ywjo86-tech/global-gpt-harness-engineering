"""Additive production composition for successor staging and Lifecycle V2 P3.

The legacy OCP runtime remains the implementation of transport, recovery, Full Plan,
and all pre-existing request kinds. This module adds separately gated successor staging,
P3 Promotion Admission, and bounded P3 Canary Activation callbacks, then delegates the
normal one-shot service loop. P3 canary activation may register only the single fresh
candidate already admitted by P3 admission; runtime-current switching, migration,
predecessor shutdown, generic mutation, and new effect backends remain unauthorized.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import ocpv2_runtime_service as base
from .approved_full_plan_activation_contract import ApprovedFullPlanActivationRequestV1
from .harness_state_root import resolve_harness_state_root
from .lifecycle_v2_p3_canary_activation import evaluate_p3_canary_activation
from .lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionEvidence,
    evaluate_p3_promotion_admission,
)
from .project_onboarding import OnboardingRegistry
from .remote_control_envelope import APPROVED_FULL_PLAN_ACTIVATION_KIND
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
_P3_ENV_KEYS = {
    "OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED",
    "OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_REF",
    "OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_DIGEST",
}
_P3_CANARY_ENV_KEYS = {
    "OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_ENABLED",
    "OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_POLICY_REF",
    "OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_POLICY_DIGEST",
}
_POLICY_REF = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

# Extending the legacy parser allow-list never enables any capability. Every
# feature remains independently default-disabled below.
base._OPTIONAL_ENV.update(_STAGE_ENV_KEYS | _P3_ENV_KEYS | _P3_CANARY_ENV_KEYS)


class SuccessorStageRuntimeError(ValueError):
    pass


def successor_release_stage_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    return str(environment.get("OCP_SUCCESSOR_RELEASE_STAGE_ENABLED") or "").strip() == "1"


def lifecycle_v2_p3_promotion_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    return str(environment.get("OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED") or "").strip() == "1"


def lifecycle_v2_p3_canary_activation_enabled_from_environment(
    environment: Mapping[str, str],
) -> bool:
    return str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_ENABLED") or "").strip() == "1"


def _safe_policy_ref(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_SUCCESSOR_RELEASE_STAGE_POLICY_REF") or "").strip()
    if not value or ".." in value or not _POLICY_REF.fullmatch(value):
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_POLICY_REQUIRED")
    return value


def _safe_p3_policy_ref(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_REF") or "").strip()
    if not value or ".." in value or not _POLICY_REF.fullmatch(value):
        raise SuccessorStageRuntimeError("P3_PROMOTION_POLICY_REQUIRED")
    return value


def _safe_p3_policy_digest(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_DIGEST") or "").strip()
    if not _SHA256.fullmatch(value):
        raise SuccessorStageRuntimeError("P3_PROMOTION_POLICY_DIGEST_REQUIRED")
    return value


def _safe_p3_canary_policy_ref(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_POLICY_REF") or "").strip()
    if not value or ".." in value or not _POLICY_REF.fullmatch(value):
        raise SuccessorStageRuntimeError("P3_CANARY_ACTIVATION_POLICY_REQUIRED")
    return value


def _safe_p3_canary_policy_digest(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_POLICY_DIGEST") or "").strip()
    if not _SHA256.fullmatch(value):
        raise SuccessorStageRuntimeError("P3_CANARY_ACTIVATION_POLICY_DIGEST_REQUIRED")
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
    module_name = "_ocpv2_successor_stage_bootstrap"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_BOOTSTRAP_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
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


class _ReadOnlyPredecessorServiceStateProbe:
    """Observe only the fixed serving OCP units; never invokes a service mutation."""

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

    def serving(self) -> bool:
        service_active = self._query("is-active", "--quiet", "ocpv2.service")
        timer_active = self._query("is-active", "--quiet", "ocpv2.timer")
        timer_enabled = self._query("is-enabled", "--quiet", "ocpv2.timer")
        return service_active or (timer_active and timer_enabled)


@dataclass(frozen=True, slots=True)
class _P3FullPlanDelegation:
    """Internal delegation only; never serialized or accepted as remote authority."""

    message_id: str
    request_kind: str
    payload: ApprovedFullPlanActivationRequestV1


def _successor_stager(config: base.RuntimeConfig) -> SuccessorReleaseStager:
    if config.state_root is None:
        raise SuccessorStageRuntimeError("SUCCESSOR_RELEASE_STAGE_STATE_ROOT_REQUIRED")
    mapping_root = _mapping_root(config)
    serving_root = config.repo_root.resolve(strict=True)
    config_root = (Path.home() / ".config" / "gch").absolute()
    unit_root = (Path.home() / ".config" / "systemd" / "user").absolute()
    return SuccessorReleaseStager(
        OnboardingRegistry(mapping_root / "aliases"),
        lifecycle_identity_provider=lambda: SuccessorLifecycleIdentity(
            serving_root=serving_root,
            predecessor_root=serving_root,
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


def _readonly_git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            text=True,
        )
    except OSError as exc:
        raise SuccessorStageRuntimeError("P3_PROMOTION_GIT_EVIDENCE_UNAVAILABLE") from exc
    if completed.returncode != 0 or not completed.stdout.strip():
        raise SuccessorStageRuntimeError("P3_PROMOTION_GIT_EVIDENCE_UNAVAILABLE")
    return completed.stdout.strip()


def _file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise SuccessorStageRuntimeError("P3_PROMOTION_SERVING_ARTIFACT_UNAVAILABLE")
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SuccessorStageRuntimeError("P3_PROMOTION_SERVING_ARTIFACT_UNAVAILABLE") from exc


def _matching_staged_receipt(config: base.RuntimeConfig, request) -> Mapping[str, Any]:
    if config.state_root is None:
        raise SuccessorStageRuntimeError("P3_PROMOTION_STATE_ROOT_REQUIRED")
    root = config.state_root / "successor-release-stage-receipts"
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise SuccessorStageRuntimeError("P3_PROMOTION_STAGE_EVIDENCE_UNAVAILABLE")
    matches: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        if (
            value.get("status") == "STAGED"
            and value.get("project_alias") == request.project_alias
            and value.get("post_head") == request.expected_head
            and value.get("guard_outcomes", {}).get("serving_preservation") == "PASS"
            and value.get("guard_outcomes", {}).get("successor_inert") == "PASS"
        ):
            matches.append(value)
    if len(matches) != 1:
        raise SuccessorStageRuntimeError("P3_PROMOTION_STAGE_EVIDENCE_AMBIGUOUS")
    return matches[0]


def _serving_preservation_is_current(receipt: Mapping[str, Any]) -> bool:
    identity = receipt.get("serving_runtime_identity_after")
    if not isinstance(identity, Mapping):
        return False
    serving_root = str(identity.get("serving_root") or "")
    predecessor_root = str(identity.get("predecessor_root") or "")
    if not serving_root or serving_root != predecessor_root:
        return False
    expected = receipt.get("serving_artifact_hashes_after")
    if not isinstance(expected, Mapping):
        return False
    config_root = (Path.home() / ".config" / "gch").absolute()
    unit_root = (Path.home() / ".config" / "systemd" / "user").absolute()
    current = {
        "env": _file_sha256(config_root / "ocpv2.env"),
        "service": _file_sha256(unit_root / "ocpv2.service"),
        "timer": _file_sha256(unit_root / "ocpv2.timer"),
    }
    return current == {key: str(expected.get(key) or "") for key in ("env", "service", "timer")}


def _collect_p3_promotion_evidence(config: base.RuntimeConfig, request) -> LifecycleV2P3PromotionAdmissionEvidence:
    mapping_root = _mapping_root(config)
    entries = [
        item
        for item in OnboardingRegistry(mapping_root / "aliases").entries()
        if item.get("alias") == request.project_alias
    ]
    if len(entries) != 1:
        raise SuccessorStageRuntimeError("P3_PROMOTION_ALIAS_EVIDENCE_UNAVAILABLE")
    entry = entries[0]
    workspace = Path(str(entry["project_root"])).resolve(strict=True)
    observed_branch = _readonly_git(workspace, "symbolic-ref", "--short", "HEAD")
    observed_head = _readonly_git(workspace, "rev-parse", "HEAD")

    harness_state = resolve_harness_state_root(
        project_root=workspace,
        environ=config.environment,
    )
    if harness_state.is_symlink() or not harness_state.is_dir() or harness_state.resolve() != harness_state:
        raise SuccessorStageRuntimeError("P3_PROMOTION_HARNESS_STATE_UNAVAILABLE")
    candidate_path = (
        harness_state
        / "_workspace"
        / "production-full-plan-jobs"
        / str(entry["project_id"])
        / f"{request.candidate_run_id}.job.json"
    )
    candidate_prev = candidate_path.with_suffix(candidate_path.suffix + ".prev")
    candidate_state = (
        "REGISTERED"
        if candidate_path.exists()
        or candidate_path.is_symlink()
        or candidate_prev.exists()
        or candidate_prev.is_symlink()
        else "ABSENT"
    )

    receipt = _matching_staged_receipt(config, request)
    predecessor_serving = _ReadOnlyPredecessorServiceStateProbe().serving()
    runtime_current_points_to_predecessor = _serving_preservation_is_current(receipt)

    return LifecycleV2P3PromotionAdmissionEvidence.from_mapping(
        {
            "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-evidence.v1",
            "project_alias": request.project_alias,
            "observed_branch": observed_branch,
            "observed_head": observed_head,
            "observed_successor_profile": "lifecycle-v2-p2",
            "candidate_run_id": request.candidate_run_id,
            "candidate_run_registration_state": candidate_state,
            "predecessor_serving": predecessor_serving,
            "runtime_current_points_to_predecessor": runtime_current_points_to_predecessor,
            "approved_policy_ref": _safe_p3_policy_ref(config.environment),
            "approved_policy_digest": _safe_p3_policy_digest(config.environment),
        }
    )


def _wire_p3_promotion(config: base.RuntimeConfig, service):
    if not lifecycle_v2_p3_promotion_enabled_from_environment(config.environment):
        return service
    policy_ref = _safe_p3_policy_ref(config.environment)
    _safe_p3_policy_digest(config.environment)

    def admit_p3(envelope) -> Mapping[str, Any]:
        evidence = _collect_p3_promotion_evidence(config, envelope.payload)
        result = evaluate_p3_promotion_admission(envelope.payload, evidence)
        return {
            "schema_version": "orchestration.remote-p3-promotion-admission-status-projection.v1",
            "message_id": envelope.message_id,
            "request_id": envelope.payload.request_id,
            "project_alias": envelope.payload.project_alias,
            "request_digest": envelope.payload.request_digest,
            "evidence_digest": evidence.evidence_digest,
            "mode": envelope.payload.mode,
            "result_class": result.status,
            "result": result.to_dict(),
        }

    service.admit_p3_promotion_authorized = admit_p3
    service.lifecycle_v2_p3_promotion_enabled = True
    service.lifecycle_v2_p3_promotion_policy_ref = policy_ref
    return service


def _wire_p3_canary_activation(config: base.RuntimeConfig, service):
    if not lifecycle_v2_p3_canary_activation_enabled_from_environment(config.environment):
        return service
    policy_ref = _safe_p3_canary_policy_ref(config.environment)
    policy_digest = _safe_p3_canary_policy_digest(config.environment)
    canonical_full_plan = getattr(service, "activate_full_plan_authorized", None)
    if canonical_full_plan is None:
        raise SuccessorStageRuntimeError("P3_CANARY_ACTIVATION_CALLBACK_UNAVAILABLE")

    def activate_p3_canary(envelope) -> Mapping[str, Any]:
        request = envelope.payload
        admission_request = request.admission_request
        if (
            admission_request.approval_policy_ref != policy_ref
            or admission_request.approval_policy_digest != policy_digest
        ):
            raise SuccessorStageRuntimeError("P3_CANARY_ACTIVATION_POLICY_MISMATCH")
        evidence = _collect_p3_promotion_evidence(config, admission_request)
        admission = evaluate_p3_promotion_admission(admission_request, evidence)
        authorization = evaluate_p3_canary_activation(request, admission)
        delegated = _P3FullPlanDelegation(
            message_id=envelope.message_id,
            request_kind=APPROVED_FULL_PLAN_ACTIVATION_KIND,
            payload=request.full_plan_activation,
        )
        result = canonical_full_plan(delegated)
        if not isinstance(result, Mapping):
            raise SuccessorStageRuntimeError("P3_CANARY_ACTIVATION_FULL_PLAN_RESULT_INVALID")
        if (
            str(result.get("activation_request_id") or "") != admission_request.candidate_run_id
            or str(result.get("run_id") or "") != admission_request.candidate_run_id
            or str(result.get("result_status") or "") != "FULL_PLAN_REGISTERED"
        ):
            raise SuccessorStageRuntimeError("P3_CANARY_ACTIVATION_FULL_PLAN_RESULT_INVALID")
        return {
            "schema_version": "orchestration.remote-p3-canary-activation-status-projection.v1",
            "message_id": envelope.message_id,
            "request_id": request.request_id,
            "project_alias": admission_request.project_alias,
            "request_digest": request.request_digest,
            "candidate_run_id": admission_request.candidate_run_id,
            "result_class": "P3_CANARY_ACTIVATED",
            "full_plan_result_status": str(result["result_status"]),
            "full_plan_activation_digest": str(result.get("activation_digest") or ""),
            "authorization": authorization.to_dict(),
        }

    service.activate_p3_canary_authorized = activate_p3_canary
    service.lifecycle_v2_p3_canary_activation_enabled = True
    service.lifecycle_v2_p3_canary_activation_policy_ref = policy_ref
    return service


def compose_service(config: base.RuntimeConfig):
    service = base._compose_service(config)
    service = _wire_p3_promotion(config, service)
    service = _wire_p3_canary_activation(config, service)

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
        result["p3_promotion_admitted"] = 0
        result["p3_canary_activated"] = 0
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
        "p3_promotion_admitted": result.p3_promotion_admitted,
        "p3_canary_activated": result.p3_canary_activated,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one OCPv2 poll with bounded successor staging/Lifecycle V2 P3")
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
