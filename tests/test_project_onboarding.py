from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.project_onboarding import OnboardingRegistry, ProjectOnboardingError


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


if __name__ == "__main__":
    unittest.main()
