import json
import os
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

    def test_explicit_pytest_profile_is_not_changed_by_active_external_venv(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as e:
            root=Path(d)
            with patch.dict(os.environ, {'VIRTUAL_ENV': e}):
                plan=resolve_validation_commands(
                    root,['tests/test_a.py'],allow_deferred=True,validation_profile='PYTEST_PROFILE'
                )
            self.assertTrue(plan.deferred)
            self.assertEqual(plan.profile_ids,('PYTEST_PROFILE',))
            self.assertEqual(plan.focused[0],('.venv/bin/python','-m','pytest','-q','tests/test_a.py'))

    def test_active_venv_is_not_implicit_python_validation_intent(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as e:
            root=Path(d)
            with patch.dict(os.environ, {'VIRTUAL_ENV': e}):
                with self.assertRaisesRegex(ValidationToolchainError,'project venv or approved external interpreter'):
                    resolve_validation_commands(root,['tests/test_a.py'],allow_deferred=False)

    def test_explicit_external_python_is_exactly_bound_and_must_be_outside_project(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as e:
            root=Path(d); external=Path(e)/'python'; external.write_text(''); external.chmod(0o755)
            plan=resolve_validation_commands(root,['tests/test_a.py'],python_executable=external)
            self.assertEqual(plan.profile_ids,('PYTHON_UNITTEST_EXTERNAL',))
            self.assertEqual(plan.focused[0][0],str(external))
            inside=root/'python'; inside.write_text(''); inside.chmod(0o755)
            with self.assertRaisesRegex(ValidationToolchainError,'outside project root'):
                resolve_validation_commands(root,['tests/test_a.py'],python_executable=inside)

    def test_explicit_external_unittest_profile_uses_bound_interpreter_over_project_venv(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as e:
            root=Path(d); (root/'.venv/bin').mkdir(parents=True); (root/'.venv/bin/python').write_text('')
            external=Path(e)/'python'; external.write_text(''); external.chmod(0o755)
            plan=resolve_validation_commands(
                root,['tests/test_a.py'],python_executable=external,
                validation_profile='EXTERNAL_UNITTEST_PROFILE',
            )
            self.assertEqual(plan.profile_ids,('EXTERNAL_UNITTEST_PROFILE',))
            self.assertEqual(plan.focused[0],(str(external),'-m','unittest','-v','tests.test_a'))
            validate_profile_resolution(['EXTERNAL_UNITTEST_PROFILE'],plan.profile_ids)

    def test_explicit_pytest_profile_is_deterministic_across_python_environments(self):
        from unittest.mock import patch
        expected={
            "profile_ids":["PYTEST_PROFILE"],
            "focused":[[".venv/bin/python","-m","pytest","-q","tests/test_a.py"]],
            "full":[[".venv/bin/python","-m","pytest","-q"]],
            "compile":[[".venv/bin/python","-m","compileall","-q","tests/test_a.py"]],
            "deferred":True,
        }
        with tempfile.TemporaryDirectory() as d:
            system=resolve_validation_commands(Path(d),["tests/test_a.py"],allow_deferred=True,validation_profile="PYTEST_PROFILE")
        with tempfile.TemporaryDirectory() as d:
            project_root=Path(d); (project_root/".venv/bin").mkdir(parents=True); (project_root/".venv/bin/python").write_text("")
            project=resolve_validation_commands(project_root,["tests/test_a.py"],allow_deferred=True,validation_profile="PYTEST_PROFILE")
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as e:
            temporary_root=Path(d)
            with patch.dict(os.environ, {"VIRTUAL_ENV": e}):
                temporary=resolve_validation_commands(temporary_root,["tests/test_a.py"],allow_deferred=True,validation_profile="PYTEST_PROFILE")
        self.assertEqual(system.to_dict(),expected)
        self.assertEqual(project.to_dict(),expected)
        self.assertEqual(temporary.to_dict(),expected)

    def test_explicit_pytest_profile_respects_non_deferred_intent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'.venv/bin').mkdir(parents=True); (root/'.venv/bin/python').write_text('')
            plan=resolve_validation_commands(root,['tests/test_a.py'],allow_deferred=False,validation_profile='PYTEST_PROFILE')
            self.assertFalse(plan.deferred)
            self.assertEqual(plan.profile_ids,('PYTEST_PROFILE',))

    def test_android_node_manifest_resolves_without_guessing_package_manager(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'gradlew').write_text('#!/bin/sh\n'); (root/'backend').mkdir()
            (root/'backend/package.json').write_text(json.dumps({'packageManager':'npm@11','scripts':{'test':'node --test','build':'tsc'}}))
            plan=resolve_validation_commands(root,['android-app/','backend/'])
            self.assertEqual(plan.profile_ids,('ANDROID_GRADLE_WRAPPER','NODE_NPM'))
            self.assertIn(('./gradlew','check'),plan.focused)
            self.assertIn(('npm','--prefix','backend','test'),plan.focused)
            self.assertIn(('npm','--prefix','backend','run','build'),plan.compile)

    def test_nested_android_wrapper_inside_owned_scope_is_supported_and_pinned(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); wrapper=root/'android-app/gradle/wrapper'; wrapper.mkdir(parents=True)
            (root/'android-app/gradlew').write_text('#!/bin/sh\n')
            (wrapper/'gradle-wrapper.jar').write_bytes(b'wrapper')
            (wrapper/'gradle-wrapper.properties').write_text(
                'distributionUrl=https://services.gradle.org/distributions/gradle-9.6.0-bin.zip\n'
                'distributionSha256Sum=' + 'a'*64 + '\n'
            )
            plan=resolve_validation_commands(root,['settings.gradle.kts','gradle/libs.versions.toml','android-app/'])
            self.assertEqual(plan.profile_ids,('ANDROID_GRADLE_WRAPPER',))
            self.assertIn(('sh','android-app/gradlew','-p','.','check'),plan.focused)
            self.assertIn(('sh','android-app/gradlew','-p','.','assembleDebug'),plan.compile)

    def test_nested_android_wrapper_without_jar_or_checksum_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); wrapper=root/'android-app/gradle/wrapper'; wrapper.mkdir(parents=True)
            (root/'android-app/gradlew').write_text('#!/bin/sh\n')
            (wrapper/'gradle-wrapper.properties').write_text(
                'distributionUrl=https://services.gradle.org/distributions/gradle-9.6.0-bin.zip\n'
            )
            with self.assertRaisesRegex(ValidationToolchainError,'complete pinned Gradle wrapper'):
                resolve_validation_commands(root,['android-app/'])

    def test_trusted_system_gradle_can_satisfy_android_bootstrap_without_project_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); tool=Path(d).parent/'trusted-gradle-test-bin'; tool.write_text('#!/bin/sh\n')
            try:
                from unittest.mock import patch
                with patch('runtime.orchestrator.validation_toolchain.shutil.which', return_value=str(tool)):
                    plan=resolve_validation_commands(root,['settings.gradle.kts','android-app/'])
                self.assertEqual(plan.profile_ids,('ANDROID_GRADLE_SYSTEM_BOOTSTRAP',))
                self.assertEqual(plan.focused[0][1:],('--no-daemon','check'))
                validate_profile_resolution(['ANDROID_GRADLE_BOOTSTRAP'],plan.profile_ids)
            finally:
                tool.unlink(missing_ok=True)

    def test_bootstrap_can_defer_missing_project_native_manifests(self):
        with tempfile.TemporaryDirectory() as d:
            from unittest.mock import patch
            with patch('runtime.orchestrator.validation_toolchain.shutil.which', return_value=None):
                plan=resolve_validation_commands(Path(d),['android-app/','backend/'],allow_deferred=True)
            self.assertTrue(plan.deferred)
            self.assertEqual(plan.profile_ids,('ANDROID_GRADLE_BOOTSTRAP','NODE_PACKAGE_MANIFEST'))

    def test_cross_cutting_scope_uses_existing_project_manifests(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'gradlew').write_text('#!/bin/sh\n'); (root/'backend').mkdir()
            (root/'backend/package.json').write_text(json.dumps({'packageManager':'npm@11','scripts':{'test':'node --test','build':'tsc'}}))
            plan=resolve_validation_commands(root,['shared-contracts/curriculum/','tools/content-qa/'])
            self.assertEqual(plan.profile_ids,('ANDROID_GRADLE_WRAPPER','NODE_NPM'))

    def test_document_only_scope_does_not_infer_android_from_system_gradle_alone(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); tool=root.parent/'trusted-gradle-doc-only'; tool.write_text('#!/bin/sh\n')
            try:
                from unittest.mock import patch
                with patch('runtime.orchestrator.validation_toolchain.shutil.which', return_value=str(tool)):
                    plan=resolve_validation_commands(
                        root, ['docs/history/upgrades/PROJECT/'], allow_deferred=True
                    )
                self.assertEqual(plan.profile_ids, ('DOCUMENT_EVIDENCE',))
                self.assertFalse(plan.deferred)
                with patch('runtime.orchestrator.validation_toolchain.shutil.which', return_value=str(tool)):
                    resolved=resolve_validation_commands(root, ['docs/history/upgrades/PROJECT/'], allow_deferred=False)
                self.assertEqual(resolved.profile_ids, ('DOCUMENT_EVIDENCE',))
            finally:
                tool.unlink(missing_ok=True)

    def test_node_ambiguity_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'backend').mkdir(); (root/'backend/package-lock.json').write_text('{}'); (root/'backend/yarn.lock').write_text('')
            (root/'backend/package.json').write_text(json.dumps({'scripts':{'test':'x','build':'y'}}))
            with self.assertRaises(ValidationToolchainError):
                resolve_validation_commands(root,['backend/'])

    def test_sealed_deferred_profiles_must_resolve_without_expansion(self):
        validate_profile_resolution(['ANDROID_GRADLE_BOOTSTRAP','NODE_PACKAGE_MANIFEST'],['ANDROID_GRADLE_WRAPPER','NODE_NPM'])
        validate_profile_resolution(['PYTEST_PROFILE'],['PYTEST_PROFILE'])
        validate_profile_resolution(['EXTERNAL_UNITTEST_PROFILE'],['EXTERNAL_UNITTEST_PROFILE'])
        with self.assertRaises(ValidationToolchainError):
            validate_profile_resolution(['EXTERNAL_UNITTEST_PROFILE'],['PYTHON_UNITTEST_EXTERNAL'])
        with self.assertRaises(ValidationToolchainError):
            validate_profile_resolution(['ANDROID_GRADLE_BOOTSTRAP'],['ANDROID_GRADLE_WRAPPER','NODE_NPM'])

    def test_documentation_only_scope_does_not_inherit_project_toolchain(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'docs/history').mkdir(parents=True)
            plan=resolve_validation_commands(root,['docs/history/'])
            self.assertEqual(plan.profile_ids,('DOCUMENT_EVIDENCE',))
            self.assertEqual(plan.focused,(('git','diff','--check'),))
            self.assertEqual(plan.full,(('git','diff','--check'),))
            self.assertEqual(plan.compile,(('git','diff','--check'),))
            self.assertFalse(plan.deferred)


if __name__ == '__main__': unittest.main()
