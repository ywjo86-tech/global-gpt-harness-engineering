"""Regression: legacy active Gate retirement is explicit and fail-closed."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from runtime.orchestrator.legacy_gate_retirement import make_retirement_record,verify_retirement,digest,owner_preflight,owner_comment_body,_canonical,require_exact_owner_comment
from unittest.mock import patch

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
        # Test only: synthesized GitHub fixture. Production issuance MUST fetch live via GitHub API.
        self.proof_request_id="RC1-G1-LEGACY-RETIREMENT-20261017-01"
        # Owner proof is scoped to a fixed RC1 V2 Gate anchor path.
        self.v2="docs/harness/g1-rc1-v2-sealed-anchor.md"
        (self.root/self.v2).write_text("v2-inactive-anchor\n")
        preflight=owner_preflight(self.root,new_gate_state=self.v2,request_id=self.proof_request_id)
        approval_digest=digest(_canonical(preflight))
        self.comment={"id":999001,"body":owner_comment_body(approval_digest),
                      "created_at":"2026-10-17T10:50:00Z","updated_at":"2026-10-17T10:50:00Z",
                      "user":{"id":235775273},
                      "html_url":"https://github.com/ywjo86-tech/ocpv2-control/pull/1#issuecomment-999001"}
        network=patch("runtime.orchestrator.legacy_gate_retirement._fetch_live_owner_comment",return_value=self.comment)
        network.start();self.addCleanup(network.stop)
        rec=make_retirement_record(self.root,new_gate_state=self.v2,owner_authorization_ref=self.proof_request_id,owner_comment=self.comment)
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

    def test_missing_owner_comment_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"verified owner Github comment required"):
            make_retirement_record(self.root,new_gate_state=self.v2,owner_authorization_ref=self.proof_request_id)
    def test_fake_owner_comment_is_rejected(self):
        forged=dict(self.comment)
        forged["user"]={"id":111111}
        with self.assertRaisesRegex(ValueError,"actor mismatched"):
            make_retirement_record(self.root,new_gate_state=self.v2,owner_authorization_ref=self.proof_request_id,owner_comment=forged)
    def test_edited_owner_comment_is_rejected(self):
        forged=dict(self.comment)
        forged["updated_at"]="2026-10-17T10:51:00Z"
        # Isolate the changed timestamp. setUp has already committed a second
        # HEAD, so rebuilding the old approval's preflight here would fail
        # the intent digest before reaching the edited-comment safeguard.
        approved_digest=json.loads(self.comment["body"].split("\n",1)[1])["preflight_digest"]
        with self.assertRaisesRegex(ValueError,"been edited"):
            require_exact_owner_comment(forged,preflight_digest=approved_digest)
    def test_old_approval_cannot_bind_a_new_git_head(self):
        # After setUp's fixture commit the authority HEAD differs from that
        # in the owner-approved preflight. The old comment must be rejected.
        with self.assertRaisesRegex(ValueError,"intent mismatched"):
            make_retirement_record(self.root,new_gate_state=self.v2,
                owner_authorization_ref=self.proof_request_id,owner_comment=self.comment)
    def test_replayed_foreign_comment_is_rejected(self):
        forged=dict(self.comment)
        forged["body"]=forged["body"].replace("preflight_digest","unbound_digest")
        with self.assertRaisesRegex(ValueError,"intent mismatched"):
            make_retirement_record(self.root,new_gate_state=self.v2,owner_authorization_ref=self.proof_request_id,owner_comment=forged)
    def test_tampered_stored_owner_proof_is_rejected(self):
        document=json.loads(self.proof.read_text())
        document["owner_proof"]["body"]="FORGED"
        document["record_sha256"]=digest(__import__("runtime.orchestrator.legacy_gate_retirement",fromlist=["_canonical"])._canonical({k:v for k,v in document.items() if k!="record_sha256"}))
        self.proof.write_text(json.dumps(document,sort_keys=True)+"\n")
        self.sha=digest(self.proof.read_bytes())
        with self.assertRaisesRegex(ValueError,"owner Github approval exact body mismatch"):
            self.verify()
