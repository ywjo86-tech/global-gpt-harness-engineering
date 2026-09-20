from __future__ import annotations

import json
import unittest

from runtime.orchestrator.omniroute_adapter import (
    OmniRouteAdapterError,
    make_omniroute_runner,
    normalize_omniroute_result,
    run_omniroute_provider,
    validate_target_binding,
)
from runtime.orchestrator.provider_adapter_registry import build_active_provider_adapter_registry
from runtime.orchestrator.provider_candidate_inventory import (
    PROVIDER_CANDIDATE_SCHEMA_V1, ProviderCandidateInventoryV1, ProviderCandidateRecordV1,
)
from runtime.orchestrator.provider_execution_registry import build_active_provider_runner_registry


class _Response:
    def __init__(self, *, provider="provider-x", model="provider-x/model-1", fallback="0", content="ok"):
        self.headers = {
            "X-OmniRoute-Provider": provider,
            "X-OmniRoute-Model": model,
            "X-OmniRoute-Fallback-Attempts": fallback,
        }
        self._body = json.dumps({"choices": [{"message": {"content": content}}], "model": model}).encode()
    def read(self): return self._body
    def __enter__(self): return self
    def __exit__(self, *args): return False


def _record(state: str) -> ProviderCandidateRecordV1:
    active = state == "ACTIVE"
    return ProviderCandidateRecordV1(
        PROVIDER_CANDIDATE_SCHEMA_V1, "provider-x", "openai-compatible", state,
        ("provider-x/model-1",), False, "free", ("reasoning", "read_only"),
        ("read-pass",) if active else (), "action-pass" if active else "",
        "reroute-pass" if active else "", "approval-pass" if active else "", connection_id="conn-x",
    )


class OmniRouteAdapterTests(unittest.TestCase):
    def test_adapter_sends_explicit_selected_model_and_connection(self) -> None:
        sent = {}
        def opener(req, timeout=None):
            sent.update(json.loads(req.data.decode()))
            sent["headers"] = {k.lower(): v for k, v in req.header_items()}
            return _Response()
        result = run_omniroute_provider(
            prompt="x", provider="provider-x", model="provider-x/model-1",
            connection_id="conn-x", api_key="a" * 32, opener=opener,
        )
        self.assertEqual(sent["model"], "provider-x/model-1")
        self.assertEqual(sent["headers"]["x-omniroute-connection"], "conn-x")
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("a" * 32, json.dumps(result))

    def test_target_binding_rejects_provider_model_or_fallback_mismatch(self) -> None:
        for headers in (
            {"X-OmniRoute-Provider": "other", "X-OmniRoute-Model": "provider-x/model-1", "X-OmniRoute-Fallback-Attempts": "0"},
            {"X-OmniRoute-Provider": "provider-x", "X-OmniRoute-Model": "other", "X-OmniRoute-Fallback-Attempts": "0"},
            {"X-OmniRoute-Provider": "provider-x", "X-OmniRoute-Model": "provider-x/model-1", "X-OmniRoute-Fallback-Attempts": "1"},
        ):
            with self.subTest(headers=headers), self.assertRaisesRegex(OmniRouteAdapterError, "target binding"):
                validate_target_binding(headers, expected_provider="provider-x", expected_model="provider-x/model-1")

    def test_normalizer_rejects_different_provider(self) -> None:
        raw = {"headers": _Response(provider="other").headers, "payload": {"choices": [{"message": {"content": "x"}}]}}
        with self.assertRaisesRegex(OmniRouteAdapterError, "target binding"):
            normalize_omniroute_result(expected_provider="provider-x", expected_model="provider-x/model-1", raw=raw)

    def test_auto_and_nested_fallback_are_forbidden_before_transport(self) -> None:
        def opener(*args, **kwargs): raise AssertionError("transport must not run")
        for model, fallbacks in (("auto", ()), ("provider-x/model-1", ("other",))):
            with self.subTest(model=model), self.assertRaises(OmniRouteAdapterError):
                run_omniroute_provider(prompt="x", provider="provider-x", model=model, fallback_models=fallbacks, api_key="a"*32, opener=opener)

    def test_registry_factories_register_active_records_only(self) -> None:
        active = ProviderCandidateInventoryV1((_record("ACTIVE"),))
        discovered = ProviderCandidateInventoryV1((_record("DISCOVERED"),))
        adapter_factory = lambda record: (lambda task, decision, root: {"provider": record.provider_id})
        runner_factory = lambda record: (lambda **kwargs: {"provider": record.provider_id})
        self.assertEqual(build_active_provider_adapter_registry(active, adapter_factory).provider_ids, ("provider-x",))
        self.assertEqual(build_active_provider_adapter_registry(discovered, adapter_factory).provider_ids, ())
        self.assertIsNotNone(build_active_provider_runner_registry(active, runner_factory).resolve_read("provider-x"))
        self.assertIsNone(build_active_provider_runner_registry(discovered, runner_factory).resolve_read("provider-x"))

    def test_bound_runner_rejects_router_model_drift(self) -> None:
        runner = make_omniroute_runner(_record("ACTIVE"), api_key="a"*32, opener=lambda *a, **k: _Response())
        result = runner(prompt="x", project_root=".", input_files=[], model="other/model", require_explicit_model=True, fallback_models=())
        self.assertEqual(result["status"], "provider_failed")
        self.assertEqual(result["provider_error_class"], "omniroute_target_binding_error")


if __name__ == "__main__": unittest.main()
