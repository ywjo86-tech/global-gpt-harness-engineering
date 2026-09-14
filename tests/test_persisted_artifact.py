import json,os,tempfile,unittest
from pathlib import Path
from tests.test_production_lifecycle import binding
from runtime.orchestrator.persisted_artifact import PersistedArtifactError,publish,validate

SRC="a"*64;PRE="b"*64
class PersistedArtifactTests(unittest.TestCase):
 def fixture(self,d): publish(d,"run/package.json",kind="package",payload={"x":1},binding=binding(),source_artifact_sha256=SRC,predecessor_digest=PRE)
 def ok(self,d,**kw): return validate(d,"run/package.json",expected_kind="package",expected_binding=binding(),expected_source_sha256=SRC,expected_predecessor=PRE,**kw)
 def test_valid_bytes_only_are_returned(self):
  with tempfile.TemporaryDirectory() as d:self.fixture(d);self.assertEqual(self.ok(d).payload,{"x":1})
 def test_payload_tamper_and_metadata_only_match_fail(self):
  with tempfile.TemporaryDirectory() as d:
   self.fixture(d);p=Path(d)/"run/package.json";body=json.loads(p.read_text());body["payload"]={"x":2};p.write_text(json.dumps(body))
   with self.assertRaises(PersistedArtifactError):self.ok(d)
 def test_sidecar_tamper_wrong_sidecar_and_role_exchange_fail(self):
  for field,value in (("source_artifact_sha256","c"*64),("raw_payload_sha256","d"*64),("projection_sha256",None)):
   with tempfile.TemporaryDirectory() as d:
    self.fixture(d);p=Path(d)/"run/package.json.sidecar.json";s=json.loads(p.read_text());s[field]=s["raw_payload_sha256"] if value is None else value;p.write_text(json.dumps(s))
    with self.assertRaises(PersistedArtifactError):self.ok(d)
 def test_path_swap_after_open_uses_validated_bytes_and_symlink_swap_fails(self):
  with tempfile.TemporaryDirectory() as d:
   self.fixture(d);p=Path(d)/"run/package.json";result=self.ok(d,after_open=lambda _:p.write_text("{}"));self.assertEqual(result.payload,{"x":1})
  with tempfile.TemporaryDirectory() as d:
   self.fixture(d);p=Path(d)/"run/package.json";p.unlink();p.symlink_to("other")
   with self.assertRaises(PersistedArtifactError):self.ok(d)
 def test_corrupt_unsupported_traversal_and_wrong_lineage_fail(self):
  with tempfile.TemporaryDirectory() as d:
   self.fixture(d);(Path(d)/"run/package.json").write_text("{")
   with self.assertRaises(PersistedArtifactError):self.ok(d)
  with tempfile.TemporaryDirectory() as d:
   self.fixture(d)
   for kwargs in ({"expected_kind":"review"},{"expected_source_sha256":"c"*64},{"expected_predecessor":"c"*64}):
    base=dict(expected_kind="package",expected_binding=binding(),expected_source_sha256=SRC,expected_predecessor=PRE);base.update(kwargs)
    with self.assertRaises(PersistedArtifactError):validate(d,"run/package.json",**base)
   with self.assertRaises(PersistedArtifactError):validate(d,"../x",expected_kind="package",expected_binding=binding(),expected_source_sha256=SRC,expected_predecessor=PRE)
