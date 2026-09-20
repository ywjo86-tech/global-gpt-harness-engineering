from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SKILL=(ROOT/'.agents/skills/harness-design/SKILL.md').read_text()
GUIDE=(ROOT/'docs/harness/skill-design-guide.md').read_text()
ORCH=(ROOT/'.agents/skills/new-project-orchestrator/SKILL.md').read_text()

class HarnessDesignContinuitySkillTests(unittest.TestCase):
    def test_harness_design_requires_stateful_continuity_review(self):
        for term in ('Stateful Continuity Review','self-reference','successor','rollback','NOT READY'):
            self.assertIn(term,SKILL)

    def test_continuity_invariants_are_defined(self):
        for term in ('CI-CONT-01','CI-CONT-02','CI-CONT-03','CI-CONT-04','CI-CONT-05'):
            self.assertIn(term,GUIDE)
        self.assertIn('Before -> Quiesce -> Transition -> Successor Verify -> Predecessor Close -> Rollback',GUIDE)

    def test_self_replacing_triggers_are_explicit(self):
        combined=SKILL+'\n'+GUIDE
        for term in ('runtime replacement','service restart','supervisor replacement','worktree','server reboot','scheduler','state-store'):
            self.assertIn(term,combined)

    def test_zero_active_self_reference_paradox_must_be_resolved(self):
        combined=SKILL+'\n'+GUIDE
        self.assertIn('zero active',combined.lower())
        self.assertIn('self-reference',combined)
        self.assertIn('durable continuation owner',combined)

    def test_new_project_orchestrator_routes_to_continuity_standard(self):
        self.assertIn('Stateful Continuity Review',ORCH)
        self.assertIn('self-replacing',ORCH)

    def test_stateless_design_does_not_force_false_trigger(self):
        self.assertIn('stateful',SKILL.lower())
        self.assertIn('applicable',SKILL.lower())

if __name__=='__main__': unittest.main()
