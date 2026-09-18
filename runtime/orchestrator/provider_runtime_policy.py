from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from .codex_adapter import detect_codex_cli
from .provider_router import (
    ELIGIBILITY_SCHEMA_V1,
    GOVERNED_POLICY_V1,
    ProviderEligibilitySnapshotV1,
)


PROVIDER_GENERATION_CAPABILITIES_V1 = {
    "nvidia": (
        "read_only", "reasoning", "evidence_analysis", "code_generation", "patch_generation",
        "test_design", "implementation_generation", "integration", "review", "diagnostics",
        "documentation", "security_review",
    ),
    "codex": (
        "read_only", "reasoning", "evidence_analysis", "code_generation", "patch_generation",
        "test_design", "implementation_generation", "integration", "review", "diagnostics",
        "documentation", "security_review", "native_tool_action",
    ),
}


def collect_static_provider_eligibility(
    run_id: str,
    *,
    codex_ready_override: bool | None = None,
    extra_evidence_refs: Iterable[str] = (),
) -> ProviderEligibilitySnapshotV1:
    """Collect the approved pre-MPRF static provider/model eligibility snapshot.

    Provider selection is not performed here.  This function only projects the
    existing file-backed NVIDIA/Codex policy and current readiness facts into
    the immutable snapshot consumed by Provider Router.
    """
    pool_path = Path(
        os.getenv(
            "GCH_NVIDIA_MODEL_POOL",
            str(Path.home() / ".config" / "gch" / "nvidia-model-pool.json"),
        )
    ).expanduser()
    nvidia_model = ""
    nvidia_fallbacks: tuple[str, ...] = ()
    evidence_refs: list[str] = ["pre-mprf-static-policy", *[str(x) for x in extra_evidence_refs if str(x)]]

    if pool_path.is_file() and not pool_path.is_symlink():
        try:
            raw = pool_path.read_bytes()
            pool = json.loads(raw.decode("utf-8"))
            models = pool.get("models", {})
            policy = pool.get("policy", {})
            role = str(pool.get("default_role", "primary_heavy"))
            record = models.get(role, {}) if isinstance(models, dict) else {}
            valid_policy = (
                pool.get("schema_version") == "gch.nvidia.model-pool.v1"
                and isinstance(record, dict)
                and record.get("status") == "ACTIVE"
                and policy.get("automatic_provider_fallback") is False
                and policy.get("state_changing_execution") is False
            )
            if valid_policy:
                nvidia_model = str(record.get("model", "")).strip()
                raw_fallbacks = record.get("fallback_models", [])
                if policy.get("automatic_model_failover") is True and isinstance(raw_fallbacks, list):
                    candidates = tuple(str(item).strip() for item in raw_fallbacks if str(item).strip())
                    if len(candidates) == len(set(candidates)) and nvidia_model not in candidates:
                        nvidia_fallbacks = candidates
                evidence_refs.append(
                    f"nvidia-model-pool-sha256:{hashlib.sha256(raw).hexdigest()}"
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, AttributeError):
            nvidia_model = ""

    nvidia_eligible = bool(os.getenv("NVIDIA_API_KEY", "").strip() and nvidia_model)

    codex_model = ""
    codex_policy_path = Path(
        os.getenv(
            "GCH_PRE_MPRF_PROVIDER_POLICY",
            str(Path.home() / ".config" / "gch" / "pre-mprf-provider-policy.json"),
        )
    ).expanduser()
    if codex_policy_path.is_file() and not codex_policy_path.is_symlink():
        try:
            raw = codex_policy_path.read_bytes()
            policy_doc = json.loads(raw.decode("utf-8"))
            providers = policy_doc.get("providers", {})
            codex_record = providers.get("codex", {}) if isinstance(providers, dict) else {}
            provider_names = set(providers) if isinstance(providers, dict) else set()
            valid_codex_policy = (
                policy_doc.get("schema_version") == "gch.pre-mprf.provider-policy.v1"
                and policy_doc.get("policy_profile") == GOVERNED_POLICY_V1
                and provider_names.issubset({"codex"})
                and isinstance(codex_record, dict)
                and codex_record.get("status") == "ACTIVE"
                and bool(str(codex_record.get("approval_ref", "")).strip())
            )
            if valid_codex_policy:
                codex_model = str(codex_record.get("model", "")).strip()
                if codex_model:
                    evidence_refs.append(
                        f"pre-mprf-provider-policy-sha256:{hashlib.sha256(raw).hexdigest()}"
                    )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, AttributeError):
            codex_model = ""

    codex_runtime_ready = detect_codex_cli() if codex_ready_override is None else bool(codex_ready_override)
    codex_eligible = bool(codex_model and codex_runtime_ready)

    model_refs: dict[str, str] = {}
    if nvidia_model:
        model_refs["nvidia"] = nvidia_model
    if codex_model:
        model_refs["codex"] = codex_model

    return ProviderEligibilitySnapshotV1(
        schema_version=ELIGIBILITY_SCHEMA_V1,
        snapshot_id=f"pre-mprf-{run_id}",
        provider_eligible={"nvidia": nvidia_eligible, "codex": codex_eligible},
        model_refs=model_refs,
        evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        model_fallback_refs={"nvidia": nvidia_fallbacks} if nvidia_fallbacks else None,
        provider_capabilities=PROVIDER_GENERATION_CAPABILITIES_V1,
    )
