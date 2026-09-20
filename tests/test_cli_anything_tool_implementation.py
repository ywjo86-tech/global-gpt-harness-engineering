import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.tool_implementation.manifest import seal_manifest
from runtime.tool_implementation.cli_anything_adapter import (
    ToolImplementationError, build_cli_argv, dry_run, run_preflight,
)
from runtime.tool_implementation.qualification import qualify_source_checkout


def manifest(executable: Path, *, artifact_sha=None, input_schema=None):
    artifact_sha = artifact_sha or hashlib.sha256(executable.read_bytes()).hexdigest()
    schema=input_schema or {'type':'object','properties':{
        'subcommand':{'type':'string'},'value':{'type':'string'},
        'path':{'type':'string','x-cli-kind':'relative_path'},
    },'required':['subcommand'],'additionalProperties':False}
    return seal_manifest({
        'manifest_id':'CLI_ANYTHING_TEST_V1','state':'CANDIDATE',
        'upstream_url':'https://github.com/HKUDS/CLI-Anything.git','upstream_ref':'HEAD',
        'upstream_commit':'810c18b0d1ab9b234bc996c9fd999318523a3ef0',
        'generated_artifact_sha256':artifact_sha,'allowed_argv0':str(executable),
        'allowed_subcommands':('inspect','render'), 'input_schema':schema,
        'output_schema':{'type':'object','properties':{'status':{'type':'string'}},'additionalProperties':False},
        'effect_class':'READ_ONLY','verifier_sha256':'c'*64,
        'generated_skill_qualified':False,'generated_skill_qualification_sha256':'',
        'qualification_evidence_sha256':'','manifest_sha256':'',
    })


def write_cli(root: Path, body: str) -> Path:
    p=root/'bounded-cli'; p.write_text('#!/usr/bin/python3\n'+body); p.chmod(0o700); return p

class CliAnythingImplementationTests(unittest.TestCase):
    def test_argv_is_explicit_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as td:
            p=write_cli(Path(td),'print("ok")\n'); m=manifest(p)
            self.assertEqual(build_cli_argv(m,{'subcommand':'inspect','value':'abc','path':'safe/out.txt'}),
                             [str(p),'inspect','--path=safe/out.txt','--value=abc'])
            with self.assertRaises(ToolImplementationError): build_cli_argv(m,{'subcommand':'exec'})
            with self.assertRaises(ToolImplementationError): build_cli_argv(m,{'subcommand':'inspect','command':'id'})

    def test_relative_path_is_normalized_and_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            p=write_cli(Path(td),'print("ok")\n'); m=manifest(p)
            with self.assertRaises(ToolImplementationError): build_cli_argv(m,{'subcommand':'inspect','path':'../secret'})
            with self.assertRaises(ToolImplementationError): build_cli_argv(m,{'subcommand':'inspect','path':'/etc/passwd'})

    def test_dry_run_never_launches_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); marker=root/'ran'; p=write_cli(root,f'open({str(marker)!r},"w").write("x")\n')
            result=dry_run(manifest(p),{'subcommand':'inspect'},cwd=root)
            self.assertEqual(result.status,'DRY_RUN'); self.assertFalse(marker.exists()); self.assertEqual(result.control_authority,'NONE')

    def test_preflight_strips_secret_environment_and_isolates_home(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=write_cli(root,'import os,json\nprint(json.dumps({"secret":os.getenv("AWS_SECRET_ACCESS_KEY"),"home":os.getenv("HOME")}))\n')
            old=os.environ.get('AWS_SECRET_ACCESS_KEY'); os.environ['AWS_SECRET_ACCESS_KEY']='must-not-leak'
            try: result=run_preflight(manifest(p),{'subcommand':'inspect'},cwd=root)
            finally:
                if old is None: os.environ.pop('AWS_SECRET_ACCESS_KEY',None)
                else: os.environ['AWS_SECRET_ACCESS_KEY']=old
            self.assertEqual(result.status,'PASS'); self.assertIn('"secret": null',result.stdout); self.assertIn('.gch-cli-home',result.stdout)

    def test_preflight_detects_unavailable_and_artifact_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=write_cli(root,'print("ok")\n'); m=manifest(p)
            p.unlink(); self.assertEqual(run_preflight(m,{'subcommand':'inspect'},cwd=root).status,'UNAVAILABLE')
            p=write_cli(root,'print("changed")\n'); self.assertEqual(run_preflight(m,{'subcommand':'inspect'},cwd=root).status,'ARTIFACT_MISMATCH')

    def test_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=write_cli(root,'print("x"*10000)\n')
            r=run_preflight(manifest(p),{'subcommand':'inspect'},cwd=root,max_output_bytes=64)
            self.assertEqual(r.status,'OUTPUT_LIMIT_EXCEEDED'); self.assertLessEqual(len(r.stdout.encode()),64)

    def test_source_checkout_is_exact_and_control_authority_none(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); subprocess.run(['git','init','-q',str(root)],check=True); subprocess.run(['git','-C',str(root),'config','user.email','t@example.com'],check=True); subprocess.run(['git','-C',str(root),'config','user.name','t'],check=True)
            (root/'LICENSE').write_text('Apache License\nVersion 2.0\n'); (root/'source.py').write_text('x=1\n'); subprocess.run(['git','-C',str(root),'add','.'],check=True); subprocess.run(['git','-C',str(root),'commit','-qm','init'],check=True)
            head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
            q=qualify_source_checkout(root,upstream_url='https://example.invalid/repo.git',expected_commit=head,mechanisms=('REGISTRY_METADATA','SKILL_GENERATOR_REFERENCE'))
            self.assertEqual(q.commit,head); self.assertEqual(q.control_authority,'NONE'); self.assertRegex(q.qualification_sha256,r'^[0-9a-f]{64}$')
            with self.assertRaises(ToolImplementationError): qualify_source_checkout(root,upstream_url='https://example.invalid/repo.git',expected_commit='0'*40,mechanisms=('REGISTRY_METADATA',))

if __name__=='__main__': unittest.main()
