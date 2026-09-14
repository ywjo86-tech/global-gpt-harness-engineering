import json, tempfile, unittest
from pathlib import Path
from runtime.orchestrator.affiliate_entrypoint import AffiliateEntrypointError, resolve_alias, run_affiliate_entrypoint


class AffiliateEntrypointTests(unittest.TestCase):
    def test_alias_codex_delegates_once(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/"aliases").mkdir()
            (root/"aliases/a.json").write_text(json.dumps({"alias":"a","project_id":"p","entry_command":["a","codex"]}))
            calls=[]
            code=run_affiliate_entrypoint(["a","codex","production-gate-run"],mapping_root=root,dispatcher=lambda args:(calls.append(args) or 0))
            self.assertEqual(code,0); self.assertEqual(calls,[["production-gate-run"]])

    def test_unregistered_or_conflicting_entrypoint_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/"aliases").mkdir()
            with self.assertRaisesRegex(AffiliateEntrypointError,"not registered"):
                resolve_alias("missing",root)
            (root/"aliases/a.json").write_text(json.dumps({"alias":"a","project_id":"p","entry_command":["other","codex"]}))
            with self.assertRaisesRegex(AffiliateEntrypointError,"binding"):
                resolve_alias("a",root)
