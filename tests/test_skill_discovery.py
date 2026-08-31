from __future__ import annotations

import unittest

from runtime.orchestrator.approval_gate import CAUTION, DANGEROUS, classify_discovery_intent
from runtime.orchestrator.schemas import (
    CandidateRisk,
    CapabilityCandidate,
    CapabilityRequirement,
    DiscoveryDecision,
    DiscoveryLevel,
    DiscoveryStatus,
)


def requirement() -> CapabilityRequirement:
    return CapabilityRequirement(
        capability_id="python.testing", gate_id="GATE-1", lv_id="LV-1",
        required_permissions=("read",), owned_files=("tests/",), optional=False,
    )


def candidate(**overrides: object) -> CapabilityCandidate:
    values: dict[str, object] = {
        "candidate_id": "owner/repo@python-testing", "source": "skills.sh",
        "repository": "owner/repo", "maintainer": "owner", "scope": "project",
        "metadata": {"skill_md_verified": True, "permissions": ["read"], "owned_files": ["tests/"]}, "evaluation_state": "PASS",
        "risk": CandidateRisk(),
    }
    values.update(overrides)
    return CapabilityCandidate(**values)


class SkillDiscoverySchemaTests(unittest.TestCase):
    def test_existing_capability_is_terminal_and_does_not_require_discovery(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), selected_existing_asset="registered-python-agent", discovery_level=DiscoveryLevel.EXISTING_CAPABILITY, discovery_status=DiscoveryStatus.EXISTING)
        self.assertEqual(decision.discovery_status, DiscoveryStatus.EXISTING)
        self.assertFalse(decision.discovery_required)

    def test_capability_gap_requires_discovery(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.DISCOVERY_REQUIRED)
        self.assertTrue(decision.discovery_required)

    def test_unapproved_discovery_is_blocked(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.BLOCKED, blocked_reason="dangerous approval required", approval_required=True)
        self.assertTrue(decision.approval_required)

    def test_project_install_is_not_executable(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.PROJECT_INSTALL, discovery_status=DiscoveryStatus.INSTALL_REQUIRED, approval_required=True, escalation_reason="project file write and supply-chain review")
        self.assertFalse(decision.execution_allowed)

    def test_global_install_requires_escalation(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.GLOBAL_INSTALL, discovery_status=DiscoveryStatus.ESCALATION_REQUIRED, escalation_reason="global scope", approval_required=True)
        self.assertFalse(decision.execution_allowed)

    def test_dangerous_candidate_is_blocked(self) -> None:
        risky = candidate(risk=CandidateRisk(secret=True))
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.BLOCKED, candidate_list=(risky,), blocked_reason="candidate requires secret")
        self.assertFalse(decision.execution_allowed)

    def test_unknown_or_incomplete_candidate_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            candidate(scope="")
        with self.assertRaises(ValueError):
            candidate(metadata={})
        with self.assertRaises(ValueError):
            CapabilityCandidate(candidate_id="x", source="", repository="repo", maintainer="m", scope="project", metadata={}, evaluation_state="UNKNOWN", risk=CandidateRisk())

    def test_permission_and_owned_file_mismatch_are_not_approved(self) -> None:
        mismatched = candidate(metadata={"skill_md_verified": True, "permissions": ["write"], "owned_files": ["docs/"]})
        with self.assertRaises(ValueError):
            DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.CANDIDATE_EVALUATED, candidate_list=(mismatched,), selected_candidate=mismatched.candidate_id)

    def test_discovery_failure_does_not_become_existing_or_approved(self) -> None:
        decision = DiscoveryDecision(requirement=requirement(), discovery_level=DiscoveryLevel.DISCOVERY, discovery_status=DiscoveryStatus.BLOCKED, blocked_reason="candidate evaluation failed")
        self.assertNotEqual(decision.discovery_status, DiscoveryStatus.EXISTING)
        self.assertFalse(decision.execution_allowed)

    def test_intents_use_existing_approval_boundaries(self) -> None:
        self.assertEqual(classify_discovery_intent("skill_discovery_read_only").classification, DANGEROUS)
        self.assertEqual(classify_discovery_intent("project_skill_install").classification, CAUTION)
        self.assertEqual(classify_discovery_intent("global_skill_install").classification, DANGEROUS)
        self.assertEqual(classify_discovery_intent("project_skill_create").classification, CAUTION)
        self.assertEqual(classify_discovery_intent("global_skill_create").classification, DANGEROUS)


if __name__ == "__main__":
    unittest.main()
