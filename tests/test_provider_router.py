from __future__ import annotations

import unittest

from runtime.orchestrator.provider_router import route_provider


class ProviderRouterTest(unittest.TestCase):
    def test_explicit_codex_cli_routes_to_codex_for_read_only_and_state_changing(self) -> None:
        for capabilities in (["read_only", "reasoning"], ["implementation"], ["test", "git"]):
            with self.subTest(capabilities=capabilities):
                decision = route_provider("codex-cli", capabilities)
                self.assertEqual(decision.provider, "codex")
                self.assertEqual(decision.reason_code, "mode_codex_cli")
                self.assertTrue(decision.eligible)

    def test_manual_and_mock_modes_do_not_auto_route_to_codex(self) -> None:
        manual = route_provider("manual", ["implementation"])
        mock = route_provider("mock", ["implementation"])

        self.assertEqual(manual.provider, "manual")
        self.assertEqual(manual.reason_code, "mode_manual")
        self.assertTrue(manual.eligible)
        self.assertEqual(mock.provider, "local")
        self.assertEqual(mock.reason_code, "mode_mock_local")
        self.assertTrue(mock.eligible)

    def test_hybrid_routes_read_only_to_nvidia(self) -> None:
        decision = route_provider("hybrid", ["reasoning", "read_only"])
        self.assertEqual(decision.provider, "nvidia")
        self.assertEqual(decision.reason_code, "hybrid_read_only_to_nvidia")

    def test_hybrid_routes_state_changing_to_codex(self) -> None:
        for capability in ["filesystem_write", "shell", "test", "git", "implementation", "integration"]:
            with self.subTest(capability=capability):
                decision = route_provider("hybrid", ["reasoning", capability])
                self.assertEqual(decision.provider, "codex")
                self.assertEqual(decision.reason_code, "hybrid_state_changing_to_codex")

    def test_nvidia_rejects_state_changing(self) -> None:
        for capability in ["filesystem_write", "shell", "test", "git", "implementation", "integration"]:
            with self.subTest(capability=capability):
                decision = route_provider("nvidia", ["reasoning", capability])
                self.assertEqual(decision.provider, "manual")
                self.assertFalse(decision.eligible)

    def test_read_only_plus_integration_is_state_changing(self) -> None:
        hybrid = route_provider("hybrid", ["reasoning", "read_only", "integration"])
        nvidia = route_provider("nvidia", ["reasoning", "read_only", "integration"])

        self.assertEqual(hybrid.provider, "codex")
        self.assertEqual(hybrid.reason_code, "hybrid_state_changing_to_codex")
        self.assertEqual(nvidia.provider, "manual")
        self.assertFalse(nvidia.eligible)

    def test_capabilities_are_deduplicated_and_sorted_in_decision(self) -> None:
        decision = route_provider("hybrid", ["test", "read_only", "test", " reasoning ", ""])

        self.assertEqual(decision.provider, "codex")
        self.assertEqual(decision.required_capabilities, ("read_only", "reasoning", "test"))


if __name__ == "__main__":
    unittest.main()
