import dataclasses
import unittest

from runtime.tool_implementation.manifest import (
    ToolImplementationError, ToolImplementationManifest, qualify_manifest,
    seal_manifest, validate_manifest,
)

SHA='a'*64

def base(**overrides):
    value={
        'manifest_id':'CLI_ANYTHING_ECHO_V1','state':'CANDIDATE',
        'upstream_url':'https://github.com/HKUDS/CLI-Anything.git','upstream_ref':'HEAD',
        'upstream_commit':'810c18b0d1ab9b234bc996c9fd999318523a3ef0',
        'generated_artifact_sha256':'b'*64,'allowed_argv0':'/opt/gch-tools/echo-cli',
        'allowed_subcommands':('inspect','render'),
        'input_schema':{'type':'object','properties':{'subcommand':{'type':'string'},'value':{'type':'string'}},'required':['subcommand'],'additionalProperties':False},
        'output_schema':{'type':'object','properties':{'status':{'type':'string'}},'required':['status'],'additionalProperties':False},
        'effect_class':'READ_ONLY','verifier_sha256':'c'*64,
        'generated_skill_qualified':False,'generated_skill_qualification_sha256':'',
        'qualification_evidence_sha256':'','manifest_sha256':'',
    }
    value.update(overrides); return value

class ManifestTests(unittest.TestCase):
    def test_candidate_round_trip_is_digest_bound_and_frozen(self):
        m=seal_manifest(base()); validate_manifest(m)
        self.assertRegex(m.manifest_sha256,r'^[0-9a-f]{64}$')
        with self.assertRaises(dataclasses.FrozenInstanceError): m.state='QUALIFIED'

    def test_qualified_requires_external_qualification_evidence(self):
        m=seal_manifest(base())
        with self.assertRaises(ToolImplementationError): qualify_manifest(m,'')
        q=qualify_manifest(m,'d'*64); self.assertEqual(q.state,'QUALIFIED'); validate_manifest(q)

    def test_bad_digest_fails_closed(self):
        m=seal_manifest(base()); object.__setattr__(m,'manifest_sha256','0'*64)
        with self.assertRaises(ToolImplementationError): validate_manifest(m)

    def test_generic_shell_or_command_surfaces_are_rejected(self):
        for argv0,subs in [('/bin/sh',('inspect',)),('/opt/tool',('exec',)),('/opt/tool',('shell',)),('/opt/tool',('command',)),('/opt/tool',('*',))]:
            with self.subTest(argv0=argv0,subs=subs), self.assertRaises(ToolImplementationError): seal_manifest(base(allowed_argv0=argv0,allowed_subcommands=subs))

    def test_command_identity_rejects_traversal_and_relative_path(self):
        for argv0 in ('../tool','tool','/opt/../bin/tool'):
            with self.subTest(argv0=argv0), self.assertRaises(ToolImplementationError): seal_manifest(base(allowed_argv0=argv0))

    def test_closed_schemas_are_mandatory(self):
        for field in ('input_schema','output_schema'):
            bad=dict(base()[field]); bad['additionalProperties']=True
            with self.subTest(field=field), self.assertRaises(ToolImplementationError): seal_manifest(base(**{field:bad}))

    def test_source_and_artifact_hashes_are_mandatory(self):
        for field,value in [('upstream_commit','bad'),('generated_artifact_sha256','bad'),('verifier_sha256','bad')]:
            with self.subTest(field=field), self.assertRaises(ToolImplementationError): seal_manifest(base(**{field:value}))

    def test_generated_skill_cannot_self_qualify(self):
        with self.assertRaises(ToolImplementationError): seal_manifest(base(generated_skill_qualified=True))
        m=seal_manifest(base(generated_skill_qualified=True,generated_skill_qualification_sha256='e'*64))
        self.assertTrue(m.generated_skill_qualified)

    def test_unknown_fields_cannot_construct_manifest(self):
        with self.assertRaises(TypeError): ToolImplementationManifest(**base(), surprise='x')

if __name__=='__main__': unittest.main()
