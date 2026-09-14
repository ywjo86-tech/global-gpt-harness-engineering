from __future__ import annotations

import unittest

from runtime.orchestrator.provider_router import route_provider


class ProviderRouterTest(unittest.TestCase):
    def test_hybrid_routes_read_only_to_nvidia(self) -> None:
        decision = route_provider("hybrid", ["reasoning", "read_only"])
        self.assertEqual(decision.provider, "nvidia")
        self.assertEqual(decision.reason_code, "hybrid_read_only_to_nvidia")

    def test_hybrid_routes_state_changing_to_codex(self) -> None:
        decision = route_provider("hybrid", ["reasoning", "filesystem_write"])
        self.assertEqual(decision.provider, "codex")
        self.assertEqual(decision.reason_code, "hybrid_state_changing_to_codex")

    def test_nvidia_rejects_state_changing(self) -> None:
        decision = route_provider("nvidia", ["reasoning", "shell"])
        self.assertEqual(decision.provider, "manual")
        self.assertFalse(decision.eligible)


if __name__ == "__main__":
    unittest.main()
