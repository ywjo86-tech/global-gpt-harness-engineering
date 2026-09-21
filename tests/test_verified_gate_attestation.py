from __future__ import annotations
import tempfile, unittest
from pathlib import Path

class VerifiedGateAttestationTests(unittest.TestCase):
    def api(self):
        try:
            from runtime.orchestrator.verified_gate_attestation import VerifiedGateAttestation, VerifiedGateAttestationStore, AttestationError
        except ModuleNotFoundError as exc:
            self.fail(f"attestation module missing: {exc}")
        return VerifiedGateAttestation,VerifiedGateAttestationStore,AttestationError

    def test_attestation_binds_tree_changed_paths_and_verifier_evidence(self):
        Attestation,Store,_=self.api()
        a=Attestation.create(project_id="P",run_id="R",gate_id="G",authority_core_sha256="a"*64,
            contract_sha256="b"*64,source_head="c"*40,source_tree_sha256="d"*40,
            changed_paths_sha256="e"*64,verifier_results={"UNITTEST":{"status":"PASS","evidence_sha256":"f"*64}},
            evidence_digests={"TEST_RESULT":"1"*64})
        self.assertRegex(a.attestation_sha256,r"^[0-9a-f]{64}$")
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)); stored=store.create(a); loaded=store.load("P","R","G")
            self.assertEqual(stored.attestation_sha256,loaded.attestation_sha256)
            self.assertEqual(loaded.source_tree_sha256,"d"*40)
            self.assertEqual(loaded.changed_paths_sha256,"e"*64)

    def test_attestation_rejects_non_pass_verifier(self):
        Attestation,_,Error=self.api()
        with self.assertRaisesRegex(Error,"verifier"):
            Attestation.create(project_id="P",run_id="R",gate_id="G",authority_core_sha256="a"*64,
                contract_sha256="b"*64,source_head="c"*40,source_tree_sha256="d"*40,
                changed_paths_sha256="e"*64,verifier_results={"UNITTEST":{"status":"FAIL","evidence_sha256":"f"*64}},
                evidence_digests={"TEST_RESULT":"1"*64})

if __name__=="__main__": unittest.main()
