import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from runtime.orchestrator.host_cplus_smoke import CPlusSmokeFailure, _security_stage_summary, main


class HostCPlusSmokeTests(unittest.TestCase):
    def test_blocked_summary_has_bounded_stage_only(self):
        out = io.StringIO()
        with patch("runtime.orchestrator.host_cplus_smoke.run_smoke", side_effect=CPlusSmokeFailure("CODEX_TRANSPORT")), redirect_stdout(out):
            self.assertEqual(main([]), 10)
        self.assertEqual(
            out.getvalue().strip(),
            "RESULT=HOST_CPLUS_BLOCKED FAIL_STAGE=CODEX_TRANSPORT "
            "JSONL_VALID=NOT_EVALUATED STDERR_SECURITY=NOT_EVALUATED FINAL_MESSAGE=NOT_EVALUATED",
        )

    def test_unknown_failure_is_safe(self):
        out = io.StringIO()
        with patch("runtime.orchestrator.host_cplus_smoke.run_smoke", side_effect=RuntimeError("do-not-print")), redirect_stdout(out):
            self.assertEqual(main([]), 10)
        self.assertEqual(out.getvalue().strip(), "RESULT=HOST_CPLUS_BLOCKED FAIL_STAGE=UNKNOWN")

    def test_independent_security_stage_statuses_distinguish_not_evaluated(self):
        self.assertEqual(_security_stage_summary("JSONL_CONTRACT"), {
            "JSONL_VALID": "BLOCK", "STDERR_SECURITY": "NOT_EVALUATED", "FINAL_MESSAGE": "NOT_EVALUATED",
        })
        self.assertEqual(_security_stage_summary("STDERR_SECURITY"), {
            "JSONL_VALID": "PASS", "STDERR_SECURITY": "BLOCK", "FINAL_MESSAGE": "NOT_EVALUATED",
        })
        self.assertEqual(_security_stage_summary("FINAL_MESSAGE"), {
            "JSONL_VALID": "PASS", "STDERR_SECURITY": "PASS", "FINAL_MESSAGE": "BLOCK",
        })


if __name__ == "__main__":
    unittest.main()
