from __future__ import annotations

import inspect
import unittest
from dataclasses import FrozenInstanceError

from runtime.mprf import (
    ADMISSION_ADMITTED,
    ADMISSION_RECORD_SCHEMA_V1,
    CODEX_PROVIDER,
    MODEL_RECORD_SCHEMA_V1,
    NVIDIA_PROVIDER,
    PROVIDER_RECORD_SCHEMA_V1,
    REGISTRY_SCHEMA_V1,
    RUNTIME_SCHEMA_V1,
    AdmissionRecordV1,
    ModelRecordV1,
    MPRFContractError,
    MPRFRuntimeV1,
    ProviderModelRegistryV1,
    ProviderRecordV1,
)
from runtime.mprf.lifecycle import (
    CAPABILITY_MISSING,
    HEALTHY,
    LIFECYCLE_FACT_SCHEMA_V1,
    LIFECYCLE_OK,
    LIFECYCLE_STATE_SCHEMA_V1,
    QUOTA_AVAILABLE,
    QUOTA_EXHAUSTED,
    QUOTA_EXHAUSTED_REASON,
    QUOTA_UNKNOWN,
    RATE_AVAILABLE,
    RATE_LIMITED,
    RATE_LIMITED_REASON,
    RATE_UNKNOWN,
    STALE,
    STALE_HEALTH,
    STALE_LIFECYCLE_VERSION,
    UNKNOWN,
    UNKNOWN_HEALTH,
    UNKNOWN_QUOTA,
    UNKNOWN_RATE,
    LifecycleFactV1,
    LifecycleStateV1,
    evaluate_lifecycle,
)


def make_registry() -> ProviderModelRegistryV1:
    providers = (
        ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, NVIDIA_PROVIDER, 1),
        ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, CODEX_PROVIDER, 1),
    )
    models = (
        ModelRecordV1(MODEL_RECORD_SCHEMA_V1, NVIDIA_PROVIDER, "nvidia/model-a", 1),
        ModelRecordV1(MODEL_RECORD_SCHEMA_V1, CODEX_PROVIDER, "codex/model-b", 1),
    )
    admissions = (
        AdmissionRecordV1(ADMISSION_RECORD_SCHEMA_V1, "n1", NVIDIA_PROVIDER,
                          "nvidia/model-a", 1, ADMISSION_ADMITTED),
        AdmissionRecordV1(ADMISSION_RECORD_SCHEMA_V1, "c1", CODEX_PROVIDER,
                          "codex/model-b", 1, ADMISSION_ADMITTED),
    )
    return ProviderModelRegistryV1(REGISTRY_SCHEMA_V1, "registry-1", 1,
                                   providers, models, admissions)


def fact(
    provider_id: str,
    model_ref: str,
    *,
    lifecycle_version: int = 1,
    registry_version: int = 1,
    health_state: str = HEALTHY,
    quota_state: str = QUOTA_AVAILABLE,
    rate_state: str = RATE_AVAILABLE,
    capabilities: frozenset[str] = frozenset({"reasoning", "read_only"}),
) -> LifecycleFactV1:
    return LifecycleFactV1(
        LIFECYCLE_FACT_SCHEMA_V1,
        provider_id,
        model_ref,
        registry_version,
        lifecycle_version,
        health_state,
        quota_state,
        rate_state,
        capabilities,
    )


class MPRFLifecycleHealthTests(unittest.TestCase):
    def test_contract_is_versioned_immutable_and_fail_closed(self) -> None:
        item = fact(NVIDIA_PROVIDER, "nvidia/model-a")
        self.assertIsInstance(item.capabilities, frozenset)
        with self.assertRaises(FrozenInstanceError):
            item.lifecycle_version = 2
        with self.assertRaises(MPRFContractError):
            LifecycleFactV1("bad", NVIDIA_PROVIDER, "nvidia/model-a", 1, 1,
                            HEALTHY, QUOTA_AVAILABLE, RATE_AVAILABLE, frozenset())
        with self.assertRaises(MPRFContractError):
            fact("bad provider id", "other/model")
        with self.assertRaises(MPRFContractError):
            fact(NVIDIA_PROVIDER, "nvidia/model-a", lifecycle_version=True)
        with self.assertRaises(MPRFContractError):
            fact(NVIDIA_PROVIDER, "nvidia/model-a", health_state="DEGRADED")

    def test_health_quota_rate_and_capability_constraints_fail_closed(self) -> None:
        healthy = fact(NVIDIA_PROVIDER, "nvidia/model-a")
        self.assertEqual(evaluate_lifecycle(healthy, ("reasoning",)), (True, LIFECYCLE_OK))

        cases = (
            (fact(NVIDIA_PROVIDER, "nvidia/model-a", health_state=STALE), STALE_HEALTH),
            (fact(NVIDIA_PROVIDER, "nvidia/model-a", health_state=UNKNOWN), UNKNOWN_HEALTH),
            (fact(NVIDIA_PROVIDER, "nvidia/model-a", quota_state=QUOTA_EXHAUSTED),
             QUOTA_EXHAUSTED_REASON),
            (fact(NVIDIA_PROVIDER, "nvidia/model-a", quota_state=QUOTA_UNKNOWN), UNKNOWN_QUOTA),
            (fact(NVIDIA_PROVIDER, "nvidia/model-a", rate_state=RATE_LIMITED), RATE_LIMITED_REASON),
            (fact(NVIDIA_PROVIDER, "nvidia/model-a", rate_state=RATE_UNKNOWN), UNKNOWN_RATE),
        )
        for item, expected in cases:
            with self.subTest(reason=expected):
                self.assertEqual(evaluate_lifecycle(item), (False, expected))
        self.assertEqual(
            evaluate_lifecycle(healthy, ("filesystem_write",)),
            (False, CAPABILITY_MISSING),
        )

    def test_lifecycle_transition_is_deterministic_and_monotonic(self) -> None:
        first = fact(NVIDIA_PROVIDER, "nvidia/model-a", lifecycle_version=1)
        state = LifecycleStateV1(LIFECYCLE_STATE_SCHEMA_V1, 1, (first,))
        second = fact(NVIDIA_PROVIDER, "nvidia/model-a", lifecycle_version=2,
                      quota_state=QUOTA_EXHAUSTED)
        advanced = state.transition(second)
        self.assertEqual(advanced.state_version, 2)
        self.assertEqual(advanced.fact_for(NVIDIA_PROVIDER, "nvidia/model-a"), second)
        with self.assertRaises(MPRFContractError):
            state.transition(fact(NVIDIA_PROVIDER, "nvidia/model-a", lifecycle_version=3))
        with self.assertRaises(MPRFContractError):
            advanced.transition(fact(NVIDIA_PROVIDER, "nvidia/model-a", registry_version=0))

        rollover = advanced.transition(
            fact(NVIDIA_PROVIDER, "nvidia/model-a", registry_version=2, lifecycle_version=1)
        )
        self.assertEqual(rollover.state_version, 3)
        self.assertEqual(
            evaluate_lifecycle(
                rollover.fact_for(NVIDIA_PROVIDER, "nvidia/model-a"),
                expected_registry_version=1,
            ),
            (False, STALE_LIFECYCLE_VERSION),
        )
        with self.assertRaises(MPRFContractError):
            advanced.transition(
                fact(NVIDIA_PROVIDER, "nvidia/model-a", registry_version=2, lifecycle_version=2)
            )

    def test_runtime_combines_admission_and_lifecycle_into_router_facts(self) -> None:
        registry = make_registry()
        lifecycle = LifecycleStateV1(
            LIFECYCLE_STATE_SCHEMA_V1,
            1,
            (
                fact(NVIDIA_PROVIDER, "nvidia/model-a"),
                fact(CODEX_PROVIDER, "codex/model-b", quota_state=QUOTA_EXHAUSTED,
                     capabilities=frozenset({"filesystem_write"})),
            ),
        )
        runtime = MPRFRuntimeV1(RUNTIME_SCHEMA_V1, registry, lifecycle)
        snapshot = runtime.export_router_snapshot("snapshot-1", ("EVD-T020",), ("reasoning",))
        self.assertTrue(snapshot.provider_eligible[NVIDIA_PROVIDER])
        self.assertFalse(snapshot.provider_eligible[CODEX_PROVIDER])
        self.assertEqual(snapshot.model_refs, {NVIDIA_PROVIDER: "nvidia/model-a"})
        self.assertEqual(snapshot.evidence_refs, ("EVD-T020",))

    def test_missing_lifecycle_fact_is_ineligible_when_lifecycle_enabled(self) -> None:
        registry = make_registry()
        lifecycle = LifecycleStateV1(
            LIFECYCLE_STATE_SCHEMA_V1,
            1,
            (fact(NVIDIA_PROVIDER, "nvidia/model-a"),),
        )
        runtime = MPRFRuntimeV1(RUNTIME_SCHEMA_V1, registry, lifecycle)
        self.assertEqual(
            runtime.lifecycle_eligibility(CODEX_PROVIDER),
            (False, UNKNOWN_HEALTH),
        )

    def test_runtime_without_lifecycle_preserves_task010_behavior(self) -> None:
        registry = make_registry()
        runtime = MPRFRuntimeV1(RUNTIME_SCHEMA_V1, registry)
        direct = registry.export_router_snapshot("legacy")
        projected = runtime.export_router_snapshot("legacy")
        self.assertEqual(projected.to_dict(), direct.to_dict())
        self.assertEqual(
            runtime.lifecycle_eligibility(NVIDIA_PROVIDER, required_capabilities=("anything",)),
            (True, LIFECYCLE_OK),
        )

    def test_no_routing_selection_fallback_action_or_full_mcp_authority(self) -> None:
        public_names = {
            name.lower()
            for cls in (LifecycleFactV1, LifecycleStateV1, MPRFRuntimeV1)
            for name in dir(cls)
            if not name.startswith("_")
        }
        forbidden_prefixes = ("route", "select", "fallback", "execute", "action", "score")
        self.assertFalse(any(name.startswith(forbidden_prefixes) for name in public_names))
        source = inspect.getsource(LifecycleStateV1) + inspect.getsource(evaluate_lifecycle)
        self.assertNotIn("runtime.full_mcp", source)
        self.assertNotIn("ProviderRouter", source)
        self.assertNotIn("subprocess", source)


if __name__ == "__main__":
    unittest.main()
