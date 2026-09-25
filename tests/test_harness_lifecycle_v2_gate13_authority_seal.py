from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.production_run_authority import (
    RunAuthorityError,
    seal_authority_core,
    validate_authority_core,
)


class HarnessLifecycleV2Gate13AuthoritySealTest(unittest.TestCase):
    def _job(self, root: Path) -> dict:
        project = root / "project"
        runtime = root / "runtime"
        state = root / "state"
        project.mkdir()
        runtime.mkdir()
        state.mkdir()
        return {
            "schema_version": "orchestration.production-full-plan-job.v1",
            "project_root": str(project),
            "harness_root": str(runtime),
            "runtime_code_root": str(runtime),
            "harness_state_root": str(state),
            "project_id": "G13_PROJECT",
            "run_id": "G13-RUN",
            "executor_runtime_identity": {
                "schema_version": "orchestration.executor-runtime-identity.v1",
                "root": str(runtime.resolve()),
                "head": "",
                "branch": "",
                "git_common_dir": "",
                "runtime_source_sha256": "",
            },
            "gates": [
                {
                    "gate_id": "GATE-13",
                    "approval_evidence": "approval.json",
                    "requirements_sha256": "a" * 64,
                    "branch": "main",
                    "head": "b" * 40,
                    "full_plan_opt_in": True,
                    "project_final_validation": True,
                }
            ],
            "lifecycle_binding": {
                "schema_version": "orchestration.execution-lifecycle-binding.v2",
                "lifecycle_mode": "V2",
                "qualification_marker": "BOUND",
            },
            "execution_authority_bundle": {
                "schema_version": "orchestration.execution-authority-bundle.v2",
                "project_id": "G13_PROJECT",
                "run_id": "G13-RUN",
                "runtime_release_digest": "1" * 64,
            },
        }

    def test_v2_lifecycle_fields_are_covered_by_immutable_authority_core(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sealed = seal_authority_core(self._job(Path(directory)))
            self.assertRegex(validate_authority_core(sealed), r"^[0-9a-f]{64}$")

            lifecycle_tamper = copy.deepcopy(sealed)
            lifecycle_tamper["lifecycle_binding"]["qualification_marker"] = "TAMPERED"
            with self.assertRaisesRegex(RunAuthorityError, "RUN_AUTHORITY_DRIFT"):
                validate_authority_core(lifecycle_tamper)

            authority_tamper = copy.deepcopy(sealed)
            authority_tamper["execution_authority_bundle"]["runtime_release_digest"] = "2" * 64
            with self.assertRaisesRegex(RunAuthorityError, "RUN_AUTHORITY_DRIFT"):
                validate_authority_core(authority_tamper)

    def test_only_declared_runtime_gate_overlay_remains_outside_authority_core(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sealed = seal_authority_core(self._job(Path(directory)))
            runtime_overlay = copy.deepcopy(sealed)
            runtime_overlay["gates"][0]["manual_action_package_paths_by_lv"] = {
                "TASK-001": "/tmp/action.json"
            }
            runtime_overlay["gates"][0]["manual_action_authorization_paths_by_lv"] = {
                "TASK-001": "/tmp/auth.json"
            }
            self.assertEqual(validate_authority_core(runtime_overlay), sealed["authority_core_sha256"])


if __name__ == "__main__":
    unittest.main()
