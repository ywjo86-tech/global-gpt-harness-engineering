from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Iterable

from runtime.mprf.contracts import (
    ADMISSION_ADMITTED, ADMISSION_RECORD_SCHEMA_V1, CODEX_PROVIDER, MODEL_RECORD_SCHEMA_V1,
    NVIDIA_PROVIDER, PROVIDER_RECORD_SCHEMA_V1, AdmissionRecordV1, ModelRecordV1, ProviderRecordV1,
)
from runtime.mprf.registry import REGISTRY_SCHEMA_V1, ProviderModelRegistryV1
from runtime.mprf.runtime import MPRFRuntimeV1, RUNTIME_SCHEMA_V1
from runtime.mprf.lifecycle import LifecycleStateV1

from . import provider_runtime_policy as runtime_policy
from .provider_router import ELIGIBILITY_SCHEMA_V1, ProviderEligibilitySnapshotV1
from .provider_candidate_inventory import (
    ProviderCandidateInventoryV1, load_canonical_candidate_inventory, project_active_candidates,
)


class ProviderRuntimeBindingError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ProviderRuntimeBindingError(f"unsafe or missing provider runtime file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderRuntimeBindingError(f"malformed provider runtime JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ProviderRuntimeBindingError(f"provider runtime JSON object required: {path}")
    return value


def _parse_secret_file(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise ProviderRuntimeBindingError("NVIDIA secret source is missing or unsafe")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ProviderRuntimeBindingError("NVIDIA secret source permissions are too broad")
    result: dict[str, str] = {}
    allowed = {"NVIDIA_API_KEY", "NVIDIA_MODEL"}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ProviderRuntimeBindingError("NVIDIA secret source contains invalid assignment")
        key, value = line.split("=", 1)
        key = key.strip(); value = value.strip()
        if key not in allowed:
            continue
        if any(token in value for token in ("$(", "`")):
            raise ProviderRuntimeBindingError("NVIDIA secret source contains unsupported expansion")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if not value:
            raise ProviderRuntimeBindingError(f"NVIDIA secret value is empty: {key}")
        result[key] = value
    return result


def ensure_nvidia_runtime_environment() -> tuple[str, ...]:
    pool_path = Path(os.getenv("GCH_NVIDIA_MODEL_POOL", str(Path.home()/".config/gch/nvidia-model-pool.json"))).expanduser()
    if not pool_path.exists():
        return ()
    pool = _load_json(pool_path)
    policy = pool.get("policy", {})
    if pool.get("schema_version") != "gch.nvidia.model-pool.v1" or not isinstance(policy, dict):
        raise ProviderRuntimeBindingError("NVIDIA model pool contract is invalid")
    refs = [f"nvidia-model-pool-sha256:{_sha256(pool_path)}"]
    if os.getenv("NVIDIA_API_KEY", "").strip():
        refs.append("nvidia-secret-source:process-environment")
        return tuple(refs)
    source = str(policy.get("secret_source", "")).strip()
    if not source:
        return tuple(refs)
    secret_path = Path(source).expanduser()
    values = _parse_secret_file(secret_path)
    api_key = values.get("NVIDIA_API_KEY", "").strip()
    if api_key:
        os.environ["NVIDIA_API_KEY"] = api_key
    if not os.getenv("NVIDIA_MODEL", "").strip() and values.get("NVIDIA_MODEL", "").strip():
        os.environ["NVIDIA_MODEL"] = values["NVIDIA_MODEL"].strip()
    refs.append(f"nvidia-secret-source-sha256:{_sha256(secret_path)}")
    return tuple(refs)


def _mprf_approval(project_root: str | Path) -> tuple[bool, str]:
    path = Path(project_root).resolve()/"docs/history/upgrades/PREPH5MPRF/TASK-016/MULTI_PROVIDER_FOUNDATION_BASELINE_FINAL_APPROVAL_20260918.json"
    if not path.exists():
        return False, ""
    value = _load_json(path)
    valid = (
        value.get("schema_version") == "gch.multi-provider-foundation.baseline-final-approval.v1"
        and value.get("baseline_id") == "MULTI_PROVIDER_FOUNDATION_BASELINE"
        and value.get("final_record_status") == "APPROVED_SEALED"
        and value.get("normalized_decision") == "FINAL_APPROVED"
        and value.get("gate010_independent_review") == "PASS"
    )
    if not valid:
        raise ProviderRuntimeBindingError("MPRF baseline approval is present but invalid")
    return True, f"mprf-baseline-approval-sha256:{_sha256(path)}"


def _mprf_snapshot_from_policy(
    project_root: str | Path, run_id: str, *, required_capabilities: Iterable[str],
    codex_ready_override: bool | None, extra_evidence_refs: Iterable[str],
    lifecycle_state: LifecycleStateV1 | None = None,
) -> ProviderEligibilitySnapshotV1:
    active, approval_ref = _mprf_approval(project_root)
    if not active:
        return runtime_policy.collect_static_provider_eligibility(
            run_id, codex_ready_override=codex_ready_override, extra_evidence_refs=extra_evidence_refs
        )
    env_refs = ensure_nvidia_runtime_environment()
    source = runtime_policy.collect_static_provider_eligibility(
        run_id, codex_ready_override=codex_ready_override, extra_evidence_refs=extra_evidence_refs
    )
    providers = (
        ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, NVIDIA_PROVIDER, 1),
        ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, CODEX_PROVIDER, 1),
    )
    models = []
    admissions = []
    for provider in (NVIDIA_PROVIDER, CODEX_PROVIDER):
        model = str(source.model_refs.get(provider, "")).strip()
        if model:
            models.append(ModelRecordV1(MODEL_RECORD_SCHEMA_V1, provider, model, 1))
        if model and bool(source.provider_eligible.get(provider, False)):
            admissions.append(AdmissionRecordV1(
                ADMISSION_RECORD_SCHEMA_V1, f"production-{provider}-{run_id}", provider, model, 1, ADMISSION_ADMITTED
            ))
    registry = ProviderModelRegistryV1(
        REGISTRY_SCHEMA_V1, f"production-mprf-{run_id}", 1, providers, tuple(models), tuple(admissions)
    )
    runtime = MPRFRuntimeV1(RUNTIME_SCHEMA_V1, registry, lifecycle_state)
    refs = [approval_ref, "provider-runtime-source:mprf"]
    refs.extend(ref for ref in source.evidence_refs if ref != "pre-mprf-static-policy")
    refs.extend(env_refs)
    snapshot = runtime.export_router_snapshot(
        f"mprf-{run_id}", tuple(dict.fromkeys(refs)), tuple(required_capabilities)
    )
    fallback_refs = {
        provider: tuple(refs)
        for provider, refs in dict(source.model_fallback_refs or {}).items()
        if provider in snapshot.model_refs and tuple(refs)
    } or None
    return ProviderEligibilitySnapshotV1(
        ELIGIBILITY_SCHEMA_V1, snapshot.snapshot_id, snapshot.provider_eligible, snapshot.model_refs,
        snapshot.evidence_refs, snapshot.failure_classes, fallback_refs, source.provider_capabilities,
    )


def collect_production_provider_eligibility(
    project_root: str | Path, run_id: str, *, required_capabilities: Iterable[str] = (),
    codex_ready_override: bool | None = None, extra_evidence_refs: Iterable[str] = (),
    lifecycle_state: LifecycleStateV1 | None = None,
    candidate_inventory: ProviderCandidateInventoryV1 | None = None,
) -> ProviderEligibilitySnapshotV1:
    try:
        snapshot = _mprf_snapshot_from_policy(
            project_root, run_id, required_capabilities=tuple(required_capabilities),
            codex_ready_override=codex_ready_override, extra_evidence_refs=extra_evidence_refs,
            lifecycle_state=lifecycle_state,
        )
        inventory = candidate_inventory if candidate_inventory is not None else load_canonical_candidate_inventory(project_root)
        return project_active_candidates(snapshot, inventory) if inventory.records else snapshot
    except ProviderRuntimeBindingError:
        raise
    except Exception as exc:
        raise ProviderRuntimeBindingError("MPRF production binding failed closed") from exc
