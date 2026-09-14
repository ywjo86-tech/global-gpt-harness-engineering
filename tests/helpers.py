from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from shutil import copytree
import sys
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = Path(sys.executable)
SAMPLE_PROJECT = REPO_ROOT / "runtime" / "examples" / "sample_project_contract"


@contextmanager
def cloned_sample_project():
    temp_dir = TemporaryDirectory()
    try:
        destination = Path(temp_dir.name) / "sample_project_contract"
        copytree(SAMPLE_PROJECT, destination)
        (destination / "logs").mkdir(exist_ok=True)
        (destination / "logs" / "app.log").write_text("sample validation log\n", encoding="utf-8")
        yield destination
    finally:
        temp_dir.cleanup()
