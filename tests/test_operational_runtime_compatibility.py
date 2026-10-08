from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from runtime.orchestrator.operational_runtime_compatibility import (
    OperationalRuntimeCompatibilityError,
    build_runtime_compatibility_manifest,
    evaluate_runtime_compatibility,
    validate_runtime_compatibility_manifest,
)


CURRENT = "a" * 40
PINNED = "b" * 40


def _root(tmp_path: Path) -> Path:
    releases = tmp_path / "releases"
    (releases / CURRENT).mkdir(parents=True)
    (releases / PINNED).mkdir()
    return releases


def _manifest(tmp_path: Path):
    releases = _root(tmp_path)
    return build_runtime_compatibility_manifest(
        current_runtime_source_identity=CURRENT,
        releases_root=releases,
        components=[
            {
                "component_id": "reconcile",
                "unit": "global-gpt-harness-full-plan-reconcile.service",
                "binding_mode": "CURRENT_RUNTIME",
                "expected_source_head": CURRENT,
                "compatibility_evidence_refs": [],
            },
            {
                "component_id": "timer-recovery",
                "unit": "global-gpt-harness-operations-timer-recovery.service",
                "binding_mode": "PINNED_COMPATIBLE",
                "expected_source_head": PINNED,
                "compatibility_evidence_refs": ["qualification:timer-recovery-v1"],
            },
        ],
    )


class OperationalRuntimeCompatibilityTests(unittest.TestCase):
    def test_manifest_and_observed_bindings_pass(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            manifest = _manifest(tmp_path)
            releases = Path(manifest["releases_root"])
            result = evaluate_runtime_compatibility(
                manifest,
                observed_working_directories={
                    "global-gpt-harness-full-plan-reconcile.service": releases / CURRENT,
                    "global-gpt-harness-operations-timer-recovery.service": releases / PINNED,
                },
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["failures"], [])
            self.assertEqual(len(result["result_sha256"]), 64)

    def test_current_binding_can_resolve_runtime_current_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            manifest = _manifest(tmp_path)
            releases = Path(manifest["releases_root"])
            runtime_current = tmp_path / "runtime-current"
            runtime_current.symlink_to(releases / CURRENT, target_is_directory=True)
            result = evaluate_runtime_compatibility(
                manifest,
                observed_working_directories={
                    "global-gpt-harness-full-plan-reconcile.service": runtime_current,
                    "global-gpt-harness-operations-timer-recovery.service": releases / PINNED,
                },
            )
            self.assertEqual(result["status"], "PASS")

    def test_source_head_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            manifest = _manifest(tmp_path)
            releases = Path(manifest["releases_root"])
            result = evaluate_runtime_compatibility(
                manifest,
                observed_working_directories={
                    "global-gpt-harness-full-plan-reconcile.service": releases / PINNED,
                    "global-gpt-harness-operations-timer-recovery.service": releases / PINNED,
                },
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("reconcile:SOURCE_HEAD_MISMATCH", result["failures"])

    def test_non_release_working_directory_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            manifest = _manifest(tmp_path)
            outside = tmp_path / "worktree"
            outside.mkdir()
            releases = Path(manifest["releases_root"])
            result = evaluate_runtime_compatibility(
                manifest,
                observed_working_directories={
                    "global-gpt-harness-full-plan-reconcile.service": outside,
                    "global-gpt-harness-operations-timer-recovery.service": releases / PINNED,
                },
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("reconcile:RELEASE_PATH_INVALID", result["failures"])

    def test_pinned_component_requires_compatibility_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            releases = _root(tmp_path)
            with self.assertRaisesRegex(
                OperationalRuntimeCompatibilityError,
                "pinned component requires compatibility evidence",
            ):
                build_runtime_compatibility_manifest(
                    current_runtime_source_identity=CURRENT,
                    releases_root=releases,
                    components=[{
                        "component_id": "ocp",
                        "unit": "ocpv2.service",
                        "binding_mode": "PINNED_COMPATIBLE",
                        "expected_source_head": PINNED,
                        "compatibility_evidence_refs": [],
                    }],
                )

    def test_manifest_digest_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            manifest = _manifest(tmp_path)
            manifest["components"][0]["expected_source_head"] = PINNED
            with self.assertRaisesRegex(
                OperationalRuntimeCompatibilityError,
                "component binding invalid|manifest digest mismatch",
            ):
                validate_runtime_compatibility_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
