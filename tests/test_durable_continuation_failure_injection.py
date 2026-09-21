from __future__ import annotations
import unittest

class DurableContinuationFailureInjectionTests(unittest.TestCase):
    def test_stale_epoch_blocks_resume(self):
        try:
            from runtime.orchestrator.durable_continuation import evaluate_continuation_eligibility
        except ModuleNotFoundError as exc:
            self.fail(f"durable continuation module missing: {exc}")
        state={"state":"WAITING_RESOURCE","last_error":"CONTINUATION_RECOVERY_PENDING"}
        ctx={"continuation_policy":"AUTO_WITHIN_APPROVED_CONTRACT","contract_valid":True,
             "attestation_valid":True,"transaction_phase":"RECEIPT_SEALED","owner_epoch_current":False}
        result=evaluate_continuation_eligibility(state,ctx)
        self.assertFalse(result.eligible)
        self.assertEqual(result.reason,"STALE_OWNER_EPOCH")

if __name__=="__main__": unittest.main()
