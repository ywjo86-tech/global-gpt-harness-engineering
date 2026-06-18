from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = Path(r"C:\Users\ywjo8\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
SAMPLE_PROJECT = REPO_ROOT / "runtime" / "examples" / "sample_project_contract"


@contextmanager
def cloned_sample_project():
    temp_dir = TemporaryDirectory()
    try:
        destination = Path(temp_dir.name) / "sample_project_contract"
        copytree(SAMPLE_PROJECT, destination)
        yield destination
    finally:
        temp_dir.cleanup()

