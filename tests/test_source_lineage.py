from __future__ import annotations
import subprocess, tempfile, unittest
from pathlib import Path
from runtime.orchestrator.gate_continuation_contract import GateContinuationContract
from tests.test_gate_continuation_contract import mapping


def git(root: Path,*args:str)->str:
    return subprocess.check_output(["git","-C",str(root),*args],text=True).strip()


def commit(root:Path,name:str,text:str)->str:
    (root/name).write_text(text)
    subprocess.run(["git","-C",str(root),"add",name],check=True)
    subprocess.run(["git","-C",str(root),"commit","-qm",f"add {name}"],check=True)
    return git(root,"rev-parse","HEAD")

class SourceLineageTests(unittest.TestCase):
    def make_repo(self, root:Path):
        subprocess.run(["git","init","-q",str(root)],check=True)
        subprocess.run(["git","-C",str(root),"config","user.email","t@example.com"],check=True)
        subprocess.run(["git","-C",str(root),"config","user.name","T"],check=True)
        base=commit(root,"base.txt","base\n"); child=commit(root,"child.txt","child\n")
        return base,child

    def api(self):
        try:
            from runtime.orchestrator.source_lineage import verify_source_lineage, SourceLineageError
        except ModuleNotFoundError as exc:
            self.fail(f"source lineage module missing: {exc}")
        return verify_source_lineage,SourceLineageError

    def contract(self,gate:str,base:str,policy:str):
        raw=mapping(gate,base); raw["source_lineage_policy"]=policy
        raw["allowed_write_paths"]=["child.txt","other.txt","orphan.txt"]
        return GateContinuationContract.from_mapping(raw)

    def test_exact_base_rejects_different_head(self):
        verify,Error=self.api()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); base,child=self.make_repo(root)
            with self.assertRaisesRegex(Error,"EXACT_BASE"):
                verify(self.contract("G",base,"EXACT_BASE"),root,current_head=child)

    def test_descendant_chain_accepts_linear_child_and_binds_tree_paths(self):
        verify,_=self.api()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); base,child=self.make_repo(root)
            ev=verify(self.contract("G",base,"APPROVED_DESCENDANT_CHAIN"),root,current_head=child)
            self.assertEqual(ev.current_head,child)
            self.assertEqual(ev.current_tree_sha256,git(root,"rev-parse",f"{child}^{{tree}}"))
            self.assertEqual(ev.changed_paths,("child.txt",))
            self.assertRegex(ev.changed_paths_sha256,r"^[0-9a-f]{64}$")

    def test_descendant_chain_rejects_wrong_previous_receipt(self):
        verify,Error=self.api()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); base,child=self.make_repo(root)
            subprocess.run(["git","-C",str(root),"checkout","-qb","other",base],check=True)
            other=commit(root,"other.txt","other\n")
            subprocess.run(["git","-C",str(root),"checkout","-q","master"],check=True)
            with self.assertRaisesRegex(Error,"previous receipt lineage"):
                verify(self.contract("G",base,"APPROVED_DESCENDANT_CHAIN"),root,
                       previous_receipt={"schema_version":"orchestration.operator-plan-receipt.v2","source_head":other},current_head=child)

    def test_non_descendant_current_head_fails(self):
        verify,Error=self.api()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); base,child=self.make_repo(root)
            subprocess.run(["git","-C",str(root),"checkout","--orphan","orphan"],check=True,stdout=subprocess.DEVNULL)
            subprocess.run(["git","-C",str(root),"rm","-rf","."],check=True,stdout=subprocess.DEVNULL)
            orphan=commit(root,"orphan.txt","x\n")
            with self.assertRaisesRegex(Error,"not a descendant"):
                verify(self.contract("G",base,"APPROVED_DESCENDANT_CHAIN"),root,current_head=orphan)

if __name__=="__main__": unittest.main()
