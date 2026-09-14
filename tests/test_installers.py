from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
LINUX_INSTALLER = REPO_ROOT / "scripts" / "install-global-harness.sh"
POWERSHELL_INSTALLERS = (
    REPO_ROOT / "scripts" / "install-global-harness.ps1",
    REPO_ROOT / "scripts" / "install-meta-harness.ps1",
)


class InstallerContractTests(unittest.TestCase):
    def _source_repo(self, root: Path) -> tuple[Path, str]:
        source = root / "source"
        (source / ".agents").mkdir(parents=True)
        (source / "docs" / "harness").mkdir(parents=True)
        (source / "templates").mkdir()
        (source / "AGENTS.md").write_text("fixture\n", encoding="utf-8")
        (source / ".agents" / "README.md").write_text("fixture\n", encoding="utf-8")
        (source / "docs" / "harness" / "README.md").write_text("fixture\n", encoding="utf-8")
        (source / "templates" / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", "-b", "main", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "fixture@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-qm", "fixture"], check=True)
        head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        return source, head

    def test_linux_installer_clones_and_fast_forwards_main(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, first_head = self._source_repo(root)
            install_root = root / "install-root"
            target = install_root / "global-gpt-harness-engineering"
            subprocess.run(
                ["bash", str(LINUX_INSTALLER), str(source), str(install_root), target.name, "main"],
                check=True,
                capture_output=True,
                text=True,
            )
            installed_head = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
            self.assertEqual(installed_head, first_head)
            for relative in ("AGENTS.md", ".agents", "docs/harness", "templates"):
                self.assertTrue((target / relative).exists(), relative)

            (source / "AGENTS.md").write_text("fixture-v2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-qm", "fixture-v2"], check=True)
            second_head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
            subprocess.run(
                ["bash", str(LINUX_INSTALLER), str(source), str(install_root), target.name, "main"],
                check=True,
                capture_output=True,
                text=True,
            )
            updated_head = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
            self.assertEqual(updated_head, second_head)

    def test_powershell_installers_share_safe_main_update_contract(self) -> None:
        required_fragments = (
            '[string]$Branch = "main"',
            'Require-Command "git"',
            'git fetch origin $Branch',
            'git checkout $Branch',
            'git pull --ff-only origin $Branch',
            'git clone --branch $Branch $RepoUrl $targetPath',
            '"AGENTS.md"',
            '".agents"',
            '"docs\\harness"',
            '"templates"',
        )
        for script in POWERSHELL_INSTALLERS:
            with self.subTest(script=script.name):
                text = script.read_text(encoding="utf-8")
                for fragment in required_fragments:
                    self.assertIn(fragment, text)

    def test_powershell_installer_runtime_smoke_when_pwsh_available(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell runtime smoke requires pwsh; static contract coverage still runs")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, source_head = self._source_repo(root)
            install_root = root / "ps-install"
            script = POWERSHELL_INSTALLERS[0]
            subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-File",
                    str(script),
                    "-RepoUrl",
                    str(source),
                    "-InstallRoot",
                    str(install_root),
                    "-FolderName",
                    "global-gpt-harness-engineering",
                    "-Branch",
                    "main",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            target = install_root / "global-gpt-harness-engineering"
            installed_head = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
            self.assertEqual(installed_head, source_head)


if __name__ == "__main__":
    unittest.main()
