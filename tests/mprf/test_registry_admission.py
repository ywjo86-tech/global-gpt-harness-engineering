from __future__ import annotations

import inspect
import unittest
from dataclasses import FrozenInstanceError

from runtime.mprf import (
    ADMISSION_ADMITTED,
    ADMISSION_DISABLED,
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
from runtime.orchestrator.provider_router import ProviderEligibilitySnapshotV1


def provider_records() -> tuple[ProviderRecordV1, ...]:
    return (
        ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, NVIDIA_PROVIDER, 1),
        ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, CODEX_PROVIDER, 1),
    )


def model_records() -> tuple[ModelRecordV1, ...]:
    return (
        ModelRecordV1(MODEL_RECORD_SCHEMA_V1, NVIDIA_PROVIDER, "nvidia/model-a", 1),
        ModelRecordV1(MODEL_RECORD_SCHEMA_V1, CODEX_PROVIDER, "codex/model-b", 1),
    )


def admission(admission_id: str, provider: str, model: str, *, version: int = 1,
              state: str = ADMISSION_ADMITTED) -> AdmissionRecordV1:
    return AdmissionRecordV1(
        ADMISSION_RECORD_SCHEMA_V1, admission_id, provider, model, version, state
    )


def make_registry(*, version: int = 1,
                  admissions: tuple[AdmissionRecordV1, ...] = ()) -> ProviderModelRegistryV1:
    return ProviderModelRegistryV1(
        REGISTRY_SCHEMA_V1,
        f"registry-{version}",
        version,
        provider_records(),
        model_records(),
        admissions,
    )


class MPRFRegistryAdmissionTests(unittest.TestCase):
    def test_exact_provider_domain_and_schema_versions_fail_closed(self) -> None:
        with self.assertRaises(MPRFContractError):
            ProviderRecordV1("bad", NVIDIA_PROVIDER, 1)
        with self.assertRaises(MPRFContractError):
            ProviderRecordV1(PROVIDER_RECORD_SCHEMA_V1, "local", 1)
        with self.assertRaises(MPRFContractError):
            ModelRecordV1("bad", NVIDIA_PROVIDER, "nvidia/model-a", 1)
        with self.assertRaises(MPRFContractError):
            AdmissionRecordV1("bad", "a", NVIDIA_PROVIDER, "nvidia/model-a", 1)
        with self.assertRaises(MPRFContractError):
            ProviderModelRegistryV1(
                REGISTRY_SCHEMA_V1, "partial", 1,
                (provider_records()[0],), model_records()[:1], (),
            )
        with self.assertRaises(MPRFContractError):
            ProviderModelRegistryV1(
                "bad", "registry", 1, provider_records(), model_records(), (),
            )

    def test_records_are_versioned_and_immutable(self) -> None:
        provider = provider_records()[0]
        item = admission("a1", NVIDIA_PROVIDER, "nvidia/model-a")
        self.assertEqual(provider.record_version, 1)
        self.assertEqual(item.registry_version, 1)
        with self.assertRaises(FrozenInstanceError):
            provider.provider_id = CODEX_PROVIDER  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            item.state = ADMISSION_DISABLED  # type: ignore[misc]

    def test_duplicate_and_conflicting_admissions_are_rejected(self) -> None:
        duplicate = admission("same", NVIDIA_PROVIDER, "nvidia/model-a")
        with self.assertRaises(MPRFContractError):
            make_registry(admissions=(duplicate, duplicate))

        extra_model = ModelRecordV1(
            MODEL_RECORD_SCHEMA_V1, NVIDIA_PROVIDER, "nvidia/model-c", 1
        )
        with self.assertRaises(MPRFContractError):
            ProviderModelRegistryV1(
                REGISTRY_SCHEMA_V1, "conflict", 1, provider_records(),
                model_records() + (extra_model,),
                (
                    admission("a1", NVIDIA_PROVIDER, "nvidia/model-a"),
                    admission("a2", NVIDIA_PROVIDER, "nvidia/model-c"),
                ),
            )

        with self.assertRaises(MPRFContractError):
            make_registry(admissions=(
                admission("future", NVIDIA_PROVIDER, "nvidia/model-a", version=2),
            ))

    def test_unknown_disabled_and_stale_states_fail_closed(self) -> None:
        registry = make_registry(admissions=(
            admission("n1", NVIDIA_PROVIDER, "nvidia/model-a"),
            admission("c1", CODEX_PROVIDER, "codex/model-b", state=ADMISSION_DISABLED),
        ))
        admitted = registry.eligibility_fact(NVIDIA_PROVIDER)
        disabled = registry.eligibility_fact(CODEX_PROVIDER)
        unknown_provider = registry.eligibility_fact("local")
        unknown_model = registry.eligibility_fact(NVIDIA_PROVIDER, "nvidia/unknown")
        self.assertTrue(admitted.eligible)
        self.assertEqual(admitted.reason_code, "ADMITTED")
        self.assertFalse(disabled.eligible)
        self.assertEqual(disabled.reason_code, "ADMISSION_DISABLED")
        self.assertEqual(unknown_provider.reason_code, "UNKNOWN_PROVIDER")
        self.assertEqual(unknown_model.reason_code, "UNKNOWN_MODEL")

        stale = make_registry(version=2, admissions=(
            admission("old", NVIDIA_PROVIDER, "nvidia/model-a", version=1),
        )).eligibility_fact(NVIDIA_PROVIDER)
        self.assertFalse(stale.eligible)
        self.assertEqual(stale.reason_code, "STALE_ADMISSION")

    def test_router_snapshot_conversion_exposes_facts_only(self) -> None:
        registry = make_registry(admissions=(
            admission("n1", NVIDIA_PROVIDER, "nvidia/model-a"),
            admission("c1", CODEX_PROVIDER, "codex/model-b", state=ADMISSION_DISABLED),
        ))
        runtime = MPRFRuntimeV1(RUNTIME_SCHEMA_V1, registry)
        snapshot = runtime.export_router_snapshot("snapshot-1", ("evidence-1",))
        self.assertIsInstance(snapshot, ProviderEligibilitySnapshotV1)
        self.assertEqual(snapshot.provider_eligible, {CODEX_PROVIDER: False, NVIDIA_PROVIDER: True})
        self.assertEqual(snapshot.model_refs, {NVIDIA_PROVIDER: "nvidia/model-a"})
        self.assertEqual(snapshot.evidence_refs, ("evidence-1",))

    def test_no_selection_action_or_full_mcp_authority_surface(self) -> None:
        forbidden = ("route", "select", "score", "fallback", "execute", "action")
        public_names = {
            name for cls in (ProviderModelRegistryV1, MPRFRuntimeV1)
            for name in dir(cls) if not name.startswith("_")
        }
        self.assertFalse(any(name.startswith(forbidden) for name in public_names), public_names)
        source = inspect.getsource(ProviderModelRegistryV1) + inspect.getsource(MPRFRuntimeV1)
        self.assertNotIn("runtime.full_mcp", source)
        self.assertNotIn("route_request(", source)


if __name__ == "__main__":
    unittest.main()
