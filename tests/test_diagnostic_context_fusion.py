import json
import tempfile
import unittest
from pathlib import Path

from runtime.diagnostics.context_fusion import fuse_context
from runtime.diagnostics.contracts import AnalysisEvidenceEnvelope, AnalysisRequest, SourceSnapshotBinding
from runtime.diagnostics.evidence_store import DiagnosticEvidenceStore


def binding():
    return SourceSnapshotBinding(project_id="P",source_root_id="c"*64,git_head_sha="d"*40,
        workspace_tree_digest="e"*64,owned_paths=("owned.py",),owned_scope_digest="f"*64,captured_at="2026-09-20T00:00:00+00:00")

def req(kind="TOPOLOGY_AND_IMPACT"):
    return AnalysisRequest(project_id="P",run_id="R",gate_id="G",task_id="T",kind=kind,query="x",source_binding=binding(),owned_paths=("owned.py",))

def env(name,files,status="CURRENT",tests=()):
    result={"candidate_files":list(files),"related_tests":list(tests),"text":name+" evidence"}
    return AnalysisEvidenceEnvelope(project_id="P",run_id="R",gate_id="G",task_id="T",analyzer=name,
        analyzer_version="1",analysis_mode="x",status=status,source_binding=binding(),
        result_digest=("a" if name=="graphify" else "b")*64,raw_evidence_ref=f"evidence://{name}",result=result)

class ContextFusionTests(unittest.TestCase):
    def test_current_evidence_is_bounded_sorted_and_does_not_expand_owned_scope(self):
        pack=fuse_context(req(),(env("graphify",("z.py","a.py"),tests=("tests/test_z.py",)),env("codegraph",("a.py","b.py"))),max_chars=1000)
        self.assertEqual(pack.status,"CURRENT")
        self.assertEqual(pack.candidate_files,("a.py","b.py","z.py"))
        self.assertEqual(pack.related_tests,("tests/test_z.py",))
        self.assertIn("a.py",pack.advisory_text)
        self.assertNotIn("owned_scope",pack.advisory_text)
        self.assertEqual(req().owned_paths,("owned.py",))

    def test_exact_symbol_disagreement_becomes_graph_conflict_and_suppresses_advisory(self):
        pack=fuse_context(req("SYMBOL_IMPACT"),(env("graphify",("a.py",)),env("codegraph",("b.py",))),max_chars=1000)
        self.assertEqual(pack.status,"CONFLICT")
        self.assertIn("GRAPH_CONFLICT",pack.conflicts)
        self.assertEqual(pack.advisory_text,"")
        self.assertEqual(set(pack.evidence_refs),{"evidence://graphify","evidence://codegraph"})

    def test_empty_or_noncurrent_evidence_is_degraded_without_advisory(self):
        self.assertEqual(fuse_context(req(),(),max_chars=1000).status,"DEGRADED")
        pack=fuse_context(req(),(env("graphify",("a.py",),status="DEGRADED"),),max_chars=1000)
        self.assertEqual(pack.status,"DEGRADED"); self.assertEqual(pack.advisory_text,"")

    def test_evidence_store_is_digest_bound_create_once(self):
        with tempfile.TemporaryDirectory() as d:
            store=DiagnosticEvidenceStore(d); envelope=env("graphify",("a.py",))
            ref=store.put(envelope); again=store.put(envelope)
            self.assertEqual(ref,again); self.assertTrue(ref.startswith("diagnostic://sha256/"))
            files=list(Path(d).glob("*.json")); self.assertEqual(len(files),1)
            payload=json.loads(files[0].read_text()); self.assertEqual(payload["result_digest"],envelope.result_digest)


if __name__ == "__main__": unittest.main()
