from __future__ import annotations

import unittest

from poc.graphify.comparator import query_with_fallback
from poc.graphify.contracts import ProviderQueryRequest, ProviderResult

SHA = "5" * 40


class _FailingGraphify:
    def query(self, request):
        raise RuntimeError("graph unavailable")


class _StaleGraphify:
    def query(self, request):
        return ProviderResult(
            "graphify", request.scenario_id, request.source_ref,
            "completed", "stale", freshness_state="STALE"
        )


class _Baseline:
    def query(self, request):
        return ProviderResult(
            "existing_inspection", request.scenario_id, request.source_ref,
            "completed", "fallback", confidence="CANONICAL"
        )


class GraphifyFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = ProviderQueryRequest("S1", "x", SHA)

    def test_error_falls_back(self) -> None:
        result, meta = query_with_fallback(_FailingGraphify(), _Baseline(), self.request)
        self.assertEqual(result.provider_id, "existing_inspection")
        self.assertTrue(meta["fallback_used"])

    def test_stale_result_falls_back(self) -> None:
        result, meta = query_with_fallback(_StaleGraphify(), _Baseline(), self.request)
        self.assertEqual(result.provider_id, "existing_inspection")
        self.assertTrue(meta["fallback_used"])


if __name__ == "__main__":
    unittest.main()
