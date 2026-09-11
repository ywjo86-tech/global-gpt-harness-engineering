from __future__ import annotations

import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.fixed_runner import (
    COMMAND_REGISTRY, FixedRunnerError, RegisteredCommand, registry_sha256,
    run_sealed_action, seal_action_manifest, validate_action_manifest,
)
from runtime.orchestrator.lv_execution_package import canonical_json_bytes


SHA = "a" * 64
INPUT_SHA = "b" * 64
HEAD = "c" * 40


class FixedRunnerTests(unittest.TestCase):
    def manifest(self, **changes):
        values = dict(requirements_sha256=SHA, project_id="wallet-affiliate-collector", gate_id="GATE-1",
                      lv_id="G1-LV3-2", run_id="run-1", branch="main", head=HEAD,
                      owned_files=["app/model.py"], command_id="lv.package", input_sha256=INPUT_SHA)
        values.update(changes)
        return seal_action_manifest(**values)

    def test_registered_action_uses_fixed_argv_and_shell_false_and_audits(self):
        seen = {}
        def executor(argv, **kwargs):
            seen.update(argv=argv, kwargs=kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout=b"ok", stderr=b"")
        with tempfile.TemporaryDirectory() as temp:
            audit = Path(temp) / "audit.jsonl"
            result = run_sealed_action(self.manifest(), expected_project_id="wallet-affiliate-collector",
                                       expected_requirements_sha256=SHA, audit_path=audit, executor=executor)
            self.assertEqual(seen["argv"], list(COMMAND_REGISTRY["lv.package"].argv))
            self.assertIs(seen["kwargs"]["shell"], False)
            self.assertEqual(result["exit_code"], 0)
            entry = json.loads(audit.read_text().strip())
            self.assertEqual(entry["command_id"], "lv.package")
            self.assertEqual(entry["input_sha256"], INPUT_SHA)
            self.assertEqual(len(entry["artifact_sha256"]), 64)

    def test_audit_is_append_only(self):
        def executor(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 7, stdout=b"", stderr=b"blocked")
        with tempfile.TemporaryDirectory() as temp:
            audit = Path(temp) / "audit.jsonl"
            for _ in range(2):
                run_sealed_action(self.manifest(), expected_project_id="wallet-affiliate-collector",
                                  expected_requirements_sha256=SHA, audit_path=audit, executor=executor)
            self.assertEqual(len(audit.read_text().splitlines()), 2)

    def test_unregistered_command_is_blocked(self):
        with self.assertRaises(FixedRunnerError): self.manifest(command_id="git.push")

    def test_arbitrary_argument_has_no_manifest_surface(self):
        manifest = self.manifest(); manifest["payload"]["arguments"] = ["--evil"]
        manifest["manifest_sha256"] = hashlib.sha256(canonical_json_bytes(manifest["payload"])).hexdigest()
        with self.assertRaises(FixedRunnerError):
            validate_action_manifest(manifest, expected_project_id="wallet-affiliate-collector", expected_requirements_sha256=SHA)

    def test_shell_metacharacters_are_blocked(self):
        for value in ("run;rm", "run|curl", "$(id)", "x\nnext"):
            with self.subTest(value=value), self.assertRaises(FixedRunnerError): self.manifest(run_id=value)

    def test_owned_traversal_and_absolute_paths_are_blocked(self):
        for value in ("../other/file", "/etc/passwd", "app/x;rm"):
            with self.subTest(value=value), self.assertRaises(FixedRunnerError): self.manifest(owned_files=[value])

    def test_manifest_and_requirements_drift_are_blocked(self):
        manifest = self.manifest(); manifest["payload"]["head"] = "d" * 40
        with self.assertRaisesRegex(FixedRunnerError, "manifest drift"):
            validate_action_manifest(manifest, expected_project_id="wallet-affiliate-collector", expected_requirements_sha256=SHA)
        with self.assertRaisesRegex(FixedRunnerError, "requirements SHA drift"):
            validate_action_manifest(self.manifest(), expected_project_id="wallet-affiliate-collector", expected_requirements_sha256="e" * 64)

    def test_cross_project_manifest_is_blocked(self):
        with self.assertRaisesRegex(FixedRunnerError, "cross-project"):
            validate_action_manifest(self.manifest(), expected_project_id="other-project", expected_requirements_sha256=SHA)

    def test_registry_drift_is_blocked(self):
        manifest = self.manifest()
        changed = dict(COMMAND_REGISTRY)
        changed["lv.package"] = RegisteredCommand("lv.package", ("python3", "-V"), "PACKAGE")
        self.assertNotEqual(registry_sha256(), registry_sha256(changed))
        with self.assertRaisesRegex(FixedRunnerError, "registry drift"):
            validate_action_manifest(manifest, expected_project_id="wallet-affiliate-collector",
                                     expected_requirements_sha256=SHA, registry=changed)

    def test_forbidden_registry_actions_are_blocked_without_execution(self):
        for argv in (("git", "push"), ("rm", "file"), ("curl", "example"), ("pip", "install", "x")):
            registry = {"bad": RegisteredCommand("bad", argv, "WORKER")}
            with self.subTest(argv=argv), self.assertRaises(FixedRunnerError):
                seal_action_manifest(requirements_sha256=SHA, project_id="project", gate_id="GATE-1",
                                     lv_id="G1-LV3-1", run_id="run", branch="main", head=HEAD,
                                     owned_files=["x.py"], command_id="bad", input_sha256=INPUT_SHA,
                                     registry=registry)

    def test_worker_registered_template_binds_typed_request_and_result_paths(self):
        seen = {}
        def executor(argv, **kwargs):
            seen.update(argv=argv, kwargs=kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = root / "request.json"
            result = root / "result.json"
            manifest = self.manifest(command_id="lv.worker", parameters={
                "request_file": str(request), "result_file": str(result)})
            run_sealed_action(manifest, expected_project_id="wallet-affiliate-collector",
                              expected_requirements_sha256=SHA, audit_path=root / "audit.jsonl",
                              execution_root=root, executor=executor)
            self.assertEqual(seen["argv"][-4:], ["--request-file", str(request), "--result-file", str(result)])
            self.assertFalse(seen["kwargs"]["shell"])

    def test_worker_unknown_or_unsafe_parameter_is_blocked(self):
        for params in (
            {"request_file": "/tmp/request", "result_file": "/tmp/result", "evil": "x"},
            {"request_file": "/tmp/../request", "result_file": "/tmp/result"},
        ):
            with self.subTest(params=params), self.assertRaises(FixedRunnerError):
                self.manifest(command_id="lv.worker", parameters=params)

    def test_worker_path_symlink_and_outside_root_are_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); outside = root.parent / (root.name + "-outside")
            outside.mkdir()
            request = root / "request.json"; result = root / "result.json"
            request.write_text("{}")
            result.symlink_to(outside / "result.json")
            manifest = self.manifest(command_id="lv.worker", parameters={
                "request_file": str(request), "result_file": str(result)})
            with self.assertRaisesRegex(FixedRunnerError, "symlink"):
                run_sealed_action(manifest, expected_project_id="wallet-affiliate-collector",
                                  expected_requirements_sha256=SHA, audit_path=root / "audit.jsonl",
                                  execution_root=root, executor=lambda *a, **k: None)


if __name__ == "__main__":
    unittest.main()
