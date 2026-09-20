import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
from runtime.tool_implementation.cli_anything_adapter import run_preflight
from runtime.tool_implementation.manifest import seal_manifest


class CliAnythingAuthorityNegativeSpaceTests(unittest.TestCase):
    def test_tool_implementation_plane_has_no_control_authority_imports(self):
        root = Path('runtime/tool_implementation')
        text = '\n'.join(p.read_text(encoding='utf-8') for p in sorted(root.glob('*.py')))
        forbidden = (
            'provider_router', 'production_attention', 'completion_authority',
            'SingleToolBroker', 'ClosedOperationRegistry', 'ToolEffectJournal',
            'approve_scope', 'resume_wait', 'declare_completion',
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, text)

    def test_cli_execution_never_uses_shell_true(self):
        text = Path('runtime/tool_implementation/cli_anything_adapter.py').read_text(encoding='utf-8')
        self.assertIn('shell=False', text)
        self.assertNotIn('shell=True', text)

    def test_production_code_does_not_directly_invoke_qualified_launcher(self):
        offenders = []
        for path in Path('runtime/orchestrator').glob('*.py'):
            if path.name == 'production_tool_transport.py':
                continue
            text = path.read_text(encoding='utf-8')
            if 'qualified_cli_launcher(' in text or 'run_preflight(' in text:
                offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_cli_unavailable_does_not_mutate_full_plan_control_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            supervisor = DurableFullPlanSupervisor(
                root, project_id='P', run_id='R', gates=['G'], retry_budget=0,
                gate_timeout_seconds=1, heartbeat_seconds=.03, lease_seconds=.08,
                min_disk_free_bytes=0, min_inode_free=0, min_memory_available_bytes=0,
            )
            before, _ = supervisor.load()
            manifest = seal_manifest({
                'manifest_id':'CLI_UNAVAILABLE_V1','state':'CANDIDATE',
                'upstream_url':'https://github.com/HKUDS/CLI-Anything.git','upstream_ref':'HEAD',
                'upstream_commit':'810c18b0d1ab9b234bc996c9fd999318523a3ef0',
                'generated_artifact_sha256':'a'*64,'allowed_argv0':str(root/'missing-cli'),
                'allowed_subcommands':('inspect',),
                'input_schema':{'type':'object','properties':{'subcommand':{'type':'string'}},'required':['subcommand'],'additionalProperties':False},
                'output_schema':{'type':'object','properties':{'status':{'type':'string'}},'required':['status'],'additionalProperties':False},
                'effect_class':'READ_ONLY','verifier_sha256':'b'*64,
                'generated_skill_qualified':False,'generated_skill_qualification_sha256':'',
                'qualification_evidence_sha256':'','manifest_sha256':'',
            })
            result = run_preflight(manifest, {'subcommand':'inspect'}, cwd=root)
            after, _ = supervisor.load()
            self.assertEqual(result.status, 'UNAVAILABLE')
            self.assertEqual(result.control_authority, 'NONE')
            self.assertEqual(after['state_sha256'], before['state_sha256'])

    def test_generated_skill_requires_independent_evidence(self):
        from runtime.tool_implementation.manifest import ToolImplementationError
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            value = {
                'manifest_id':'CLI_SKILL_V1','state':'CANDIDATE',
                'upstream_url':'https://github.com/HKUDS/CLI-Anything.git','upstream_ref':'HEAD',
                'upstream_commit':'810c18b0d1ab9b234bc996c9fd999318523a3ef0',
                'generated_artifact_sha256':'a'*64,'allowed_argv0':str(root/'cli'),
                'allowed_subcommands':('inspect',),
                'input_schema':{'type':'object','properties':{'subcommand':{'type':'string'}},'required':['subcommand'],'additionalProperties':False},
                'output_schema':{'type':'object','properties':{},'required':[],'additionalProperties':False},
                'effect_class':'READ_ONLY','verifier_sha256':'b'*64,
                'generated_skill_qualified':True,'generated_skill_qualification_sha256':'',
                'qualification_evidence_sha256':'','manifest_sha256':'',
            }
            with self.assertRaises(ToolImplementationError):
                seal_manifest(value)


if __name__ == '__main__':
    unittest.main()
