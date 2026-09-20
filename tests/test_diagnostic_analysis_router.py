import tempfile
import unittest
from pathlib import Path

from runtime.diagnostics.analysis_router import AnalysisRouter
from runtime.diagnostics.contracts import AnalysisEvidenceEnvelope, AnalysisRequest, SourceSnapshotBinding


class FakeAdapter:
    def __init__(self,name,status="CURRENT",fail=False): self.name=name; self.status=status; self.fail=fail; self.calls=[]
    def analyze(self,request,analysis_root):
        self.calls.append((request,Path(analysis_root)))
        if self.fail: raise RuntimeError(f"{self.name} unavailable")
        result={"candidate_files":[f"{self.name}.py"],"text":f"{self.name} evidence"}
        return AnalysisEvidenceEnvelope(project_id=request.project_id,run_id=request.run_id,gate_id=request.gate_id,
            task_id=request.task_id,analyzer=self.name,analyzer_version="1",analysis_mode="fake",status=self.status,
            source_binding=request.source_binding,result_digest=("a" if self.name=="graphify" else "b")*64,
            raw_evidence_ref=f"evidence://{self.name}",result=result)


def binding():
    return SourceSnapshotBinding(project_id="P",source_root_id="c"*64,git_head_sha="d"*40,
        workspace_tree_digest="e"*64,owned_paths=(),owned_scope_digest="f"*64,captured_at="2026-09-20T00:00:00+00:00")

def request(kind):
    return AnalysisRequest(project_id="P",run_id="R",gate_id="G",task_id="T",kind=kind,query="route_provider",source_binding=binding())

class AnalysisRouterTests(unittest.TestCase):
    def test_exact_symbol_request_prefers_codegraph(self):
        with tempfile.TemporaryDirectory() as d:
            g=FakeAdapter("graphify"); c=FakeAdapter("codegraph")
            out=AnalysisRouter(g,c,analysis_root=d).analyze(request("SYMBOL_IMPACT"))
            self.assertEqual([x.analyzer for x in out],["codegraph"])
            self.assertEqual(len(g.calls),0)

    def test_unclear_cross_cutting_request_uses_graphify_then_codegraph(self):
        with tempfile.TemporaryDirectory() as d:
            g=FakeAdapter("graphify"); c=FakeAdapter("codegraph")
            out=AnalysisRouter(g,c,analysis_root=d).analyze(request("TOPOLOGY_AND_IMPACT"))
            self.assertEqual([x.analyzer for x in out],["graphify","codegraph"])

    def test_one_failure_returns_survivor_as_degraded_and_no_exception(self):
        with tempfile.TemporaryDirectory() as d:
            out=AnalysisRouter(FakeAdapter("graphify",fail=True),FakeAdapter("codegraph"),analysis_root=d).analyze(request("TOPOLOGY_AND_IMPACT"))
            self.assertEqual(len(out),1); self.assertEqual(out[0].analyzer,"codegraph"); self.assertEqual(out[0].status,"DEGRADED")
            out2=AnalysisRouter(FakeAdapter("graphify"),FakeAdapter("codegraph",fail=True),analysis_root=d).analyze(request("TOPOLOGY_AND_IMPACT"))
            self.assertEqual(len(out2),1); self.assertEqual(out2[0].analyzer,"graphify"); self.assertEqual(out2[0].status,"DEGRADED")

    def test_both_fail_returns_empty_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            router=AnalysisRouter(FakeAdapter("graphify",fail=True),FakeAdapter("codegraph",fail=True),analysis_root=d)
            self.assertEqual(router.analyze(request("TOPOLOGY_AND_IMPACT")),())


if __name__ == "__main__": unittest.main()
