import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.operational_runtime_compatibility import (
    build_runtime_compatibility_manifest,
    record_runtime_compatibility_manifest,
)
from runtime.orchestrator.production_control_action import (
    CanonicalProductionControlBackend,
    ProductionControlActionError,
    ProductionControlActionExecutor,
    ProductionControlBackendOutcome,
    ProductionControlServerConfig,
)
from runtime.orchestrator.production_control_contract import (
    OCP_QUIESCE,
    P4_CUTOVER,
    PRODUCTION_CONTROL_ACTION_SCHEMA_V1,
    RETIRE_FULL_PLAN_RUN,
    SYNC_OPERATIONAL_RUNTIME_IDENTITY,
    ProductionControlActionRequestV1,
)

NOW = datetime(2026, 10, 7, 23, 20, tzinfo=timezone.utc)


class FakeBackend:
    def __init__(self, state_digest, *, outcome=None, error=None):
        self.state_digest = state_digest
        self.outcome = outcome or ProductionControlBackendOutcome(
            "VERIFIED",
            "FAKE_VERIFIED",
            {"ok": True},
            evidence_refs=("effect:fake",),
            evidence_digests=("9" * 64,),
        )
        self.error = error
        self.calls = 0

    def current_state_digest(self, request):
        return self.state_digest

    def apply(self, request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.outcome


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class ProductionControlActionTests(unittest.TestCase):
    def _fixture(self, root: Path, *, idempotency_key="IDEMP-1", request_id="REQ-1"):
        state = root / "state"
        state.mkdir(parents=True)
        proof_rel = Path("_workspace/full-plan-human-approvals/ACT-1.json")
        proof = state / proof_rel
        proof.parent.mkdir(parents=True)
        proof_value = {
            "status": "APPROVED",
            "approval_ref": "OCP-FULL-PLAN-TEST-1",
            "activation_id": "ACT-1",
            "plan_digest": "a" * 64,
            "issued_at": "2026-10-07T23:10:00+00:00",
            "expires_at": "2026-10-07T23:40:00+00:00",
            "revoked_at": None,
            "proof": {"jws": "opaque"},
        }
        proof.write_bytes(_canonical(proof_value))
        proof_sha = hashlib.sha256(proof.read_bytes()).hexdigest()
        request = ProductionControlActionRequestV1.from_mapping({
            "schema_version": PRODUCTION_CONTROL_ACTION_SCHEMA_V1,
            "request_id": request_id,
            "project_id": "global-gpt-harness",
            "action": RETIRE_FULL_PLAN_RUN,
            "approval_ref": "OCP-FULL-PLAN-TEST-1",
            "activation_id": "ACT-1",
            "plan_digest": "a" * 64,
            "approval_proof_path": proof_rel.as_posix(),
            "approval_proof_sha256": proof_sha,
            "expected_state_sha256": "c" * 64,
            "expected_runtime_source_head": "d" * 40,
            "target_runtime_source_head": "e" * 40,
            "target_runtime_manifest_sha256": "f" * 64,
            "idempotency_key": idempotency_key,
            "parameters": {
                "run_id": "RUN-1",
                "expected_terminal_reason": "RETRY_BUDGET_EXHAUSTED",
            },
        })
        return state, proof, request

    def test_verified_action_replays_idempotently_without_backend_reexecution(self):
        with tempfile.TemporaryDirectory() as td:
            state, _, request = self._fixture(Path(td))
            backend = FakeBackend("c" * 64)
            executor = ProductionControlActionExecutor(
                harness_state_root=state, backend=backend
            )
            first = executor.execute(request, now=NOW)
            second = executor.execute(request, now=NOW)
            self.assertEqual(first.status, "VERIFIED")
            self.assertEqual(second.status, "VERIFIED")
            self.assertEqual(second.result_class, "IDEMPOTENT_REPLAY_VERIFIED")
            self.assertEqual(backend.calls, 1)

    def test_stale_state_fails_before_effect(self):
        with tempfile.TemporaryDirectory() as td:
            state, _, request = self._fixture(Path(td))
            backend = FakeBackend("0" * 64)
            executor = ProductionControlActionExecutor(
                harness_state_root=state, backend=backend
            )
            with self.assertRaisesRegex(
                ProductionControlActionError, "EXPECTED_STATE_MISMATCH"
            ):
                executor.execute(request, now=NOW)
            self.assertEqual(backend.calls, 0)

    def test_runtime_binding_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state, _, request = self._fixture(root)
            releases = root / "releases"
            releases.mkdir()
            wrong = releases / ("0" * 40)
            wrong.mkdir()
            link = root / "runtime-current"
            link.symlink_to(wrong)
            backend = CanonicalProductionControlBackend(
                ProductionControlServerConfig(
                    harness_state_root=state,
                    releases_root=releases,
                    runtime_link=link,
                    runtime_compatibility_manifest=root / "compat.json",
                )
            )
            backend._release = lambda head: SimpleNamespace(
                manifest_sha256=request.target_runtime_manifest_sha256
            )
            with self.assertRaisesRegex(
                ProductionControlActionError, "runtime-current source mismatch"
            ):
                backend.current_state_digest(request)

    def test_approval_proof_digest_and_binding_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            state, proof, request = self._fixture(Path(td))
            backend = FakeBackend("c" * 64)
            executor = ProductionControlActionExecutor(
                harness_state_root=state, backend=backend
            )
            proof.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(
                ProductionControlActionError, "approval proof digest mismatch"
            ):
                executor.execute(request, now=NOW)
            self.assertEqual(backend.calls, 0)

    def test_conflicting_request_with_same_idempotency_key_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state, _, request = self._fixture(root)
            backend = FakeBackend("c" * 64)
            executor = ProductionControlActionExecutor(
                harness_state_root=state, backend=backend
            )
            executor.execute(request, now=NOW)
            _, _, conflict = self._fixture(
                root / "second", idempotency_key="IDEMP-1", request_id="REQ-2"
            )
            # Rebind the second request to the first durable state/proof.
            conflict_value = conflict.to_dict()
            conflict_value["approval_proof_path"] = request.approval_proof_path
            conflict_value["approval_proof_sha256"] = request.approval_proof_sha256
            conflict = ProductionControlActionRequestV1.from_mapping(conflict_value)
            with self.assertRaisesRegex(
                ProductionControlActionError, "IDEMPOTENCY_KEY_CONFLICT"
            ):
                executor.execute(conflict, now=NOW)
            self.assertEqual(backend.calls, 1)

    def test_ambiguous_effect_is_never_automatically_retried(self):
        with tempfile.TemporaryDirectory() as td:
            state, _, request = self._fixture(Path(td))
            backend = FakeBackend("c" * 64, error=RuntimeError("boom"))
            executor = ProductionControlActionExecutor(
                harness_state_root=state, backend=backend
            )
            with self.assertRaisesRegex(
                ProductionControlActionError, "ACTION_EFFECT_AMBIGUOUS"
            ):
                executor.execute(request, now=NOW)
            with self.assertRaisesRegex(
                ProductionControlActionError, "AMBIGUOUS_EFFECT_RETRY_FORBIDDEN"
            ):
                executor.execute(request, now=NOW)
            self.assertEqual(backend.calls, 1)

    def test_rollback_outcome_is_durably_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            state, _, request = self._fixture(Path(td))
            outcome = ProductionControlBackendOutcome(
                "ROLLED_BACK",
                "FAKE_ROLLBACK_VERIFIED",
                {"rollback": True},
                evidence_refs=("rollback:fake",),
                evidence_digests=("8" * 64,),
            )
            executor = ProductionControlActionExecutor(
                harness_state_root=state,
                backend=FakeBackend("c" * 64, outcome=outcome),
            )
            result = executor.execute(request, now=NOW)
            self.assertEqual(result.status, "ROLLED_BACK")
            events = sorted(
                (state / "_workspace/production-control-actions/IDEMP-1/events").glob(
                    "*.json"
                )
            )
            statuses = [json.loads(path.read_text())["status"] for path in events]
            self.assertIn("ROLLED_BACK", statuses)

    def test_expired_approval_proof_fails_before_effect(self):
        with tempfile.TemporaryDirectory() as td:
            state, _, request = self._fixture(Path(td))
            backend = FakeBackend("c" * 64)
            executor = ProductionControlActionExecutor(
                harness_state_root=state, backend=backend
            )
            late = datetime(2026, 10, 7, 23, 41, tzinfo=timezone.utc)
            with self.assertRaisesRegex(
                ProductionControlActionError, "approval proof binding mismatch"
            ):
                executor.execute(request, now=late)
            self.assertEqual(backend.calls, 0)


class ProductionControlBackendSafetyTests(unittest.TestCase):
    @staticmethod
    def _request(*, action, parameters, expected_state="c" * 64,
                 source="a" * 40, target="b" * 40, target_manifest="d" * 64):
        return ProductionControlActionRequestV1.from_mapping({
            "schema_version": PRODUCTION_CONTROL_ACTION_SCHEMA_V1,
            "request_id": f"REQ-{action}",
            "project_id": "global-gpt-harness",
            "action": action,
            "approval_ref": "OCP-FULL-PLAN-TEST-1",
            "activation_id": "ACT-1",
            "plan_digest": "e" * 64,
            "approval_proof_path": "_workspace/full-plan-human-approvals/ACT-1.json",
            "approval_proof_sha256": "f" * 64,
            "expected_state_sha256": expected_state,
            "expected_runtime_source_head": source,
            "target_runtime_source_head": target,
            "target_runtime_manifest_sha256": target_manifest,
            "idempotency_key": f"IDEMP-{action}",
            "parameters": parameters,
        })

    @staticmethod
    def _config(root: Path, *, identity_files=()):
        state = root / "state"
        releases = root / "releases"
        state.mkdir(parents=True, exist_ok=True)
        releases.mkdir(parents=True, exist_ok=True)
        compatibility = root / "operational-runtime-compatibility.json"
        if not compatibility.exists():
            compatibility.write_text("{}\n", encoding="utf-8")
        return ProductionControlServerConfig(
            harness_state_root=state,
            releases_root=releases,
            runtime_link=root / "runtime-current",
            runtime_compatibility_manifest=compatibility,
            operational_identity_files=tuple(identity_files),
            job_search_root=state,
        )

    def test_runtime_current_drift_fails_before_target_release_or_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = self._config(root)
            request = self._request(
                action=RETIRE_FULL_PLAN_RUN,
                parameters={
                    "run_id": "RUN-1",
                    "expected_terminal_reason": "RETRY_BUDGET_EXHAUSTED",
                },
            )
            backend = CanonicalProductionControlBackend(config)
            with patch(
                "runtime.orchestrator.production_control_action._runtime_link_head",
                return_value="0" * 40,
            ), patch.object(backend, "_release") as release:
                with self.assertRaisesRegex(
                    ProductionControlActionError, "runtime-current source mismatch"
                ):
                    backend._validate_runtime_binding(request)
                release.assert_not_called()

    def test_ocp_partial_quiesce_failure_restores_exact_prior_unit_state(self):
        class Controller:
            def __init__(self):
                self.states = {
                    "ocpv2.service": True,
                    "ocpv2.timer": True,
                }
                self.fail_timer_once = True

            def is_active(self, unit):
                return self.states[unit]

            def stop(self, unit):
                if unit == "ocpv2.timer" and self.fail_timer_once:
                    self.fail_timer_once = False
                    raise RuntimeError("simulated stop failure")
                self.states[unit] = False

            def start(self, unit):
                self.states[unit] = True

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            controller = Controller()
            backend = CanonicalProductionControlBackend(
                self._config(root), service_controller=controller
            )
            request = self._request(
                action=OCP_QUIESCE,
                parameters={"units": ["ocpv2.service", "ocpv2.timer"]},
            )
            outcome = backend._ocp_units(request, start=False)
            self.assertEqual(outcome.status, "ROLLED_BACK")
            self.assertEqual(outcome.result_class, "OCP_UNIT_STATE_ROLLED_BACK")
            self.assertTrue(outcome.effect["rollback_verified"])
            self.assertEqual(
                controller.states,
                {"ocpv2.service": True, "ocpv2.timer": True},
            )

    def test_runtime_identity_failure_restores_all_original_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = "a" * 40
            target = "b" * 40
            target_manifest = "d" * 64
            releases = root / "releases"
            releases.mkdir()
            (releases / source).mkdir()
            (releases / target).mkdir()
            link = root / "runtime-current"
            link.symlink_to(releases / source)

            compatibility = root / "operational-runtime-compatibility.json"
            manifest = build_runtime_compatibility_manifest(
                current_runtime_source_identity=source,
                releases_root=releases,
                components=[{
                    "component_id": "full-plan-reconcile",
                    "unit": "global-gpt-harness-full-plan-reconcile.service",
                    "binding_mode": "CURRENT_RUNTIME",
                    "expected_source_head": source,
                    "compatibility_evidence_refs": [],
                }],
            )
            record_runtime_compatibility_manifest(compatibility, manifest)

            identity_files = []
            for name in ("acceptance.service", "dashboard.service", "attention.service"):
                path = root / name
                path.write_text(f"RUNTIME={source}\n", encoding="utf-8")
                identity_files.append(path)
            originals = {
                compatibility: compatibility.read_bytes(),
                **{path: path.read_bytes() for path in identity_files},
            }

            reload_calls = {"count": 0}
            def daemon_reload():
                reload_calls["count"] += 1
                if reload_calls["count"] == 1:
                    raise RuntimeError("simulated daemon-reload failure")

            config = ProductionControlServerConfig(
                harness_state_root=root / "state",
                releases_root=releases,
                runtime_link=link,
                runtime_compatibility_manifest=compatibility,
                operational_identity_files=tuple(identity_files),
                job_search_root=root / "state",
            )
            config.harness_state_root.mkdir()
            backend = CanonicalProductionControlBackend(
                config, daemon_reload=daemon_reload
            )
            backend._release = lambda head: SimpleNamespace(
                manifest_sha256=target_manifest
            )
            request = self._request(
                action=SYNC_OPERATIONAL_RUNTIME_IDENTITY,
                source=source,
                target=target,
                target_manifest=target_manifest,
                parameters={
                    "predecessor_runtime_source_head": source,
                    "target_runtime_source_head": target,
                },
            )
            outcome = backend._sync_runtime_identity(request)
            self.assertEqual(outcome.status, "ROLLED_BACK")
            self.assertEqual(
                outcome.result_class,
                "OPERATIONAL_RUNTIME_IDENTITY_ROLLED_BACK",
            )
            self.assertTrue(outcome.effect["rollback_verified"])
            self.assertEqual(reload_calls["count"], 2)
            for path, raw in originals.items():
                self.assertEqual(path.read_bytes(), raw)


class ProductionControlP4LineageTests(unittest.TestCase):
    def test_p4_lineage_drift_blocks_before_cutover_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state"
            lifecycle_state = root / "lifecycle-state"
            releases = root / "releases"
            state.mkdir()
            lifecycle_state.mkdir()
            releases.mkdir()
            link = root / "runtime-current"
            manifest = root / "compat.json"
            manifest.write_text("{}", encoding="utf-8")
            admission = "1" * 64
            qualification = "2" * 64
            entry = "3" * 64
            cutover = "4" * 64
            source = "a" * 40
            target = "b" * 40
            target_manifest = "5" * 64
            for directory, value in (
                ("p3-final-qualifications", {
                    "qualification_digest": "9" * 64,
                }),
                ("p4-read-only-entries", {
                    "entry_digest": entry,
                    "qualification_digest": qualification,
                    "status": "P4_READ_ONLY_ENTERED",
                }),
                ("p4-cutover-admissions", {
                    "admission_digest": admission,
                    "qualification_digest": qualification,
                    "p4_entry_digest": entry,
                    "cutover_admission_digest": cutover,
                    "status": "P4_CUTOVER_READY",
                    "runtime_current_switch_authorized": True,
                    "source_head": source,
                    "target_head": target,
                    "target_manifest_sha256": target_manifest,
                }),
            ):
                path = lifecycle_state / directory / f"{admission}.json"
                path.parent.mkdir(parents=True)
                path.write_bytes(_canonical(value))
            request = ProductionControlActionRequestV1.from_mapping({
                "schema_version": PRODUCTION_CONTROL_ACTION_SCHEMA_V1,
                "request_id": "P4-REQ-1",
                "project_id": "global-gpt-harness",
                "action": P4_CUTOVER,
                "approval_ref": "OCP-FULL-PLAN-TEST-1",
                "activation_id": "ACT-1",
                "plan_digest": "6" * 64,
                "approval_proof_path": "_workspace/full-plan-human-approvals/ACT-1.json",
                "approval_proof_sha256": "7" * 64,
                "expected_state_sha256": "8" * 64,
                "expected_runtime_source_head": source,
                "target_runtime_source_head": target,
                "target_runtime_manifest_sha256": target_manifest,
                "idempotency_key": "P4-IDEMP-1",
                "parameters": {
                    "admission_digest": admission,
                    "qualification_digest": qualification,
                    "p4_entry_digest": entry,
                    "cutover_admission_digest": cutover,
                },
            })
            backend = CanonicalProductionControlBackend(
                ProductionControlServerConfig(
                    harness_state_root=state,
                    lifecycle_state_root=lifecycle_state,
                    releases_root=releases,
                    runtime_link=link,
                    runtime_compatibility_manifest=manifest,
                )
            )
            backend._release = lambda head: SimpleNamespace(
                release_path=releases / head,
                manifest_sha256=target_manifest if head == target else "0" * 64,
            )
            with patch(
                "runtime.orchestrator.production_control_action.execute_p4_cutover"
            ) as execute:
                with self.assertRaisesRegex(
                    ProductionControlActionError, "P4 lineage binding mismatch"
                ):
                    backend._p4_cutover(request)
                execute.assert_not_called()

    def test_p4_execution_rechecks_current_cutover_blockers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state"
            lifecycle_state = root / "lifecycle-state"
            releases = root / "releases"
            state.mkdir()
            lifecycle_state.mkdir()
            releases.mkdir()
            link = root / "runtime-current"
            manifest = root / "compat.json"
            manifest.write_text("{}", encoding="utf-8")
            admission = "1" * 64
            qualification = "2" * 64
            entry = "3" * 64
            cutover = "4" * 64
            source = "a" * 40
            target = "b" * 40
            target_manifest = "5" * 64
            for directory, value in (
                ("p3-final-qualifications", {"qualification_digest": qualification}),
                ("p4-read-only-entries", {
                    "entry_digest": entry,
                    "qualification_digest": qualification,
                    "status": "P4_READ_ONLY_ENTERED",
                }),
                ("p4-cutover-admissions", {
                    "admission_digest": admission,
                    "qualification_digest": qualification,
                    "p4_entry_digest": entry,
                    "cutover_admission_digest": cutover,
                    "status": "P4_CUTOVER_READY",
                    "runtime_current_switch_authorized": True,
                    "source_head": source,
                    "target_head": target,
                    "target_manifest_sha256": target_manifest,
                }),
            ):
                path = lifecycle_state / directory / f"{admission}.json"
                path.parent.mkdir(parents=True)
                path.write_bytes(_canonical(value))
            request = ProductionControlActionRequestV1.from_mapping({
                "schema_version": PRODUCTION_CONTROL_ACTION_SCHEMA_V1,
                "request_id": "P4-REQ-STALE",
                "project_id": "global-gpt-harness",
                "action": P4_CUTOVER,
                "approval_ref": "OCP-FULL-PLAN-TEST-1",
                "activation_id": "ACT-1",
                "plan_digest": "6" * 64,
                "approval_proof_path": "_workspace/full-plan-human-approvals/ACT-1.json",
                "approval_proof_sha256": "7" * 64,
                "expected_state_sha256": "8" * 64,
                "expected_runtime_source_head": source,
                "target_runtime_source_head": target,
                "target_runtime_manifest_sha256": target_manifest,
                "idempotency_key": "P4-IDEMP-STALE",
                "parameters": {
                    "admission_digest": admission,
                    "qualification_digest": qualification,
                    "p4_entry_digest": entry,
                    "cutover_admission_digest": cutover,
                },
            })
            backend = CanonicalProductionControlBackend(
                ProductionControlServerConfig(
                    harness_state_root=state,
                    lifecycle_state_root=lifecycle_state,
                    releases_root=releases,
                    runtime_link=link,
                    runtime_compatibility_manifest=manifest,
                )
            )
            backend._release = lambda head: SimpleNamespace(
                release_path=releases / head,
                manifest_sha256=target_manifest if head == target else "0" * 64,
            )
            stale = {
                "status": "P4_CUTOVER_BLOCKED",
                "runtime_current_switch_authorized": False,
                "cutover_admission_digest": "9" * 64,
            }
            with patch(
                "runtime.orchestrator.production_control_action.prepare_p4_cutover",
                return_value=stale,
            ), patch(
                "runtime.orchestrator.production_control_action.execute_p4_cutover"
            ) as execute:
                with self.assertRaisesRegex(
                    ProductionControlActionError, "P4 cutover admission became stale"
                ):
                    backend._p4_cutover(request)
                execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
