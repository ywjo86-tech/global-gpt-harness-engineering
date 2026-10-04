from __future__ import annotations

import ast
import inspect
import unittest

import runtime.ai_office.public_runtime as public_runtime
from runtime.ai_office.public_runtime import (
    AIOfficePublicRuntimeError,
    AIOfficePublicRuntimeFacade,
    AIOfficePublicRuntimeHandlersV1,
    compose_public_runtime_facade,
)


class AIOfficePublicRuntimeFacadeTests(unittest.TestCase):
    @staticmethod
    def handlers(calls=None):
        calls = calls if calls is not None else []

        def outcome(name, ref):
            def call(value):
                calls.append((name, value))
                return {
                    "status": "COMPLETED",
                    "workflow_ref": ref,
                    "reason_codes": [],
                }
            return call

        return AIOfficePublicRuntimeHandlersV1(
            submit_work=outcome("work", "work-1"),
            request_capability=outcome("capability", "cap-1"),
            request_approval=outcome("approval", "wf-1"),
            submit_execution_intent=lambda value: {
                "status": "POLICY_BLOCKED",
                "workflow_ref": "wf-1",
                "reason_codes": ["PILOT_NO_EXTERNAL_EFFECT"],
            },
            read_effect_evidence=lambda intent_id: {
                "intent_id": intent_id,
                "execution_ref": "exec-1",
                "effect_status": "SUCCEEDED",
                "external_object_ref": "effect://1",
                "occurred_at": "2026-10-04T00:00:00Z",
                "evidence_refs": [],
                "reconciliation_required": False,
                "failure_class": None,
            },
            read_status=lambda workflow_ref: {
                "workflow_ref": workflow_ref,
                "business_stage": "PILOT",
                "platform_run_state_ref": "run-1",
                "pending_approvals": [],
                "blockers": [],
                "last_business_entity_refs": [],
                "evidence_refs": [],
            },
            transport_business_event=outcome("event", "corr-1"),
        )

    def test_composes_all_seven_public_operations_without_owning_authority(self):
        calls = []
        facade = compose_public_runtime_facade(self.handlers(calls))

        self.assertEqual(facade.submit_work(object())["status"], "COMPLETED")
        self.assertEqual(
            facade.request_capability(object())["status"], "COMPLETED"
        )
        self.assertEqual(
            facade.request_approval(object())["status"], "COMPLETED"
        )
        self.assertEqual(
            facade.submit_execution_intent(object())["status"],
            "POLICY_BLOCKED",
        )
        self.assertEqual(
            facade.read_effect_evidence("intent-1")["intent_id"],
            "intent-1",
        )
        self.assertEqual(
            facade.read_status("wf-1")["workflow_ref"],
            "wf-1",
        )
        self.assertEqual(
            facade.transport_business_event(object())["status"],
            "COMPLETED",
        )
        self.assertEqual(
            [item[0] for item in calls],
            ["work", "capability", "approval", "event"],
        )

    def test_all_handlers_are_required_and_must_be_callable(self):
        original = self.handlers()
        values = {
            name: getattr(original, name)
            for name in original.__dataclass_fields__
        }
        values["submit_work"] = None
        with self.assertRaisesRegex(
            AIOfficePublicRuntimeError,
            "handler is not callable: submit_work",
        ):
            AIOfficePublicRuntimeHandlersV1(**values)

    def test_unknown_runtime_status_fails_closed(self):
        handlers = self.handlers()
        handlers = AIOfficePublicRuntimeHandlersV1(
            **{
                name: (
                    (lambda _: {"status": "UNKNOWN", "reason_codes": []})
                    if name == "submit_work"
                    else getattr(handlers, name)
                )
                for name in handlers.__dataclass_fields__
            }
        )
        facade = AIOfficePublicRuntimeFacade(handlers)
        with self.assertRaisesRegex(
            AIOfficePublicRuntimeError,
            "unsupported public status",
        ):
            facade.submit_work(object())

    def test_authority_selector_fields_cannot_leak_through_public_outcomes(self):
        handlers = self.handlers()
        handlers = AIOfficePublicRuntimeHandlersV1(
            **{
                name: (
                    (lambda _: {
                        "status": "COMPLETED",
                        "reason_codes": [],
                        "provider": "nvidia",
                    })
                    if name == "submit_work"
                    else getattr(handlers, name)
                )
                for name in handlers.__dataclass_fields__
            }
        )
        facade = AIOfficePublicRuntimeFacade(handlers)
        with self.assertRaisesRegex(
            AIOfficePublicRuntimeError,
            "authority-selection fields",
        ):
            facade.submit_work(object())

    def test_status_and_effect_reads_bind_requested_identity(self):
        handlers = self.handlers()
        bad_status = AIOfficePublicRuntimeHandlersV1(
            **{
                name: (
                    (lambda _: {"workflow_ref": "other"})
                    if name == "read_status"
                    else getattr(handlers, name)
                )
                for name in handlers.__dataclass_fields__
            }
        )
        with self.assertRaisesRegex(
            AIOfficePublicRuntimeError,
            "read_status identity mismatch",
        ):
            AIOfficePublicRuntimeFacade(bad_status).read_status("wf-1")

        bad_effect = AIOfficePublicRuntimeHandlersV1(
            **{
                name: (
                    (lambda _: {"intent_id": "other"})
                    if name == "read_effect_evidence"
                    else getattr(handlers, name)
                )
                for name in handlers.__dataclass_fields__
            }
        )
        with self.assertRaisesRegex(
            AIOfficePublicRuntimeError,
            "read_effect_evidence identity mismatch",
        ):
            AIOfficePublicRuntimeFacade(bad_effect).read_effect_evidence(
                "intent-1"
            )

    def test_public_facade_has_no_forbidden_runtime_authority_imports(self):
        source = inspect.getsource(public_runtime)
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = {
            "runtime.full_mcp",
            "runtime.orchestrator.provider_router",
            "runtime.orchestrator.mprf",
            "runtime.orchestrator.ocpv2_runtime_service",
        }
        self.assertTrue(imported.isdisjoint(forbidden))

    def test_handler_exception_does_not_trigger_fallback_authority(self):
        handlers = self.handlers()
        handlers = AIOfficePublicRuntimeHandlersV1(
            **{
                name: (
                    (lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
                    if name == "submit_work"
                    else getattr(handlers, name)
                )
                for name in handlers.__dataclass_fields__
            }
        )
        facade = AIOfficePublicRuntimeFacade(handlers)
        with self.assertRaisesRegex(RuntimeError, "boom"):
            facade.submit_work(object())


if __name__ == "__main__":
    unittest.main()
