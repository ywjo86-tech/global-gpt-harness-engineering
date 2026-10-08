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
from .full_plan_activation import FullPlanActivationReceiptV1
from .lifecycle_v2_p3_canary_activation import evaluate_p3_canary_activation
from .lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionEvidence,
    evaluate_p3_promotion_admission,
)
from .p3_canary_validate_evidence import (
    P3CanaryValidateEvidenceError,
    issue_p3_canary_validate_evidence,
)
from .p3_canary_validate_registration import P3CanaryValidateRegistrationError, register_p3_canary_validate
from .project_onboarding import OnboardingRegistry, ProjectOnboardingError
from .remote_control_envelope import (
    APPROVED_FULL_PLAN_ACTIVATION_KIND,
    LIFECYCLE_V2_P3_CANARY_ACTIVATION_KIND,
    LIFECYCLE_V2_P3_PROMOTION_ADMISSION_KIND,
    LIFECYCLE_V2_P3_CANARY_VALIDATE_REGISTRATION_KIND,
    LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_KIND,
    SUCCESSOR_RELEASE_STAGE_KIND,
)
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
_P3_VALIDATE_ENV_KEYS = {
    "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_ENABLED",
    "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_POLICY_REF",
    "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_POLICY_DIGEST",
}
_P3_VALIDATE_EVIDENCE_ENV_KEYS = {
    "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_ENABLED",
    "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_POLICY_REF",
    "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_POLICY_DIGEST",
}
_POLICY_REF = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_P3_HANDOFF_SCHEMA = "orchestration.lifecycle-v2-p3-handoff.v1"
_P3_HANDOFF_WAITING = "WAITING_FOR_AUTHORIZED_ACTIVATION"

_P3_TERMINAL_HANDOFF_SCHEMA = "orchestration.lifecycle-v2-p3-handoff-terminal.v1"
_P3_TERMINAL_STATE = "P3_CANARY_ACTIVATED"
_P3_TERMINAL_COMPLETION_MODES = {
    "NEW_ACTIVATION",
    "RECOVERED_EXISTING_ACTIVATION",
}
_P3_TERMINAL_RESULT_STATUSES = {
    "FULL_PLAN_REGISTERED",
    "FULL_PLAN_ALREADY_REGISTERED",
}

# Extending the legacy parser allow-list never enables any capability. Every
# feature remains independently default-disabled below.
base._OPTIONAL_ENV.update(_STAGE_ENV_KEYS | _P3_ENV_KEYS | _P3_CANARY_ENV_KEYS | _P3_VALIDATE_ENV_KEYS | _P3_VALIDATE_EVIDENCE_ENV_KEYS)


class SuccessorStageRuntimeError(ValueError):
    pass


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _seal_p3_waiting_handoff(config: base.RuntimeConfig, request, evidence, result) -> dict[str, Any]:
    if config.state_root is None:
        raise SuccessorStageRuntimeError("P3_PROMOTION_STATE_ROOT_REQUIRED")
    root = Path(config.state_root) / "p3-lifecycle-handoffs"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SuccessorStageRuntimeError("P3_HANDOFF_STATE_UNAVAILABLE") from exc
    if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root:
        raise SuccessorStageRuntimeError("P3_HANDOFF_STATE_UNSAFE")

    admission_digest = str(result.admission_digest or "")
    if not _SHA256.fullmatch(admission_digest):
        raise SuccessorStageRuntimeError("P3_HANDOFF_ADMISSION_DIGEST_INVALID")
    handoff = {
        "schema_version": _P3_HANDOFF_SCHEMA,
        "state": _P3_HANDOFF_WAITING,
        "last_completed_step": "P3_PROMOTION_ADMISSION",
        "next_required_request_kind": LIFECYCLE_V2_P3_CANARY_ACTIVATION_KIND,
        "project_alias": str(result.project_alias),
        "candidate_run_id": str(result.canary_run_id),
        "admission_request_id": str(result.request_id),
        "admission_request_digest": str(request.request_digest),
        "admission_evidence_digest": str(evidence.evidence_digest),
        "admission_digest": admission_digest,
        "authorization_required": True,
    }
    payload = _canonical_json_bytes(handoff)
    path = root / f"{admission_digest}.waiting.json"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise SuccessorStageRuntimeError("P3_HANDOFF_STATE_UNSAFE")
        try:
            existing_raw = path.read_bytes()
            existing = json.loads(existing_raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SuccessorStageRuntimeError("P3_HANDOFF_STATE_UNREADABLE") from exc
        if existing_raw != _canonical_json_bytes(existing) or existing != handoff:
            raise SuccessorStageRuntimeError("P3_HANDOFF_ALREADY_SEALED")
        return handoff

    try:
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
    except FileExistsError:
        raise SuccessorStageRuntimeError("P3_HANDOFF_ALREADY_SEALED")
    except OSError as exc:
        raise SuccessorStageRuntimeError("P3_HANDOFF_STATE_UNAVAILABLE") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        finally:
            raise
    return handoff




def _recover_p3_registered_canary(
    *,
    waiting_handoff: Mapping[str, Any] | None,
    request_digest: str,
    bundle_digest: str,
    receipt: Mapping[str, Any],
    canonical_job: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Verify an already-registered P3 candidate without mutation replay."""
    if not isinstance(waiting_handoff, Mapping):
        raise SuccessorStageRuntimeError(
            "P3_CANARY_RECOVERY_HANDOFF_REQUIRED"
        )

    candidate = str(waiting_handoff.get("candidate_run_id") or "")
    if not candidate:
        raise SuccessorStageRuntimeError(
            "P3_CANARY_RECOVERY_HANDOFF_REQUIRED"
        )

    try:
        validated = FullPlanActivationReceiptV1.from_mapping(receipt)
    except Exception as exc:
        raise SuccessorStageRuntimeError(
            "P3_CANARY_RECOVERY_RECEIPT_INVALID"
        ) from exc

    if (
        validated.activation_request_id != candidate
        or validated.run_id != candidate
    ):
        raise SuccessorStageRuntimeError(
            "P3_CANARY_RECOVERY_BINDING_MISMATCH"
        )

    if (
        validated.bundle_digest != bundle_digest
        or validated.executable_authority_bundle_digest != bundle_digest
    ):
        raise SuccessorStageRuntimeError(
            "P3_CANARY_RECOVERY_BINDING_MISMATCH"
        )

    if not isinstance(canonical_job, Mapping):
        raise SuccessorStageRuntimeError(
            "P3_CANARY_RECOVERY_JOB_AUTHORITY_MISMATCH"
        )

    if str(canonical_job.get("run_id") or "") != candidate:
        raise SuccessorStageRuntimeError(
            "P3_CANARY_RECOVERY_JOB_AUTHORITY_MISMATCH"
        )

    if (
        str(canonical_job.get("activation_binding_digest") or "")
        != request_digest
        or str(
            canonical_job.get(
                "executable_authority_bundle_digest"
            ) or ""
        )
        != bundle_digest
    ):
        raise SuccessorStageRuntimeError(
            "P3_CANARY_RECOVERY_BINDING_MISMATCH"
        )

    job_authority = str(
        canonical_job.get("authority_core_sha256") or ""
    )
    if (
        not job_authority
        or job_authority != validated.authority_digest
    ):
        raise SuccessorStageRuntimeError(
            "P3_CANARY_RECOVERY_JOB_AUTHORITY_MISMATCH"
        )

    return {
        "activation_request_id": validated.activation_request_id,
        "run_id": validated.run_id,
        "result_status": "FULL_PLAN_ALREADY_REGISTERED",
        "activation_digest": validated.activation_digest,
        "canonical_job_path": validated.canonical_job_path,
        "request_digest": request_digest,
        "bundle_digest": validated.bundle_digest,
        "executable_authority_bundle_digest":
            validated.executable_authority_bundle_digest,
    }


def _seal_p3_terminal_handoff(
    config: base.RuntimeConfig,
    terminal: Mapping[str, Any],
) -> Mapping[str, Any]:
    expected_fields = {
        "schema_version",
        "state",
        "project_alias",
        "candidate_run_id",
        "admission_digest",
        "canary_request_digest",
        "full_plan_activation_digest",
        "full_plan_result_status",
        "completion_mode",
    }
    value = dict(terminal)

    if set(value) != expected_fields:
        raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_INVALID")
    if value["schema_version"] != _P3_TERMINAL_HANDOFF_SCHEMA:
        raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_INVALID")
    if value["state"] != _P3_TERMINAL_STATE:
        raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_INVALID")
    if value["completion_mode"] not in _P3_TERMINAL_COMPLETION_MODES:
        raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_INVALID")
    if value["full_plan_result_status"] not in _P3_TERMINAL_RESULT_STATUSES:
        raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_INVALID")

    for key in (
        "project_alias",
        "candidate_run_id",
        "admission_digest",
        "canary_request_digest",
        "full_plan_activation_digest",
    ):
        if not isinstance(value[key], str) or not value[key]:
            raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_INVALID")

    for key in (
        "admission_digest",
        "canary_request_digest",
        "full_plan_activation_digest",
    ):
        if len(value[key]) != 64:
            raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_INVALID")
        try:
            int(value[key], 16)
        except ValueError as exc:
            raise SuccessorStageRuntimeError(
                "P3_TERMINAL_HANDOFF_INVALID"
            ) from exc

    state_root = Path(config.state_root)
    if state_root.is_symlink():
        raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_ROOT_INVALID")

    root = state_root / "p3-lifecycle-handoffs"
    root.mkdir(parents=True, exist_ok=True)

    if root.is_symlink() or not root.is_dir():
        raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_ROOT_INVALID")
    try:
        if root.resolve(strict=True) != root.resolve():
            raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_ROOT_INVALID")
    except OSError as exc:
        raise SuccessorStageRuntimeError(
            "P3_TERMINAL_HANDOFF_ROOT_INVALID"
        ) from exc

    # admission_digest is immutable lineage identity.
    path = root / f"{value['admission_digest']}.terminal.json"

    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_CONFLICT")
        try:
            existing_raw = path.read_bytes()
            existing = json.loads(existing_raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorStageRuntimeError(
                "P3_TERMINAL_HANDOFF_CONFLICT"
            ) from exc

        canonical_existing = json.dumps(
            existing,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        if existing_raw != canonical_existing or existing != value:
            raise SuccessorStageRuntimeError("P3_TERMINAL_HANDOFF_CONFLICT")
        return existing

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return value


def _load_p3_waiting_handoff(config: base.RuntimeConfig, request) -> dict[str, Any]:
    if config.state_root is None:
        raise SuccessorStageRuntimeError("P3_PROMOTION_STATE_ROOT_REQUIRED")
    admission_digest = str(request.admission_digest or "")
    if not _SHA256.fullmatch(admission_digest):
        raise SuccessorStageRuntimeError("P3_HANDOFF_ADMISSION_DIGEST_INVALID")
    root = Path(config.state_root) / "p3-lifecycle-handoffs"
    if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root:
        raise SuccessorStageRuntimeError("P3_HANDOFF_STATE_UNSAFE")
    path = root / f"{admission_digest}.waiting.json"
    if path.is_symlink() or not path.is_file():
        raise SuccessorStageRuntimeError("P3_HANDOFF_WAITING_REQUIRED")
    try:
        raw = path.read_bytes()
        handoff = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SuccessorStageRuntimeError("P3_HANDOFF_STATE_UNREADABLE") from exc
    if raw != _canonical_json_bytes(handoff):
        raise SuccessorStageRuntimeError("P3_HANDOFF_STATE_UNREADABLE")
    expected = {
        "schema_version": _P3_HANDOFF_SCHEMA,
        "state": _P3_HANDOFF_WAITING,
        "last_completed_step": "P3_PROMOTION_ADMISSION",
        "next_required_request_kind": LIFECYCLE_V2_P3_CANARY_ACTIVATION_KIND,
        "project_alias": request.admission_request.project_alias,
        "candidate_run_id": request.admission_request.candidate_run_id,
        "admission_request_id": request.admission_request.request_id,
        "admission_request_digest": request.admission_request_digest,
        "admission_evidence_digest": request.admission_evidence_digest,
        "admission_digest": admission_digest,
        "authorization_required": True,
    }
    if handoff != expected:
        raise SuccessorStageRuntimeError("P3_HANDOFF_LINEAGE_MISMATCH")
    return handoff


def successor_release_stage_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    return str(environment.get("OCP_SUCCESSOR_RELEASE_STAGE_ENABLED") or "").strip() == "1"


def lifecycle_v2_p3_promotion_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    return str(environment.get("OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED") or "").strip() == "1"


def lifecycle_v2_p3_canary_activation_enabled_from_environment(
    environment: Mapping[str, str],
) -> bool:
    return str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_ENABLED") or "").strip() == "1"


def lifecycle_v2_p3_canary_validate_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    return str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_ENABLED") or "").strip() == "1"


def lifecycle_v2_p3_canary_validate_evidence_issue_enabled_from_environment(environment: Mapping[str, str]) -> bool:
    return str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_ENABLED") or "").strip() == "1"


def _safe_p3_validate_evidence_issue_policy_ref(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_POLICY_REF") or "").strip()
    if not value or ".." in value or not _POLICY_REF.fullmatch(value):
        raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_EVIDENCE_ISSUE_POLICY_REQUIRED")
    return value


def _safe_p3_validate_evidence_issue_policy_digest(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_POLICY_DIGEST") or "").strip()
    if not _SHA256.fullmatch(value):
        raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_EVIDENCE_ISSUE_POLICY_DIGEST_REQUIRED")
    return value


def _safe_p3_validate_policy_ref(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_POLICY_REF") or "").strip()
    if not value or ".." in value or not _POLICY_REF.fullmatch(value):
        raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_POLICY_REQUIRED")
    return value


def _safe_p3_validate_policy_digest(environment: Mapping[str, str]) -> str:
    value = str(environment.get("OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_POLICY_DIGEST") or "").strip()
    if not _SHA256.fullmatch(value):
        raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_POLICY_DIGEST_REQUIRED")
    return value


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
    """Verify the preserved predecessor service without invoking a service mutation."""

    def __init__(self, predecessor_root: Path):
        self._predecessor_root = predecessor_root.resolve()

    @staticmethod
    def _show(*properties: str) -> dict[str, str]:
        completed = subprocess.run(
            ["systemctl", "--user", "show", "ocpv2.service", *properties],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            text=True,
        )
        if completed.returncode != 0:
            return {}
        return {
            key: value
            for line in completed.stdout.splitlines()
            if "=" in line
            for key, value in (line.split("=", 1),)
        }

    def serving(self) -> bool:
        service = self._show("-p", "LoadState", "-p", "WorkingDirectory", "-p", "Environment", "-p", "Result")
        if service.get("LoadState") != "loaded" or service.get("Result") not in {"success", ""}:
            return False
        if Path(str(service.get("WorkingDirectory") or "/")).resolve() != self._predecessor_root:
            return False
        environment = str(service.get("Environment") or "")
        if "PYTHONPATH=" in environment:
            return False
        timer = subprocess.run(
            ["systemctl", "--user", "show", "ocpv2.timer", "-p", "ActiveState", "-p", "UnitFileState"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            text=True,
        )
        if timer.returncode != 0:
            return False
        timer_state = dict(
            line.split("=", 1)
            for line in timer.stdout.splitlines()
            if "=" in line
        )
        return (
            timer_state.get("ActiveState") == "active"
            and timer_state.get("UnitFileState") == "enabled"
        )


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
    receipt = _matching_staged_receipt(config, request)
    workspace = Path(str(receipt.get("canonical_successor_root") or "")).resolve(
        strict=True
    )
    if workspace != Path.cwd().resolve(strict=True):
        raise SuccessorStageRuntimeError("P3_PROMOTION_STAGE_IDENTITY_MISMATCH")
    project_id = str(receipt.get("project_id") or "")
    if not project_id:
        raise SuccessorStageRuntimeError("P3_PROMOTION_STAGE_IDENTITY_MISMATCH")
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
        / project_id
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

    predecessor_serving = _ReadOnlyPredecessorServiceStateProbe(config.repo_root).serving()
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
        handoff = _seal_p3_waiting_handoff(config, envelope.payload, evidence, result)
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
            "handoff": handoff,
        }

    service.admit_p3_promotion_authorized = admit_p3
    service.lifecycle_v2_p3_promotion_enabled = True
    service.lifecycle_v2_p3_promotion_policy_ref = policy_ref
    return service


def _wire_p3_canary_activation(config: base.RuntimeConfig, service):
    if not lifecycle_v2_p3_canary_activation_enabled_from_environment(config.environment):
        return service
    if not bool(getattr(config, "full_plan_activation_enabled", False)):
        raise SuccessorStageRuntimeError("P3_CANARY_ACTIVATION_FULL_PLAN_REQUIRED")
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

        # P3_REGISTERED_RECOVERY_WIRING_V1
        evidence_state = str(
            evidence.to_dict().get(
                "candidate_run_registration_state"
            ) or ""
        )

        if evidence_state == "REGISTERED":
            waiting_handoff = _load_p3_waiting_handoff(
                config,
                request,
            )

            recover_existing = getattr(
                canonical_full_plan,
                "recover_existing",
                None,
            )

            if not callable(recover_existing):
                raise SuccessorStageRuntimeError(
                    "P3_CANARY_RECOVERY_CALLBACK_UNAVAILABLE"
                )

            artifacts = recover_existing(envelope)

            if not isinstance(artifacts, Mapping):
                raise SuccessorStageRuntimeError(
                    "P3_CANARY_RECOVERY_ARTIFACTS_INVALID"
                )

            recovered = _recover_p3_registered_canary(
                waiting_handoff=waiting_handoff,
                request_digest=str(
                    artifacts.get("request_digest") or ""
                ),
                bundle_digest=str(
                    artifacts.get("bundle_digest") or ""
                ),
                receipt=artifacts.get("receipt"),
                canonical_job=artifacts.get("canonical_job"),
            )

            terminal = _seal_p3_terminal_handoff(
                config,
                {
                    "schema_version":
                        _P3_TERMINAL_HANDOFF_SCHEMA,
                    "state": _P3_TERMINAL_STATE,
                    "project_alias": request.admission_request.project_alias,
                    "candidate_run_id":
                        request.admission_request.candidate_run_id,
                    "admission_digest":
                        request.admission_digest,
                    "canary_request_digest":
                        request.request_digest,
                    "full_plan_activation_digest":
                        recovered["activation_digest"],
                    "full_plan_result_status":
                        recovered["result_status"],
                    "completion_mode":
                        "RECOVERED_EXISTING_ACTIVATION",
                },
            )

            return {
                "result_class": "P3_CANARY_ACTIVATED",
                "project_alias": terminal["project_alias"],
                "candidate_run_id": terminal["candidate_run_id"],
                "full_plan_result_status":
                    terminal["full_plan_result_status"],
                "completion_mode": terminal["completion_mode"],
                "admission_digest": terminal["admission_digest"],
                "canary_request_digest":
                    terminal["canary_request_digest"],
                "full_plan_activation_digest":
                    terminal["full_plan_activation_digest"],
            }

        admission = evaluate_p3_promotion_admission(admission_request, evidence)
        authorization = evaluate_p3_canary_activation(request, admission)
        _load_p3_waiting_handoff(config, request)
        try:
            validate_evidence = issue_p3_canary_validate_evidence(
                state_root=config.state_root,
                project_alias=admission_request.project_alias,
                candidate_run_id=admission_request.candidate_run_id,
                admission_request_id=admission_request.request_id,
                admission_request_digest=request.admission_request_digest,
                admission_evidence_digest=request.admission_evidence_digest,
                admission_digest=request.admission_digest,
                approval_ref=policy_ref,
            )
        except P3CanaryValidateEvidenceError as exc:
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_EVIDENCE_INVALID") from exc
        delegated = _P3FullPlanDelegation(
            message_id=envelope.message_id,
            request_kind=APPROVED_FULL_PLAN_ACTIVATION_KIND,
            payload=request.full_plan_activation,
        )
        result = canonical_full_plan(delegated, enqueue_projection=False)
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
            "p3_canary_validate_evidence_digest": validate_evidence.evidence_digest,
            "authorization": authorization.to_dict(),
        }

    service.activate_p3_canary_authorized = activate_p3_canary
    service.lifecycle_v2_p3_canary_activation_enabled = True
    service.lifecycle_v2_p3_canary_activation_policy_ref = policy_ref
    return service


def _wire_p3_canary_validate_registration(config: base.RuntimeConfig, service):
    if not lifecycle_v2_p3_canary_validate_enabled_from_environment(config.environment):
        return service
    policy_ref = _safe_p3_validate_policy_ref(config.environment)
    _safe_p3_validate_policy_digest(config.environment)

    def register_p3_validate(envelope) -> Mapping[str, Any]:
        request = envelope.payload
        if request.evidence.approval_ref != policy_ref:
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_POLICY_MISMATCH")
        observed = _collect_p3_promotion_evidence(config, request.admission_request)
        admission = evaluate_p3_promotion_admission(request.admission_request, observed)
        if (
            admission.status != request.admission_status
            or admission.request_digest != request.admission_request_digest
            or admission.evidence_digest != request.admission_evidence_digest
            or admission.admission_digest != request.admission_digest
        ):
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_ADMISSION_LINEAGE_MISMATCH")
        _load_p3_waiting_handoff(config, request)
        try:
            mapping_root = _mapping_root(config)
            alias_entry = OnboardingRegistry(mapping_root / "aliases").resolve_alias(
                request.admission_request.project_alias
            )
        except ProjectOnboardingError as exc:
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_PROJECT_UNAVAILABLE") from exc
        if alias_entry is None:
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_PROJECT_UNAVAILABLE")
        project_root = Path(str(alias_entry["project_root"])).absolute()
        if (
            project_root.is_symlink()
            or not project_root.is_dir()
            or project_root.resolve() != project_root
        ):
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_PROJECT_UNAVAILABLE")
        try:
            receipt = register_p3_canary_validate(
                state_root=config.state_root,
                project_root=project_root,
                binding=request.binding,
                evidence=request.evidence.to_dict(),
            )
        except P3CanaryValidateRegistrationError as exc:
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_REGISTRATION_INVALID") from exc
        return {
            "schema_version": "orchestration.remote-p3-canary-validate-registration-status-projection.v1",
            "message_id": envelope.message_id,
            "request_id": request.request_id,
            "project_alias": request.admission_request.project_alias,
            "request_digest": request.request_digest,
            "candidate_run_id": request.admission_request.candidate_run_id,
            "result_class": receipt.status,
            "registration": receipt.to_dict(),
        }

    service.register_p3_canary_validate_authorized = register_p3_validate
    service.lifecycle_v2_p3_canary_validate_enabled = True
    service.lifecycle_v2_p3_canary_validate_policy_ref = policy_ref
    return service


def _wire_p3_canary_validate_evidence_issue(config: base.RuntimeConfig, service):
    if not lifecycle_v2_p3_canary_validate_evidence_issue_enabled_from_environment(config.environment):
        return service
    policy_ref = _safe_p3_validate_evidence_issue_policy_ref(config.environment)
    _safe_p3_validate_evidence_issue_policy_digest(config.environment)

    def issue_p3_validate_evidence(envelope) -> Mapping[str, Any]:
        request = envelope.payload
        if request.approval_ref != policy_ref:
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_EVIDENCE_ISSUE_POLICY_MISMATCH")
        observed = _collect_p3_promotion_evidence(config, request.admission_request)
        admission = evaluate_p3_promotion_admission(request.admission_request, observed)
        if (admission.status != request.admission_status or admission.request_digest != request.admission_request_digest or admission.evidence_digest != request.admission_evidence_digest or admission.admission_digest != request.admission_digest):
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_EVIDENCE_ISSUE_ADMISSION_LINEAGE_MISMATCH")
        try:
            evidence = issue_p3_canary_validate_evidence(state_root=config.state_root, project_alias=request.admission_request.project_alias, candidate_run_id=request.admission_request.candidate_run_id, admission_request_id=request.admission_request.request_id, admission_request_digest=request.admission_request_digest, admission_evidence_digest=request.admission_evidence_digest, admission_digest=request.admission_digest, approval_ref=request.approval_ref)
        except P3CanaryValidateEvidenceError as exc:
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_EVIDENCE_ISSUE_INVALID") from exc
        return {"schema_version":"orchestration.remote-p3-canary-validate-evidence-issue-status-projection.v1","message_id":envelope.message_id,"request_id":request.request_id,"project_alias":request.admission_request.project_alias,"request_digest":request.request_digest,"candidate_run_id":request.admission_request.candidate_run_id,"result_class":"P3_CANARY_VALIDATE_EVIDENCE_ISSUED","evidence":evidence.to_dict()}

    service.issue_p3_canary_validate_evidence_authorized = issue_p3_validate_evidence
    service.lifecycle_v2_p3_canary_validate_evidence_enabled = True
    service.lifecycle_v2_p3_canary_validate_evidence_policy_ref = policy_ref
    return service


def compose_service(config: base.RuntimeConfig):
    service = base._compose_service(config)
    service = _wire_p3_promotion(config, service)
    service = _wire_p3_canary_validate_evidence_issue(config, service)
    service = _wire_p3_canary_validate_registration(config, service)
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



class _P3CanaryFilteredTransport:
    """Limit P3 Canary polling to the dedicated request kind before poll_limit."""

    def __init__(self, transport):
        self._transport = transport

    def receive(self, *, limit: int = 16):
        receiver = getattr(self._transport, "receive_request_kind", None)
        if not callable(receiver):
            raise SuccessorStageRuntimeError(
                "P3_CANARY_TRANSPORT_FILTER_REQUIRED"
            )
        return receiver(
            LIFECYCLE_V2_P3_CANARY_ACTIVATION_KIND,
            limit=limit,
        )

    def acknowledge_delivery(self, message_id: str) -> None:
        self._transport.acknowledge_delivery(message_id)

    def publish_projection(self, projection: Mapping[str, Any]) -> None:
        self._transport.publish_projection(projection)


class _SuccessorStageFilteredTransport(_P3CanaryFilteredTransport):
    """Receive only a successor-stage request during a bounded control poll."""

    def receive(self, *, limit: int = 16):
        receiver = getattr(self._transport, "receive_request_kind", None)
        if not callable(receiver):
            raise SuccessorStageRuntimeError("SUCCESSOR_STAGE_TRANSPORT_FILTER_REQUIRED")
        return receiver(SUCCESSOR_RELEASE_STAGE_KIND, limit=limit)


class _P3PromotionFilteredTransport(_P3CanaryFilteredTransport):
    """Receive only a P3 admission request during a bounded control poll."""

    def receive(self, *, limit: int = 16):
        receiver = getattr(self._transport, "receive_request_kind", None)
        if not callable(receiver):
            raise SuccessorStageRuntimeError("P3_PROMOTION_TRANSPORT_FILTER_REQUIRED")
        return receiver(LIFECYCLE_V2_P3_PROMOTION_ADMISSION_KIND, limit=limit)


class _P3CanaryValidateFilteredTransport(_P3CanaryFilteredTransport):
    """Receive only the validation-only P3 request during a bounded poll."""

    def receive(self, *, limit: int = 16):
        receiver = getattr(self._transport, "receive_request_kind", None)
        if not callable(receiver):
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_TRANSPORT_FILTER_REQUIRED")
        return receiver(LIFECYCLE_V2_P3_CANARY_VALIDATE_REGISTRATION_KIND, limit=limit)


class _P3CanaryValidateEvidenceIssueFilteredTransport(_P3CanaryFilteredTransport):
    def receive(self, *, limit: int = 16):
        receiver = getattr(self._transport, "receive_request_kind", None)
        if not callable(receiver):
            raise SuccessorStageRuntimeError("P3_CANARY_VALIDATE_EVIDENCE_ISSUE_TRANSPORT_FILTER_REQUIRED")
        return receiver(LIFECYCLE_V2_P3_CANARY_VALIDATE_EVIDENCE_ISSUE_KIND, limit=limit)


def run_once(config: base.RuntimeConfig) -> dict[str, Any]:
    if config.mode == ControlMode.DISABLED:
        result = base.run_once(config)
        result["successor_release_staged"] = 0
        result["p3_promotion_admitted"] = 0
        result["p3_canary_activated"] = 0
        return result
    service = compose_service(config)
    if successor_release_stage_enabled_from_environment(config.environment):
        service.transport = _SuccessorStageFilteredTransport(service.transport)
    elif ControlMode(config.mode) == ControlMode.LIFECYCLE_V2_P3_CANARY:
        service.transport = _P3CanaryFilteredTransport(service.transport)
    elif lifecycle_v2_p3_promotion_enabled_from_environment(config.environment):
        service.transport = _P3PromotionFilteredTransport(service.transport)
    elif lifecycle_v2_p3_canary_validate_enabled_from_environment(config.environment):
        service.transport = _P3CanaryValidateFilteredTransport(service.transport)
    elif lifecycle_v2_p3_canary_validate_evidence_issue_enabled_from_environment(config.environment):
        service.transport = _P3CanaryValidateEvidenceIssueFilteredTransport(service.transport)
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
        "p3_canary_validate_registered": getattr(result, "p3_canary_validate_registered", 0),
        "p3_canary_validate_evidence_issued": getattr(result, "p3_canary_validate_evidence_issued", 0),
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
    health = (
        base.full_plan_execution_health()
        if config.full_plan_activation_enabled
        else {"status": "NOT_APPLICABLE", "reason": "FULL_PLAN_ACTIVATION_DISABLED"}
    )
    status = "OK" if health["status"] in {"HEALTHY", "NOT_APPLICABLE"} else "DEGRADED"
    print(json.dumps({"status": status, "operational_health": health, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
