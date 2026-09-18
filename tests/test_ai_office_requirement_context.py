from __future__ import annotations

import unittest

from runtime.ai_office.context_assembly import (
    ContextAssemblyError,
    ContextSourceRefV1,
    assemble_context,
)
from runtime.ai_office.requirement_intake import RequirementIntakeError, intake_requirement

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


class AIOfficeRequirementContextTest(unittest.TestCase):
    def register(self):
        return {
            "REQ-011": {
                "source_ref": "approved-plan:REQ-011",
                "source_digest": DIGEST_A,
                "planning_authority_ref": "full-plan:approved",
                "constraints_refs": ("constraint:scope",),
            }
        }

    def candidate(self):
        return {
            "requirement_id": "REQ-011",
            "source_ref": "approved-plan:REQ-011",
            "source_digest": DIGEST_A,
            "planning_authority_ref": "full-plan:approved",
            "constraints_refs": ("constraint:scope",),
            "correlation_id": "corr-1",
        }

    def test_011_only_exact_approved_source_binding_is_accepted(self) -> None:
        envelope = intake_requirement(self.candidate(), approved_register=self.register())
        self.assertEqual(envelope.requirement_id, "REQ-011")
        self.assertEqual(envelope.source_digest, DIGEST_A)
        changed = self.candidate()
        changed["source_digest"] = DIGEST_B
        with self.assertRaises(RequirementIntakeError):
            intake_requirement(changed, approved_register=self.register())
        expanded = self.candidate()
        expanded["normalized_text"] = "silently rewritten semantics"
        with self.assertRaises(RequirementIntakeError):
            intake_requirement(expanded, approved_register=self.register())

    def test_012_higher_precedence_source_cannot_be_overridden(self) -> None:
        envelope = intake_requirement(self.candidate(), approved_register=self.register())
        lower = ContextSourceRefV1("baseline", "TECHNICAL_ASSUMPTION", "assumption:baseline", DIGEST_C)
        approved = ContextSourceRefV1("baseline", "APPROVED_PLAN", "approved:baseline", DIGEST_B)
        context = assemble_context([envelope], [lower, approved])
        self.assertEqual(len(context.context_items), 1)
        self.assertEqual(context.context_items[0].authority_tier, "APPROVED_PLAN")
        self.assertEqual(context.context_items[0].source_digest, DIGEST_B)
    def test_012_conflicting_same_precedence_source_fails_closed(self) -> None:
        envelope = intake_requirement(self.candidate(), approved_register=self.register())
        one = ContextSourceRefV1("repo", "VERIFIED_REPOSITORY", "repo:one", DIGEST_A)
        two = ContextSourceRefV1("repo", "VERIFIED_REPOSITORY", "repo:two", DIGEST_B)
        with self.assertRaises(ContextAssemblyError):
            assemble_context([envelope], [one, two])

    def test_013_context_digest_is_deterministic_and_provider_neutral(self) -> None:
        envelope = intake_requirement(self.candidate(), approved_register=self.register())
        first = ContextSourceRefV1("repository", "VERIFIED_REPOSITORY", "repo:head", DIGEST_B)
        second = ContextSourceRefV1("run-state", "VERIFIED_STATE", "state:run", DIGEST_C)
        a = assemble_context([envelope], [first, second])
        b = assemble_context([envelope], [second, first])
        self.assertEqual(a.context_digest, b.context_digest)
        keys = set(a.to_dict())
        self.assertNotIn("provider", keys)
        self.assertNotIn("provider_ref", keys)
        self.assertNotIn("model", keys)
        self.assertNotIn("model_ref", keys)


if __name__ == "__main__":
    unittest.main()
