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


    def _contract(self, *, required_evidence_classes):
        from runtime.orchestrator.gate_continuation_contract import GateContinuationContract
        return GateContinuationContract.from_mapping({
            "schema_version":"orchestration.gate-continuation-contract.v1","gate_id":"G",
            "continuation_policy":"AUTO_WITHIN_APPROVED_CONTRACT","approved_base_head":"c"*40,
            "source_lineage_policy":"APPROVED_DESCENDANT_CHAIN","allowed_write_paths":["owned.txt"],
            "forbidden_paths":[".git/"],"required_verifiers":["UNITTEST"],
            "required_evidence_classes":list(required_evidence_classes),"commit_policy":"LOCAL_COMMIT_ALLOWED",
            "risk_classes":["REPOSITORY_WRITE"],"approval_coverage_ref":"approval://test",
            "approval_coverage_digest":"9"*64,"external_effect_policy":"GOVERNED_REPOSITORY_EFFECTS_ONLY",
            "runtime_migration_policy":"NO_RUNTIME_MIGRATION"})

    def test_attestation_contract_validation_requires_effect_reconciliation_digest(self):
        Attestation,_,Error=self.api()
        contract=self._contract(required_evidence_classes=("TEST_RESULT","EFFECT_RECONCILIATION"))
        a=Attestation.create(project_id="P",run_id="R",gate_id="G",authority_core_sha256="a"*64,
            contract_sha256=contract.contract_sha256,source_head="c"*40,source_tree_sha256="d"*40,
            changed_paths_sha256="e"*64,verifier_results={"UNITTEST":{"status":"PASS","evidence_sha256":"f"*64}},
            evidence_digests={"TEST_RESULT":"1"*64})
        with self.assertRaisesRegex(Error,"required evidence"):
            a.validate_for_contract(contract)

    def test_attestation_contract_validation_accepts_bound_effect_reconciliation(self):
        Attestation,_,_=self.api()
        contract=self._contract(required_evidence_classes=("TEST_RESULT","EFFECT_RECONCILIATION"))
        a=Attestation.create(project_id="P",run_id="R",gate_id="G",authority_core_sha256="a"*64,
            contract_sha256=contract.contract_sha256,source_head="c"*40,source_tree_sha256="d"*40,
            changed_paths_sha256="e"*64,verifier_results={"UNITTEST":{"status":"PASS","evidence_sha256":"f"*64}},
            evidence_digests={"TEST_RESULT":"1"*64,"EFFECT_RECONCILIATION":"2"*64})
        a.validate_for_contract(contract)

if __name__=="__main__": unittest.main()
