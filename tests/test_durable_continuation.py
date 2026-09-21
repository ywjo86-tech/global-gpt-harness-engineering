from __future__ import annotations
import unittest

class DurableContinuationEligibilityTests(unittest.TestCase):
    def api(self):
        try:
            from runtime.orchestrator.durable_continuation import evaluate_continuation_eligibility
        except ModuleNotFoundError as exc:
            self.fail(f"durable continuation module missing: {exc}")
        return evaluate_continuation_eligibility

    def auto_context(self):
        return {"continuation_policy":"AUTO_WITHIN_APPROVED_CONTRACT","contract_valid":True,
                "attestation_valid":True,"transaction_phase":"RECEIPT_SEALED","owner_epoch_current":True}

    def test_dcc_cannot_resume_non_receipt_waits(self):
        evaluate = self.api()
        cases=[("WAITING_APPROVAL","USER_DECISION_REQUIRED"),("WAITING_PROVIDER","PROVIDER_UNAVAILABLE"),
               ("WAITING_RESOURCE","LOW_RESOURCE_BACKPRESSURE"),("WAITING_RESOURCE","RUNTIME_MIGRATION_QUIESCED")]
        for state,reason in cases:
            with self.subTest(state=state,reason=reason):
                result=evaluate({"state":state,"last_error":reason},self.auto_context())
                self.assertFalse(result.eligible)

    def test_auto_receipt_wait_requires_complete_bound_context(self):
        evaluate=self.api(); state={"state":"WAITING_RESOURCE","last_error":"OPERATOR_TASK_RECEIPT_PENDING"}
        self.assertTrue(evaluate(state,self.auto_context()).eligible)
        for field in ("contract_valid","attestation_valid","owner_epoch_current"):
            ctx=self.auto_context(); ctx[field]=False
            self.assertFalse(evaluate(state,ctx).eligible)
        ctx=self.auto_context(); ctx["continuation_policy"]="MANUAL_OPERATOR"
        self.assertFalse(evaluate(state,ctx).eligible)

if __name__=="__main__": unittest.main()
