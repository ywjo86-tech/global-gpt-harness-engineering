"""Regression: legacy active Gate retirement is explicit and fail-closed."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from runtime.orchestrator.legacy_gate_retirement import make_retirement_record,verify_retirement,digest

class LegacyGateRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"CANARY-PROJECT"
        self.root.mkdir()
        for rel,text in [
            ("docs/GATE_STATE.md","FIRST_GATE_ACTIVE\n"),
            ("docs/harness/first-gate.activation.json",'{"state":"ACTIVE"}\n'),
            ("docs/APPROVAL_LOG.md","old-approved-log\n")]:
            p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        self._git("init")
        self._git("add",".")
        self._git("-c","user.name=Test","-c","user.email=test@example.invalid","commit","-m","initial active")
        self.v2="docs/harness/sealed-v2-anchor.md"
        (self.root/self.v2).write_text("v2-inactive-anchor\n")
        rec=make_retirement_record(self.root,new_gate_state=self.v2,owner_authorization_ref="OWNER-SPECIFIC-G1-MIGRATION")
        self.proof=self.root/"docs/harness/legacy-gate-retirement.v1.json"
        self.proof.write_text(json.dumps(rec,sort_keys=True,indent=2)+"\n")
        self.sha=digest(self.proof.read_bytes())
        self._git("add",".")
        self._git("-c","user.name=Test","-c","user.email=test@example.invalid","commit","-m","retirement proof and v2")
    def _git(self,*args):
        return subprocess.run(["git","-C",str(self.root),*args],check=True,capture_output=True,text=True)
    def verify(self,sha=None):
        return verify_retirement(self.root,project_id=self.root.name,
            gate_state=self.root/self.v2,ledger_path=self.root/self.v2,
            business_approval=self.root/"docs/APPROVAL_LOG.md",
            record_rel="docs/harness/legacy-gate-retirement.v1.json",
            record_digest=sha or self.sha)
    def test_bound_committed_retirement(self):
        self.assertEqual(self.verify()["decision"],"RETIRE_LEGACY_ACTIVE_GATE_FOR_SEALED_V2")
    def test_unbound_retirement_rejected(self):
        with self.assertRaisesRegex(ValueError,"does not match registry"):
            self.verify("0"*64)
    def test_modified_historical_gate_rejected(self):
        with (self.root/"docs/GATE_STATE.md").open("a") as out:out.write("tampered\n")
        with self.assertRaisesRegex(ValueError,"historical Gate authority"):
            self.verify()
    def test_uncommitted_v2_proof_rejected(self):
        with (self.root/self.v2).open("a") as out:out.write("tampered\n")
        with self.assertRaisesRegex(ValueError,"V2 canonical state"):
            self.verify()
    def test_wrong_original_authority_location_rejected(self):
        with self.assertRaisesRegex(ValueError,"approval log location"):
            verify_retirement(self.root,project_id=self.root.name,gate_state=self.root/self.v2,
                ledger_path=self.root/self.v2,business_approval=self.root/"docs/noncanonical.md",
                record_rel="docs/harness/legacy-gate-retirement.v1.json",record_digest=self.sha)
