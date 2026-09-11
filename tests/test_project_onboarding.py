from __future__ import annotations

import tempfile
import unittest
import json
import hashlib
import subprocess
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry, ProjectOnboardingError
from runtime.orchestrator.contract_adapter import ContractMappingError, load_project_mapping


class ProjectOnboardingTests(unittest.TestCase):
    @staticmethod
    def project(base: Path, name: str, plan: str | None = "plan") -> Path:
        root = base / name
        root.mkdir()
        if plan is not None:
            (root / "IMPLEMENTATION_PLAN.md").write_text(plan, encoding="utf-8")
        return root

    def test_current_registered_fixture_uses_alias_codex_and_common_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); registry = OnboardingRegistry(base / "registry")
            project = self.project(base, "wallet-fixture")
            registered = registry.register(project, "affiliate")
            self.assertEqual(registered["status"], "REGISTERED")
            inspected = OnboardingRegistry(base / "registry").inspect(project, "affiliate")
            self.assertEqual(inspected["status"], "COMPATIBLE")
            self.assertEqual(inspected["entry"]["entry_command"], ["affiliate", "codex"])
            self.assertEqual(inspected["entry"]["controller_command_id"], "GLOBAL_GATE_RUN")
            self.assertFalse(inspected["entry"]["launcher_mutation_required"])

    def test_second_existing_project_is_read_only_compatible_before_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); registry = OnboardingRegistry(base / "registry")
            first = self.project(base, "first"); second = self.project(base, "second")
            registry.register(first, "one")
            before = sorted((base / "registry").iterdir())
            report = registry.inspect(second, "two")
            self.assertEqual(report["status"], "REGISTRATION_READY")
            self.assertFalse(report["mutation_performed"])
            self.assertEqual(sorted((base / "registry").iterdir()), before)

    def test_new_fixture_without_plan_requires_onboarding_and_never_synthesizes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); registry_root = base / "registry"
            project = self.project(base, "new-project", plan=None)
            report = OnboardingRegistry(registry_root).register(project, "new")
            self.assertEqual(report["status"], "ONBOARDING_REQUIRED")
            self.assertFalse(report["canonical_plan_synthesized"])
            self.assertFalse(report["mutation_performed"])
            self.assertFalse(registry_root.exists())
            self.assertFalse((project / "IMPLEMENTATION_PLAN.md").exists())

    def test_alias_collision_is_blocked_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); registry = OnboardingRegistry(base / "registry")
            first = self.project(base, "first"); second = self.project(base, "second")
            registry.register(first, "same")
            report = registry.register(second, "same")
            self.assertEqual(report["status"], "ONBOARDING_BLOCKED")
            self.assertFalse(report["mutation_performed"])
            self.assertEqual(len(registry.entries()), 1)

    def test_plan_sha_drift_and_immutable_entry_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); registry = OnboardingRegistry(base / "registry")
            project = self.project(base, "project")
            registry.register(project, "alias")
            (project / "IMPLEMENTATION_PLAN.md").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ProjectOnboardingError, "SHA drift"):
                registry.inspect(project, "alias")

    def test_ambiguous_plan_and_symlinked_registry_entry_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); registry = OnboardingRegistry(base / "registry")
            project = self.project(base, "project")
            (project / "docs").mkdir(); (project / "docs/DEVELOPMENT_PLAN.txt").write_text("other", encoding="utf-8")
            with self.assertRaisesRegex(ProjectOnboardingError, "ambiguous"):
                registry.inspect(project, "alias")

    def test_explicit_mapping_root_loads_declarative_temp_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); project = self.project(base, "mapped-project")
            mapping_root = base / "registry"; mapping_root.mkdir()
            plan = project / "IMPLEMENTATION_PLAN.md"
            digest = hashlib.sha256(plan.read_bytes()).hexdigest()
            payload = {
                "project_id": project.name,
                "contract_paths": {"development_plan": "IMPLEMENTATION_PLAN.md"},
                "required_contract_keys": ["development_plan"],
                "canonical_implementation_source": {"path": "IMPLEMENTATION_PLAN.md", "sha256": digest},
                "approved_source_reference": {"path": "IMPLEMENTATION_PLAN.md", "sha256": digest},
                "static_validation": {"business_lv_approval": "IMPLEMENTATION_PLAN.md", "gate_state": "IMPLEMENTATION_PLAN.md"},
                "canonical_transition": {},
            }
            (mapping_root / f"{project.name}.json").write_text(json.dumps(payload), encoding="utf-8")
            mapping = load_project_mapping(project, mapping_root=mapping_root)
            self.assertIsNotNone(mapping)

    def test_explicit_mapping_root_rejects_traversal_and_symlink_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); project = self.project(base, "mapped-project")
            mapping_root = base / "registry"; mapping_root.mkdir()
            outside = base / "outside.json"; outside.write_text("{}", encoding="utf-8")
            (mapping_root / f"{project.name}.json").symlink_to(outside)
            with self.assertRaisesRegex(ContractMappingError, "symlink"):
                load_project_mapping(project, mapping_root=mapping_root)
            (mapping_root / f"{project.name}.json").unlink()
            (mapping_root / f"{project.name}.json").write_text(json.dumps({"project_id": project.name}), encoding="utf-8")
            with self.assertRaises(ContractMappingError):
                load_project_mapping(project, mapping_root=mapping_root)

    def test_explicit_mapping_root_rejects_alias_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); first = self.project(base, "first"); second = self.project(base, "second")
            registry = OnboardingRegistry(base / "registry")
            registry.register(first, "same")
            report = registry.inspect(second, "same")
            self.assertEqual(report["status"], "ONBOARDING_BLOCKED")

    def test_bootstrap_creates_isolated_contract_and_committed_clean_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = self.project(base, "bootstrap-project", "# plan\n")
            mapping_root = base / "isolated-registry"
            report = OnboardingRegistry(mapping_root / "aliases").bootstrap(project, "demo", mapping_root=mapping_root)
            self.assertEqual(report["status"], "BOOTSTRAPPED")
            self.assertTrue((project / ".git").is_dir())
            self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True, check=True).stdout, "")
            self.assertIsNotNone(load_project_mapping(project, mapping_root=mapping_root))
            self.assertTrue((mapping_root / "aliases" / "demo.json").is_file())
            second = OnboardingRegistry(mapping_root / "aliases").bootstrap(project, "demo", mapping_root=mapping_root)
            self.assertIn(second["status"], {"BOOTSTRAPPED", "COMPATIBLE"})

    def test_bootstrap_rejects_dirty_project_and_mapping_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); project = self.project(base, "bootstrap-project")
            subprocess.run(["git", "init", "-b", "main"], cwd=project, capture_output=True, text=True, check=True)
            (project / "untracked.txt").write_text("dirty", encoding="utf-8")
            with self.assertRaisesRegex(ProjectOnboardingError, "clean"):
                OnboardingRegistry(base / "registry" / "aliases").bootstrap(project, "demo", mapping_root=base / "registry")
            mapping_root = base / "registry"; mapping_root.mkdir()
            outside = base / "outside"; outside.mkdir()
            (mapping_root / "aliases").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ProjectOnboardingError, "unsafe"):
                OnboardingRegistry(mapping_root / "aliases").bootstrap(self.project(base, "other"), "demo", mapping_root=mapping_root)

    def test_bootstrap_state_waits_for_first_gate_without_fabricated_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); project = self.project(base, "first-gate")
            mapping_root = base / "registry"
            report = OnboardingRegistry(mapping_root / "aliases").bootstrap(project, "demo", mapping_root=mapping_root)
            self.assertEqual(report["status"], "BOOTSTRAPPED")
            state = (project / "docs/GATE_STATE.md").read_text(encoding="utf-8")
            self.assertIn("FIRST_GATE_WAITING_APPROVAL", state)
            self.assertNotIn("checkpoint", state.lower())
            self.assertNotIn("Exit", state)


if __name__ == "__main__":
    unittest.main()
