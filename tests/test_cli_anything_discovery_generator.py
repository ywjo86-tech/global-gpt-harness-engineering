import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.tool_implementation.manifest import ToolImplementationError
from runtime.tool_implementation.cli_hub_discovery import CliHubDiscoveryAdapter
from runtime.tool_implementation.cli_anything_generator import CliAnythingSkillGeneratorAdapter


def executable(root: Path, name: str, body: str) -> Path:
    path=root/name
    path.write_text('#!/usr/bin/python3\n'+body,encoding='utf-8')
    path.chmod(0o700)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CliHubDiscoveryTests(unittest.TestCase):
    def test_read_only_discovery_allowlist_and_control_authority_none(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            hub=executable(root,'cli-hub','import json,sys\nprint(json.dumps({"argv":sys.argv[1:]}))\n')
            adapter=CliHubDiscoveryAdapter(hub,artifact_sha256=sha(hub))
            for argv in (
                ('list','--json'),('search','image','--json'),('info','gimp'),('can','transcribe audio','--json'),
                ('matrix','list','--json'),('matrix','search','video','--json'),
                ('matrix','preflight','video-creation','--capability=render','--json'),
            ):
                with self.subTest(argv=argv):
                    result=adapter.discover(argv,cwd=root)
                    self.assertEqual(result.status,'PASS')
                    self.assertEqual(result.control_authority,'NONE')
                    self.assertEqual(result.payload['argv'],list(argv))

    def test_side_effecting_and_shell_like_surfaces_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); hub=executable(root,'cli-hub','print("ok")\n'); adapter=CliHubDiscoveryAdapter(hub,artifact_sha256=sha(hub))
            forbidden=(('install','gimp'),('update','gimp'),('uninstall','gimp'),('launch','gimp'),('matrix','install','video'),('previews','open','x'),('search','a;id'),('search','$(id)'))
            for argv in forbidden:
                with self.subTest(argv=argv), self.assertRaises(ToolImplementationError):
                    adapter.discover(argv,cwd=root)

    def test_unavailable_or_digest_mismatch_degrades_without_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); missing=root/'cli-hub'; adapter=CliHubDiscoveryAdapter(missing,artifact_sha256='a'*64)
            self.assertEqual(adapter.discover(('list','--json'),cwd=root).status,'UNAVAILABLE')
            hub=executable(root,'cli-hub','print("should-not-run")\n'); adapter=CliHubDiscoveryAdapter(hub,artifact_sha256='b'*64)
            self.assertEqual(adapter.discover(('list','--json'),cwd=root).status,'ARTIFACT_MISMATCH')

    def test_discovery_environment_is_isolated_and_analytics_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            hub=executable(root,'cli-hub','import json,os\nprint(json.dumps({"secret":os.getenv("AWS_SECRET_ACCESS_KEY"),"analytics":os.getenv("CLI_HUB_NO_ANALYTICS"),"home":os.getenv("HOME")}))\n')
            old=os.environ.get('AWS_SECRET_ACCESS_KEY'); os.environ['AWS_SECRET_ACCESS_KEY']='never-leak'
            try: result=CliHubDiscoveryAdapter(hub,artifact_sha256=sha(hub)).discover(('list','--json'),cwd=root)
            finally:
                if old is None: os.environ.pop('AWS_SECRET_ACCESS_KEY',None)
                else: os.environ['AWS_SECRET_ACCESS_KEY']=old
            self.assertIsNone(result.payload['secret'])
            self.assertEqual(result.payload['analytics'],'1')
            self.assertIn('.gch-cli-hub-home',result.payload['home'])


class CliAnythingGeneratorTests(unittest.TestCase):
    def test_generator_writes_candidate_only_inside_isolated_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); harness=root/'candidate'/'agent-harness'; harness.mkdir(parents=True)
            generator=root/'skill_generator.py'
            generator.write_text('import argparse,pathlib\np=argparse.ArgumentParser(); p.add_argument("harness"); p.add_argument("-o","--output"); a=p.parse_args(); pathlib.Path(a.output).write_text("candidate skill\\n")\n',encoding='utf-8')
            output=root/'generated'/'SKILL.md'; output.parent.mkdir()
            adapter=CliAnythingSkillGeneratorAdapter(generator,generator_sha256=sha(generator))
            result=adapter.generate_candidate(harness_path=harness,output_path=output,workspace_root=root)
            self.assertEqual(result.status,'CANDIDATE')
            self.assertEqual(result.control_authority,'NONE')
            self.assertFalse(result.generated_skill_qualified)
            self.assertRegex(result.artifact_sha256,r'^[0-9a-f]{64}$')
            self.assertEqual(output.read_text(),'candidate skill\n')

    def test_generator_unavailable_degrades_and_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); harness=root/'candidate'; harness.mkdir(); (root/'generated').mkdir(); output=root/'generated'/'SKILL.md'
            adapter=CliAnythingSkillGeneratorAdapter(root/'missing.py',generator_sha256='a'*64)
            result=adapter.generate_candidate(harness_path=harness,output_path=output,workspace_root=root)
            self.assertEqual(result.status,'UNAVAILABLE')
            self.assertEqual(result.control_authority,'NONE')
            self.assertFalse(output.exists())

    def test_generator_rejects_output_escape_and_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); harness=root/'candidate'; harness.mkdir(); generator=root/'g.py'; generator.write_text('print("x")\n')
            adapter=CliAnythingSkillGeneratorAdapter(generator,generator_sha256=sha(generator))
            with self.assertRaises(ToolImplementationError):
                adapter.generate_candidate(harness_path=harness,output_path=root.parent/'escape.md',workspace_root=root)
            mismatch=CliAnythingSkillGeneratorAdapter(generator,generator_sha256='f'*64)
            self.assertEqual(mismatch.generate_candidate(harness_path=harness,output_path=root/'generated'/'out.md',workspace_root=root).status,'ARTIFACT_MISMATCH')


if __name__=='__main__': unittest.main()
