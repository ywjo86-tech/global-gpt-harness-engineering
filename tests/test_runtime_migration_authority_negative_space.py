import ast,unittest
from pathlib import Path
class RuntimeMigrationAuthorityNegativeSpaceTests(unittest.TestCase):
 def test_migration_module_has_no_forbidden_authority_calls(self):
  p=Path('runtime/orchestrator/runtime_migration_handoff.py'); tree=ast.parse(p.read_text())
  calls={n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,(ast.Attribute,ast.Name))}
  for forbidden in {'select_provider','execute_with_private_result','create_pass_receipt','complete','publish','resume_operator_plan_after_receipt'}:
   self.assertNotIn(forbidden,calls)
 def test_migration_module_does_not_import_authority_layers(self):
  text=Path('runtime/orchestrator/runtime_migration_handoff.py').read_text()
  for forbidden in ('provider_router','tool_authorization','completion_authority','production_attention'):
   self.assertNotIn(forbidden,text)
if __name__=='__main__': unittest.main()
