from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import PurePosixPath
from typing import Sequence

from .contracts import canonical_sha256

KINDS = {"UNIT", "INTEGRATION", "BUILD", "LINT"}


class ValidationProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidationProfile:
    profile_id: str
    kind: str
    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: int
    env_allowlist: tuple[str, ...]
    profile_digest: str = ""

    def unsigned(self) -> dict[str, object]:
        value = asdict(self); value.pop("profile_digest"); return value

    def sealed(self) -> "ValidationProfile":
        self.validate(require_digest=False)
        return replace(self, profile_digest=canonical_sha256(self.unsigned()))

    def validate(self, *, require_digest: bool = True) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id or self.kind not in KINDS:
            raise ValidationProfileError("profile identity/kind is invalid")
        if not self.argv or any(not isinstance(v, str) or not v or "\x00" in v for v in self.argv):
            raise ValidationProfileError("profile argv is invalid")
        path = PurePosixPath(self.cwd)
        if not isinstance(self.cwd, str) or path.is_absolute() or ".." in path.parts:
            raise ValidationProfileError("profile cwd must be workspace-relative")
        if not isinstance(self.timeout_seconds, int) or not 1 <= self.timeout_seconds <= 1800:
            raise ValidationProfileError("profile timeout is invalid")
        if len(self.env_allowlist) != len(set(self.env_allowlist)) or any(not isinstance(v, str) or not v for v in self.env_allowlist):
            raise ValidationProfileError("profile env allowlist is invalid")
        if require_digest and self.profile_digest != canonical_sha256(self.unsigned()):
            raise ValidationProfileError("profile digest mismatch")


class ValidationProfileCatalog:
    def __init__(self, profiles: Sequence[ValidationProfile]) -> None:
        self._profiles: dict[str, ValidationProfile] = {}
        for profile in profiles:
            profile.validate()
            if profile.profile_id in self._profiles:
                raise ValidationProfileError("duplicate profile id")
            self._profiles[profile.profile_id] = profile
        if not self._profiles:
            raise ValidationProfileError("profile catalog is empty")

    def get(self, profile_id: str) -> ValidationProfile:
        try: return self._profiles[profile_id]
        except KeyError as exc: raise ValidationProfileError("unknown profile id") from exc

    def digests(self) -> tuple[str, ...]:
        return tuple(sorted(profile.profile_digest for profile in self._profiles.values()))

    def profiles(self) -> tuple[ValidationProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))


def _profile(profile_id: str, kind: str, argv: Sequence[str], timeout: int) -> ValidationProfile:
    return ValidationProfile(profile_id, kind, tuple(argv), ".", timeout, ()).sealed()


def default_validation_profiles() -> tuple[ValidationProfile, ...]:
    return (
        _profile("VP-BOOTSTRAP-FULL-MCP", "INTEGRATION", ["python3", "-m", "unittest", "-q", "tests.full_mcp.test_gate_evidence.BootstrapQualificationTests"], 120),
        _profile("VP-VALIDATION-FOCUSED", "UNIT", ["python3", "-m", "unittest", "-q", "tests.full_mcp.test_validation.ValidationServiceFocusedTests"], 120),
        _profile("VP-UNIT-FULL-MCP", "UNIT", ["python3", "-m", "unittest", "-q", "tests.full_mcp.test_foundation", "tests.full_mcp.test_filesystem", "tests.full_mcp.test_process", "tests.full_mcp.test_git", "tests.full_mcp.test_validation", "tests.full_mcp.test_observability_recovery"], 300),
        _profile("VP-INTEGRATION-FULL-MCP", "INTEGRATION", ["python3", "-m", "unittest", "-q", "tests.full_mcp.test_runtime_server", "tests.full_mcp.test_adapter_contract"], 600),
        _profile("VP-BUILD-FULL-MCP", "BUILD", ["python3", "-m", "compileall", "-q", "runtime/full_mcp", "runtime/orchestrator/full_mcp_backend_adapter.py", "runtime/orchestrator/production_execution_gateway.py", "scripts/full_mcp_lint.py"], 120),
        _profile("VP-LINT-FULL-MCP", "LINT", ["python3", "scripts/full_mcp_lint.py", "runtime/full_mcp", "runtime/orchestrator/full_mcp_backend_adapter.py", "runtime/orchestrator/production_execution_gateway.py"], 120),
        _profile("VP-REGRESSION-HARNESS", "INTEGRATION", ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"], 1800),
        _profile("VP-PREFINAL-QUALIFICATION", "INTEGRATION", ["python3", "-m", "unittest", "-q", "tests.full_mcp.test_final_qualification.PreFinalQualificationTests"], 300),
        _profile("VP-FINAL-HANDOFF", "INTEGRATION", ["python3", "-m", "unittest", "-q", "tests.full_mcp.test_final_qualification.FinalHandoffQualificationTests"], 300),
    )


def default_validation_catalog() -> ValidationProfileCatalog:
    return ValidationProfileCatalog(default_validation_profiles())
