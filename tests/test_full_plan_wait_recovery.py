from __future__ import annotations
import unittest

class WaitRecoveryTests(unittest.TestCase):
    def api(self):
        try: from runtime.orchestrator.wait_recovery import classify_wait_recovery, WaitRecoveryError
        except ModuleNotFoundError as exc: self.fail(f"wait recovery module missing: {exc}")
        return classify_wait_recovery,WaitRecoveryError
    def test_each_wait_reason_has_exact_owner(self):
        classify,_=self.api()
        expected={"OPERATOR_TASK_RECEIPT_PENDING":"DCC_OR_OPERATOR","CONTINUATION_RECOVERY_PENDING":"DCC_RECONCILER",
                  "LOW_RESOURCE_BACKPRESSURE":"RESOURCE_RECOVERY","RUNTIME_MIGRATION_QUIESCED":"RUNTIME_MIGRATION",
                  "PROVIDER_UNAVAILABLE":"PROVIDER_RECOVERY","PROVIDER_RECOVERY_PENDING":"PROVIDER_RECOVERY"}
        for reason,owner in expected.items():
            state="WAITING_PROVIDER" if reason.startswith("PROVIDER_") else "WAITING_RESOURCE"
            self.assertEqual(classify({"state":state,"last_error":reason}).owner,owner)
    def test_unknown_or_incompatible_wait_fails_closed(self):
        classify,Error=self.api()
        with self.assertRaises(Error): classify({"state":"WAITING_RESOURCE","last_error":"UNKNOWN"})
        with self.assertRaises(Error): classify({"state":"WAITING_PROVIDER","last_error":"LOW_RESOURCE_BACKPRESSURE"})
        result=classify({"state":"WAITING_APPROVAL","last_error":"USER_DECISION_REQUIRED"})
        self.assertEqual(result.owner,"USER_DECISION")
        self.assertFalse(result.auto_recoverable)
if __name__=="__main__": unittest.main()
