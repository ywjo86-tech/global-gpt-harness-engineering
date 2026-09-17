import unittest

from runtime.mprf.contracts import MPRFContractError
from runtime.mprf.failure import (
    FAILURE_DISPOSITIONS_V1, FAILOVER_PREREQUISITES_SCHEMA_V1,
    FailureClassV1, FailoverPrerequisitesV1, evaluate_failover, failure_class,
)
from runtime.mprf.router_client import build_reroute_request, to_router_request_v2
from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1, GOVERNED_POLICY_V1, ROUTER_REQUEST_SCHEMA_V2,
    ProviderEligibilitySnapshotV1, RouterRequestV2, route_request,
)


def prereqs(*, network_safe=False, complete=True):
    value = "ref" if complete else ""
    return FailoverPrerequisitesV1(
        FAILOVER_PREREQUISITES_SCHEMA_V1, value, value, value, value, value,
        "network-safe-policy" if network_safe else "",
    )


def original(stage="PREPARE", provider="nvidia"):
    snapshot = ProviderEligibilitySnapshotV1(
        ELIGIBILITY_SCHEMA_V1, "s0", {"nvidia": True, "codex": True},
        {"nvidia": "n/model", "codex": "c/model"}, ("eligibility",), {},
    )
    request = RouterRequestV2(
        ROUTER_REQUEST_SCHEMA_V2, "r0", "P", "RUN", "T", "E", "d"*64, stage,
        ("reasoning", "read_only") if stage != "ACTION" else ("filesystem_write",),
        stage == "ACTION", GOVERNED_POLICY_V1, snapshot,
    )
    return route_request(request)


class FailureTaxonomyTests(unittest.TestCase):
    def test_021_exact_fourteen_classes_each_have_one_disposition(self):
        expected = {
            "TASK_FAILURE", "MODEL_FAILURE", "PROVIDER_FAILURE", "AUTH_FAILURE", "RATE_LIMIT",
            "QUOTA_EXHAUSTION", "NETWORK_FAILURE", "INVALID_RESPONSE", "POLICY_REJECTION",
            "CHECKPOINT_FAILURE", "EXECUTION_BACKEND_FAILURE", "ACTION_SIDE_EFFECT_AMBIGUOUS",
            "RECOVERY_REQUIRED", "UNKNOWN_FAILURE",
        }
        self.assertEqual({item.value for item in FailureClassV1}, expected)
        self.assertEqual(set(FAILURE_DISPOSITIONS_V1), set(FailureClassV1))
        self.assertEqual(len(FAILURE_DISPOSITIONS_V1), 14)
        with self.assertRaisesRegex(MPRFContractError, "unknown FailureClass"):
            failure_class("SOMETHING_NEW")

    def test_022_only_eligible_classes_form_reroute_after_all_checks(self):
        eligible = [FailureClassV1.MODEL_FAILURE, FailureClassV1.PROVIDER_FAILURE,
                    FailureClassV1.RATE_LIMIT, FailureClassV1.QUOTA_EXHAUSTION]
        for failure in eligible:
            with self.subTest(failure=failure):
                request = build_reroute_request(
                    request_id="RR", project_id="P", run_id="RUN", task_id="T", task_execution_id="E",
                    original_router_decision=original(), failure=failure, prerequisites=prereqs(),
                )
                self.assertEqual(request.failure_class, failure)
                self.assertEqual(request.original_stage, "PREPARE")
        network = build_reroute_request(
            request_id="NET", project_id="P", run_id="RUN", task_id="T", task_execution_id="E",
            original_router_decision=original(), failure=FailureClassV1.NETWORK_FAILURE,
            prerequisites=prereqs(network_safe=True),
        )
        self.assertEqual(network.failure_class, FailureClassV1.NETWORK_FAILURE)
        for failure in eligible:
            with self.subTest(incomplete=failure):
                with self.assertRaisesRegex(MPRFContractError, "RECOVERY_PREREQUISITES_INCOMPLETE"):
                    build_reroute_request(request_id="BAD", project_id="P", run_id="RUN", task_id="T", task_execution_id="E",
                                          original_router_decision=original(), failure=failure, prerequisites=prereqs(complete=False))
        with self.assertRaisesRegex(MPRFContractError, "NETWORK_SAFE_POLICY_REQUIRED"):
            build_reroute_request(request_id="NETBAD", project_id="P", run_id="RUN", task_id="T", task_execution_id="E",
                                  original_router_decision=original(), failure=FailureClassV1.NETWORK_FAILURE, prerequisites=prereqs())

    def test_023_prohibited_failure_classes_never_form_reroute(self):
        prohibited = [FailureClassV1.TASK_FAILURE, FailureClassV1.INVALID_RESPONSE, FailureClassV1.AUTH_FAILURE,
                      FailureClassV1.POLICY_REJECTION, FailureClassV1.CHECKPOINT_FAILURE,
                      FailureClassV1.EXECUTION_BACKEND_FAILURE, FailureClassV1.ACTION_SIDE_EFFECT_AMBIGUOUS,
                      FailureClassV1.RECOVERY_REQUIRED, FailureClassV1.UNKNOWN_FAILURE]
        for failure in prohibited:
            with self.subTest(failure=failure):
                with self.assertRaisesRegex(MPRFContractError, "reroute prohibited"):
                    build_reroute_request(request_id="NO", project_id="P", run_id="RUN", task_id="T", task_execution_id="E",
                                          original_router_decision=original(), failure=failure, prerequisites=prereqs(),
                                          permission_related_auth=failure is FailureClassV1.AUTH_FAILURE)

    def test_024_nvidia_prepare_failure_cannot_become_codex_action(self):
        reroute = build_reroute_request(
            request_id="REROUTE", project_id="P", run_id="RUN", task_id="T", task_execution_id="E",
            original_router_decision=original("PREPARE", "nvidia"), failure=FailureClassV1.MODEL_FAILURE,
            prerequisites=prereqs(),
        )
        snapshot = ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1, "s1", {"nvidia": False, "codex": True}, {"codex": "c/model"}, ("after-failure",), {},
        )
        router_request = to_router_request_v2(reroute, directive_digest="e"*64, eligibility_snapshot=snapshot)
        self.assertEqual(router_request.stage, "PREPARE")
        self.assertFalse(router_request.state_change_required)
        decision = route_request(router_request)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.provider_ref, "")
        self.assertEqual(decision.model_ref, "")
        self.assertNotEqual(decision.stage, "ACTION")


if __name__ == "__main__":
    unittest.main()
