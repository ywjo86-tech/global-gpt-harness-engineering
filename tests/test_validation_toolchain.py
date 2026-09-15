import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.validation_toolchain import (
    ValidationToolchainError,
    resolve_validation_commands,
    validate_profile_resolution,
)


class ValidationToolchainTests(unittest.TestCase):
    def test_python_legacy_contract_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'.venv/bin').mkdir(parents=True); (root/'.venv/bin/python').write_text('')
            plan=resolve_validation_commands(root,['app/a.py','tests/test_a.py'])
            self.assertEqual(plan.profile_ids,('PYTHON_PYTEST',))
            self.assertEqual(plan.focused[0][:4],('.venv/bin/python','-m','pytest','-q'))

    def test_android_node_manifest_resolves_without_guessing_package_manager(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'gradlew').write_text('#!/bin/sh\n'); (root/'backend').mkdir()
            (root/'backend/package.json').write_text(json.dumps({'packageManager':'npm@11','scripts':{'test':'node --test','build':'tsc'}}))
            plan=resolve_validation_commands(root,['android-app/','backend/'])
            self.assertEqual(plan.profile_ids,('ANDROID_GRADLE_WRAPPER','NODE_NPM'))
            self.assertIn(('./gradlew','check'),plan.focused)
            self.assertIn(('npm','--prefix','backend','test'),plan.focused)
            self.assertIn(('npm','--prefix','backend','run','build'),plan.compile)

    def test_bootstrap_can_defer_missing_project_native_manifests(self):
        with tempfile.TemporaryDirectory() as d:
            plan=resolve_validation_commands(Path(d),['android-app/','backend/'],allow_deferred=True)
            self.assertTrue(plan.deferred)
            self.assertEqual(plan.profile_ids,('ANDROID_GRADLE_WRAPPER','NODE_PACKAGE_MANIFEST'))

    def test_cross_cutting_scope_uses_existing_project_manifests(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'gradlew').write_text('#!/bin/sh\n'); (root/'backend').mkdir()
            (root/'backend/package.json').write_text(json.dumps({'packageManager':'npm@11','scripts':{'test':'node --test','build':'tsc'}}))
            plan=resolve_validation_commands(root,['shared-contracts/curriculum/','tools/content-qa/'])
            self.assertEqual(plan.profile_ids,('ANDROID_GRADLE_WRAPPER','NODE_NPM'))

    def test_node_ambiguity_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'backend').mkdir(); (root/'backend/package-lock.json').write_text('{}'); (root/'backend/yarn.lock').write_text('')
            (root/'backend/package.json').write_text(json.dumps({'scripts':{'test':'x','build':'y'}}))
            with self.assertRaises(ValidationToolchainError):
                resolve_validation_commands(root,['backend/'])

    def test_sealed_deferred_profiles_must_resolve_without_expansion(self):
        validate_profile_resolution(['ANDROID_GRADLE_WRAPPER','NODE_PACKAGE_MANIFEST'],['ANDROID_GRADLE_WRAPPER','NODE_NPM'])
        with self.assertRaises(ValidationToolchainError):
            validate_profile_resolution(['ANDROID_GRADLE_WRAPPER'],['ANDROID_GRADLE_WRAPPER','NODE_NPM'])


if __name__ == '__main__': unittest.main()
