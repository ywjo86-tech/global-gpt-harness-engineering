from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from .codex_dynamic_transport import (
    PINNED_CODEX_VERSION,
    TRANSPORT_CONTRACT_VERSION,
    CodexAppServerAdapter,
)
from .execution_contract import (
    ALWAYS_BEFORE_CODEX_LAUNCH,
    READY,
    CodexAuthReadinessEvidence,
    codex_launch_binding_digest,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
NOT_READY = "NOT_READY"


class CodexReadinessError(RuntimeError):
    def __init__(self, message: str, *, reason_taxonomy: str) -> None:
        super().__init__(message)
        self.reason_taxonomy = reason_taxonomy


@dataclass(frozen=True, slots=True)
class ReadinessProbeSet:
    version_probe: Callable[[], str]
    schema_probe: Callable[[], tuple[Mapping[str, bool], str]]
    environment_probe: Callable[[], str]
    auth_probe: Callable[[], str]


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CodexReadinessError(
            "readiness evidence is not canonically serializable",
            reason_taxonomy="CODEX_READINESS_EVIDENCE_INVALID",
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value.strip()):
        raise CodexReadinessError(
            f"{field} is not an exact SHA-256 value",
            reason_taxonomy="CODEX_READINESS_PROBE_INVALID",
        )
    return value.strip()


def probe_codex_auth_status(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Return only bounded READY/NOT_READY; never persist raw auth output."""
    try:
        completed = runner(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return NOT_READY

    combined = "\n".join(
        part.strip()
        for part in (completed.stdout or "", completed.stderr or "")
        if part and part.strip()
    )
    if completed.returncode == 0 and combined == "Logged in using ChatGPT":
        return READY
    return NOT_READY


def probe_transport_schema_digest(
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> tuple[Mapping[str, bool], str]:
    """Generate the same App Server schema, return bounded checks + SHA-256 only."""
    try:
        with tempfile.TemporaryDirectory(prefix="codex-readiness-schema-") as directory:
            completed = runner(
                ["codex", "app-server", "generate-json-schema", "--experimental", "--out", directory],
                capture_output=True,
                check=False,
                timeout=30,
            )
            bundle = Path(directory) / "codex_app_server_protocol.schemas.json"
            if completed.returncode != 0 or not bundle.is_file():
                raise CodexReadinessError(
                    "Codex schema generation failed",
                    reason_taxonomy="CODEX_SCHEMA_COMPATIBILITY_BLOCK",
                )
            raw = bundle.read_bytes()
    except CodexReadinessError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise CodexReadinessError(
            "Codex schema generation failed",
            reason_taxonomy="CODEX_SCHEMA_COMPATIBILITY_BLOCK",
        ) from exc

    checks = {
        "experimental_api": b'"experimentalApi"' in raw,
        "dynamic_tool_request": b'"item/tool/call"' in raw and b'"dynamicTools"' in raw,
        "dynamic_tool_response": b'"contentItems"' in raw,
        "empty_environment_supported": b'"environments"' in raw
        and b"Empty disables environment access" in raw,
    }
    bounded = {**checks, "schema_verified": all(checks.values())}
    return bounded, hashlib.sha256(raw).hexdigest()


def probe_secret_free_environment_fingerprint(
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    """Fingerprint bounded non-secret facts; never raw PATH or home values."""
    located = which("codex")
    if not isinstance(located, str) or not located.strip():
        raise CodexReadinessError(
            "Codex executable is unavailable",
            reason_taxonomy="CODEX_ENVIRONMENT_UNAVAILABLE",
        )

    try:
        resolved = Path(located).expanduser().resolve(strict=True)
    except OSError as exc:
        raise CodexReadinessError(
            "Codex executable cannot be resolved",
            reason_taxonomy="CODEX_ENVIRONMENT_UNAVAILABLE",
        ) from exc

    if not resolved.is_file():
        raise CodexReadinessError(
            "Codex executable is not a regular file",
            reason_taxonomy="CODEX_ENVIRONMENT_UNAVAILABLE",
        )

    try:
        binary_sha = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        raise CodexReadinessError(
            "Codex executable cannot be fingerprinted",
            reason_taxonomy="CODEX_ENVIRONMENT_UNAVAILABLE",
        ) from exc

    realpath_sha = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    facts = {
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "codex_binary_sha256": binary_sha,
        "codex_realpath_sha256": realpath_sha,
        "transport_contract_version": TRANSPORT_CONTRACT_VERSION,
    }
    return _digest(facts)


def default_probe_set() -> ReadinessProbeSet:
    return ReadinessProbeSet(
        version_probe=CodexAppServerAdapter._probe_version,
        schema_probe=probe_transport_schema_digest,
        environment_probe=probe_secret_free_environment_fingerprint,
        auth_probe=probe_codex_auth_status,
    )


def collect_codex_auth_readiness(
    *,
    run_id: str,
    worker_task_id: str,
    package_id: str,
    package_revision: int,
    probes: ReadinessProbeSet | None = None,
    verified_at_utc: str | None = None,
) -> CodexAuthReadinessEvidence:
    if not all(
        isinstance(value, str) and value.strip()
        for value in (run_id, worker_task_id, package_id)
    ):
        raise CodexReadinessError(
            "launch binding identifiers are required",
            reason_taxonomy="CODEX_LAUNCH_BINDING_INVALID",
        )
    if not isinstance(package_revision, int) or package_revision < 1:
        raise CodexReadinessError(
            "package revision is invalid",
            reason_taxonomy="CODEX_LAUNCH_BINDING_INVALID",
        )

    probes = probes or default_probe_set()
    try:
        cli_version = probes.version_probe()
        checks, schema_digest = probes.schema_probe()
        environment_fingerprint = probes.environment_probe()
        auth_status = probes.auth_probe()
    except CodexReadinessError:
        raise
    except Exception as exc:
        raise CodexReadinessError(
            "Codex readiness probe failed",
            reason_taxonomy="CODEX_READINESS_PROBE_UNRESOLVED",
        ) from exc

    if cli_version != PINNED_CODEX_VERSION:
        raise CodexReadinessError(
            "Codex CLI version drifted from the pinned transport",
            reason_taxonomy="CODEX_CLI_VERSION_DRIFT",
        )

    if not isinstance(checks, Mapping) or not checks.get("schema_verified"):
        raise CodexReadinessError(
            "Codex transport schema is not compatible",
            reason_taxonomy="CODEX_SCHEMA_COMPATIBILITY_BLOCK",
        )

    schema_digest = _require_sha256(str(schema_digest), "transport_schema_digest")
    environment_fingerprint = _require_sha256(
        str(environment_fingerprint), "environment_fingerprint"
    )

    if auth_status not in {READY, NOT_READY}:
        raise CodexReadinessError(
            "Codex auth probe returned an unbounded status",
            reason_taxonomy="CODEX_AUTH_STATUS_INVALID",
        )

    launch_binding = codex_launch_binding_digest(
        cli_version=cli_version,
        environment_fingerprint=environment_fingerprint,
        transport_schema_digest=schema_digest,
        run_id=run_id.strip(),
        worker_task_id=worker_task_id.strip(),
        package_id=package_id.strip(),
        package_revision=package_revision,
    )

    timestamp = (verified_at_utc or _utc_now()).strip()
    source_refs = (
        f"cli-version://{cli_version}",
        f"environment://sha256/{environment_fingerprint}",
        f"transport-schema://sha256/{schema_digest}",
        f"auth-status://{auth_status}",
    )
    evidence_id = "CAE-" + _digest(
        {
            "verified_at_utc": timestamp,
            "cli_version": cli_version,
            "environment_fingerprint": environment_fingerprint,
            "transport_schema_digest": schema_digest,
            "auth_status": auth_status,
            "source_evidence_refs": list(source_refs),
            "recheck_policy": ALWAYS_BEFORE_CODEX_LAUNCH,
            "launch_binding_digest": launch_binding,
        }
    )[:32]

    return CodexAuthReadinessEvidence(
        evidence_id=evidence_id,
        verified_at_utc=timestamp,
        cli_version=cli_version,
        environment_fingerprint=environment_fingerprint,
        transport_schema_digest=schema_digest,
        auth_status=auth_status,
        source_evidence_refs=source_refs,
        recheck_policy=ALWAYS_BEFORE_CODEX_LAUNCH,
        launch_binding_digest=launch_binding,
    )


def recheck_codex_auth_readiness(
    expected: CodexAuthReadinessEvidence,
    *,
    run_id: str,
    worker_task_id: str,
    package_id: str,
    package_revision: int,
    probes: ReadinessProbeSet | None = None,
    verified_at_utc: str | None = None,
) -> CodexAuthReadinessEvidence:
    """Re-probe immediately before launch and require exact stable-fact compatibility."""
    current = collect_codex_auth_readiness(
        run_id=run_id,
        worker_task_id=worker_task_id,
        package_id=package_id,
        package_revision=package_revision,
        probes=probes,
        verified_at_utc=verified_at_utc,
    )

    if expected.auth_status != READY or current.auth_status != READY:
        raise CodexReadinessError(
            "Codex auth readiness is not READY",
            reason_taxonomy="CODEX_AUTH_NOT_READY",
        )

    for field in (
        "cli_version",
        "environment_fingerprint",
        "transport_schema_digest",
        "recheck_policy",
        "launch_binding_digest",
    ):
        if getattr(expected, field) != getattr(current, field):
            raise CodexReadinessError(
                f"Codex readiness drift detected: {field}",
                reason_taxonomy="CODEX_READINESS_STALE_OR_DRIFTED",
            )
    return current
