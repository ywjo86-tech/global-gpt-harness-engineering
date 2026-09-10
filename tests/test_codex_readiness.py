from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.codex_readiness import (
    NOT_READY,
    CodexReadinessError,
    ReadinessProbeSet,
    collect_codex_auth_readiness,
    probe_codex_auth_status,
    probe_secret_free_environment_fingerprint,
    recheck_codex_auth_readiness,
)
from runtime.orchestrator.execution_contract import (
    ALWAYS_BEFORE_CODEX_LAUNCH,
    READY,
    codex_launch_binding_digest,
)

SCHEMA = "a" * 64
ENV = "b" * 64


def probes(*, version="0.150.1", schema=SCHEMA, env=ENV, auth=READY, schema_verified=True):
    return ReadinessProbeSet(
        version_probe=lambda: version,
        schema_probe=lambda: (
            {
                "experimental_api": schema_verified,
                "dynamic_tool_request": schema_verified,
                "dynamic_tool_response": schema_verified,
                "empty_environment_supported": schema_verified,
                "schema_verified": schema_verified,
            },
            schema,
        ),
        environment_probe=lambda: env,
        auth_probe=lambda: auth,
    )


class CodexReadinessTests(unittest.TestCase):
    def test_collects_ready_evidence_with_exact_launch_binding(self):
        evidence = collect_codex_auth_readiness(
            run_id="run-1",
            worker_task_id="TASK-4A-08",
            package_id="PKG-1",
            package_revision=1,
            probes=probes(),
            verified_at_utc="2026-09-09T15:00:00Z",
        )
        self.assertEqual(evidence.auth_status, READY)
        self.assertEqual(evidence.recheck_policy, ALWAYS_BEFORE_CODEX_LAUNCH)
        self.assertEqual(
            evidence.launch_binding_digest,
            codex_launch_binding_digest(
                cli_version="0.150.1",
                environment_fingerprint=ENV,
                transport_schema_digest=SCHEMA,
                run_id="run-1",
                worker_task_id="TASK-4A-08",
                package_id="PKG-1",
                package_revision=1,
            ),
        )
        self.assertNotIn(
            "Logged in using ChatGPT",
            "\n".join(evidence.source_evidence_refs),
        )

    def test_auth_not_ready_is_bounded_and_does_not_become_ready(self):
        evidence = collect_codex_auth_readiness(
            run_id="run-1",
            worker_task_id="TASK-4A-08",
            package_id="PKG-1",
            package_revision=1,
            probes=probes(auth=NOT_READY),
            verified_at_utc="2026-09-09T15:00:00Z",
        )
        self.assertEqual(evidence.auth_status, NOT_READY)

    def test_cli_version_drift_fails_closed(self):
        with self.assertRaises(CodexReadinessError) as caught:
            collect_codex_auth_readiness(
                run_id="run-1",
                worker_task_id="TASK-4A-08",
                package_id="PKG-1",
                package_revision=1,
                probes=probes(version="0.150.2"),
                verified_at_utc="2026-09-09T15:00:00Z",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CODEX_CLI_VERSION_DRIFT")

    def test_schema_compatibility_failure_fails_closed(self):
        with self.assertRaises(CodexReadinessError) as caught:
            collect_codex_auth_readiness(
                run_id="run-1",
                worker_task_id="TASK-4A-08",
                package_id="PKG-1",
                package_revision=1,
                probes=probes(schema_verified=False),
                verified_at_utc="2026-09-09T15:00:00Z",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CODEX_SCHEMA_COMPATIBILITY_BLOCK")

    def test_package_revision_changes_launch_binding(self):
        first = collect_codex_auth_readiness(
            run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
            package_revision=1, probes=probes(), verified_at_utc="2026-09-09T15:00:00Z",
        )
        second = collect_codex_auth_readiness(
            run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
            package_revision=2, probes=probes(), verified_at_utc="2026-09-09T15:00:01Z",
        )
        self.assertNotEqual(first.launch_binding_digest, second.launch_binding_digest)

    def test_launch_adjacent_recheck_accepts_same_stable_facts(self):
        expected = collect_codex_auth_readiness(
            run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
            package_revision=1, probes=probes(), verified_at_utc="2026-09-09T15:00:00Z",
        )
        current = recheck_codex_auth_readiness(
            expected,
            run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
            package_revision=1, probes=probes(), verified_at_utc="2026-09-09T15:00:05Z",
        )
        self.assertEqual(current.launch_binding_digest, expected.launch_binding_digest)
        self.assertNotEqual(current.evidence_id, expected.evidence_id)

    def test_launch_adjacent_environment_drift_fails_closed(self):
        expected = collect_codex_auth_readiness(
            run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
            package_revision=1, probes=probes(), verified_at_utc="2026-09-09T15:00:00Z",
        )
        with self.assertRaises(CodexReadinessError) as caught:
            recheck_codex_auth_readiness(
                expected,
                run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
                package_revision=1, probes=probes(env="c" * 64),
                verified_at_utc="2026-09-09T15:00:05Z",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CODEX_READINESS_STALE_OR_DRIFTED")

    def test_launch_adjacent_schema_drift_fails_closed(self):
        expected = collect_codex_auth_readiness(
            run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
            package_revision=1, probes=probes(), verified_at_utc="2026-09-09T15:00:00Z",
        )
        with self.assertRaises(CodexReadinessError) as caught:
            recheck_codex_auth_readiness(
                expected,
                run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
                package_revision=1, probes=probes(schema="d" * 64),
                verified_at_utc="2026-09-09T15:00:05Z",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CODEX_READINESS_STALE_OR_DRIFTED")

    def test_launch_adjacent_auth_loss_fails_closed(self):
        expected = collect_codex_auth_readiness(
            run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
            package_revision=1, probes=probes(), verified_at_utc="2026-09-09T15:00:00Z",
        )
        with self.assertRaises(CodexReadinessError) as caught:
            recheck_codex_auth_readiness(
                expected,
                run_id="run-1", worker_task_id="TASK-4A-08", package_id="PKG-1",
                package_revision=1, probes=probes(auth=NOT_READY),
                verified_at_utc="2026-09-09T15:00:05Z",
            )
        self.assertEqual(caught.exception.reason_taxonomy, "CODEX_AUTH_NOT_READY")

    def test_login_status_probe_never_returns_raw_login_text(self):
        class Result:
            returncode = 0
            stdout = "Logged in using ChatGPT\n"
            stderr = ""
        self.assertEqual(
            probe_codex_auth_status(runner=lambda *a, **k: Result()),
            READY,
        )

    def test_secret_free_environment_fingerprint_is_deterministic_and_not_raw_path(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "codex"
            binary.write_bytes(b"fake-codex-binary")
            first = probe_secret_free_environment_fingerprint(which=lambda _name: str(binary))
            second = probe_secret_free_environment_fingerprint(which=lambda _name: str(binary))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotIn(str(binary), first)


if __name__ == "__main__":
    unittest.main()
