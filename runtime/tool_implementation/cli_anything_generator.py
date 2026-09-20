"""Isolated reference runner for CLI-Anything candidate skill generation."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .manifest import ToolImplementationError

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TIMEOUT = 60
_DEFAULT_OUTPUT_LIMIT = 256 * 1024


@dataclass(frozen=True, slots=True)
class CandidateSkillGenerationResult:
    status: str
    returncode: int | None
    output_path: str
    artifact_sha256: str
    stdout: str
    stderr: str
    generated_skill_qualified: bool = False
    control_authority: str = "NONE"


def _sha(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _child(root: Path, child: Path, label: str) -> Path:
    root_resolved = root.resolve()
    child_abs = child if child.is_absolute() else root_resolved / child
    child_abs = child_abs.absolute()
    try:
        child_abs.relative_to(root_resolved)
    except ValueError as exc:
        raise ToolImplementationError(f"{label} escapes isolated generator workspace") from exc
    return child_abs


def _isolated_env(root: Path) -> dict[str, str]:
    home=root/'.gch-generator-home'; xdg=root/'.gch-generator-xdg'
    home.mkdir(mode=0o700,exist_ok=True); xdg.mkdir(mode=0o700,exist_ok=True)
    return {
        "HOME":str(home), "XDG_CONFIG_HOME":str(xdg/'config'), "XDG_CACHE_HOME":str(xdg/'cache'),
        "XDG_DATA_HOME":str(xdg/'data'), "PATH":"/usr/local/bin:/usr/bin:/bin",
        "LANG":"C.UTF-8", "LC_ALL":"C.UTF-8", "PYTHONNOUSERSITE":"1",
    }


class CliAnythingSkillGeneratorAdapter:
    """Generates CANDIDATE skill artifacts only; it cannot register or activate them."""

    def __init__(self, generator_script: str | Path, *, generator_sha256: str,
                 python_executable: str | Path = sys.executable, timeout: int = 30,
                 max_output_bytes: int = _DEFAULT_OUTPUT_LIMIT) -> None:
        self.generator_script=Path(generator_script).expanduser().absolute()
        self.python_executable=Path(python_executable).expanduser().absolute()
        if not _SHA256.fullmatch(str(generator_sha256)):
            raise ToolImplementationError("CLI-Anything generator digest is invalid")
        if not isinstance(timeout,int) or timeout <= 0 or timeout > _MAX_TIMEOUT:
            raise ToolImplementationError("generator timeout is outside the bounded policy")
        if not isinstance(max_output_bytes,int) or max_output_bytes <= 0:
            raise ToolImplementationError("generator output limit is invalid")
        self.generator_sha256=str(generator_sha256); self.timeout=timeout; self.max_output_bytes=max_output_bytes

    def generate_candidate(self, *, harness_path: str | Path, output_path: str | Path,
                           workspace_root: str | Path) -> CandidateSkillGenerationResult:
        root=Path(workspace_root).resolve()
        if not root.is_dir() or root.is_symlink():
            raise ToolImplementationError("generator workspace is unsafe")
        harness=_child(root,Path(harness_path),"candidate harness")
        output=_child(root,Path(output_path),"candidate output")
        candidate_root=(root/'candidate').resolve(); generated_root=(root/'generated').resolve()
        try: harness.resolve().relative_to(candidate_root)
        except ValueError as exc: raise ToolImplementationError("candidate harness must be below workspace/candidate") from exc
        try: output.absolute().relative_to(generated_root)
        except ValueError as exc: raise ToolImplementationError("candidate output must be below workspace/generated") from exc
        if harness.is_symlink() or not harness.is_dir():
            raise ToolImplementationError("candidate harness is unsafe")
        output.parent.mkdir(parents=True,exist_ok=True)
        if output.exists() and (output.is_symlink() or not output.is_file()):
            raise ToolImplementationError("candidate output path is unsafe")
        actual=_sha(self.generator_script)
        if actual is None or not os.access(self.python_executable,os.X_OK):
            return CandidateSkillGenerationResult("UNAVAILABLE",None,str(output),"","","generator unavailable")
        if actual != self.generator_sha256:
            return CandidateSkillGenerationResult("ARTIFACT_MISMATCH",None,str(output),"","","generator digest mismatch")
        argv=[str(self.python_executable),"-I",str(self.generator_script),str(harness),"-o",str(output)]
        try:
            completed=subprocess.run(argv,cwd=root,env=_isolated_env(root),shell=False,capture_output=True,timeout=self.timeout,check=False)
        except OSError as exc:
            return CandidateSkillGenerationResult("UNAVAILABLE",None,str(output),"","",str(exc))
        except subprocess.TimeoutExpired as exc:
            return CandidateSkillGenerationResult("TIMEOUT",None,str(output),"","",str(exc))
        stdout_raw=bytes(completed.stdout or b""); stderr_raw=bytes(completed.stderr or b"")
        overflow=len(stdout_raw)>self.max_output_bytes or len(stderr_raw)>self.max_output_bytes
        stdout=stdout_raw[:self.max_output_bytes].decode('utf-8',errors='replace')
        stderr=stderr_raw[:self.max_output_bytes].decode('utf-8',errors='replace')
        if overflow:
            return CandidateSkillGenerationResult("OUTPUT_LIMIT_EXCEEDED",int(completed.returncode),str(output),"",stdout,stderr)
        if completed.returncode != 0:
            return CandidateSkillGenerationResult("FAIL",int(completed.returncode),str(output),"",stdout,stderr)
        artifact=_sha(output)
        if artifact is None:
            return CandidateSkillGenerationResult("VERIFY_FAIL",0,str(output),"",stdout,stderr)
        return CandidateSkillGenerationResult("CANDIDATE",0,str(output),artifact,stdout,stderr)
