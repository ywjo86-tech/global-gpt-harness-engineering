"""Immutable, digest-bound manifests for candidate and qualified CLI implementations."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, replace
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,160}\Z")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_STATES = frozenset({"CANDIDATE", "QUALIFIED"})
_FORBIDDEN_COMMANDS = frozenset({"exec", "execute", "shell", "command", "raw-command", "run-command", "*"})
_FORBIDDEN_ARGV0 = frozenset({"sh", "bash", "dash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh"})
_FORBIDDEN_SCHEMA_KEYS = frozenset({"exec", "shell", "command", "raw_command", "argv", "argv0"})

class ToolImplementationError(ValueError):
    pass


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(_thaw(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolImplementationManifest:
    manifest_id: str
    state: str
    upstream_url: str
    upstream_ref: str
    upstream_commit: str
    generated_artifact_sha256: str
    allowed_argv0: str
    allowed_subcommands: Sequence[str]
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    effect_class: str
    verifier_sha256: str
    generated_skill_qualified: bool
    generated_skill_qualification_sha256: str
    qualification_evidence_sha256: str
    manifest_sha256: str


def _payload(manifest: ToolImplementationManifest, *, signed: bool) -> dict[str, Any]:
    result = {field.name: _thaw(getattr(manifest, field.name)) for field in fields(manifest)}
    if not signed:
        result.pop("manifest_sha256", None)
    return result


def _validate_schema(schema: Mapping[str, Any], label: str) -> None:
    if not isinstance(schema, Mapping) or schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ToolImplementationError(f"{label} must be a closed object schema")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, Mapping) or not isinstance(required, (list, tuple)):
        raise ToolImplementationError(f"{label} schema structure is invalid")
    if any(not isinstance(k, str) or not k for k in properties):
        raise ToolImplementationError(f"{label} property name is invalid")
    if any(str(k).lower() in _FORBIDDEN_SCHEMA_KEYS for k in properties):
        raise ToolImplementationError(f"{label} exposes an arbitrary command surface")
    if any(not isinstance(k, str) or k not in properties for k in required):
        raise ToolImplementationError(f"{label} required fields are invalid")


def validate_manifest(manifest: ToolImplementationManifest) -> None:
    if not isinstance(manifest, ToolImplementationManifest):
        raise ToolImplementationError("tool implementation manifest is invalid")
    if not _SAFE_ID.fullmatch(manifest.manifest_id):
        raise ToolImplementationError("unsafe manifest id")
    if manifest.state not in _STATES:
        raise ToolImplementationError("invalid manifest state")
    if not manifest.upstream_url.startswith("https://") or any(c.isspace() for c in manifest.upstream_url):
        raise ToolImplementationError("unsafe upstream URL")
    if not manifest.upstream_ref or any(c.isspace() for c in manifest.upstream_ref):
        raise ToolImplementationError("unsafe upstream ref")
    if not _COMMIT.fullmatch(manifest.upstream_commit):
        raise ToolImplementationError("invalid upstream commit")
    for name in ("generated_artifact_sha256", "verifier_sha256"):
        if not _SHA.fullmatch(str(getattr(manifest, name))):
            raise ToolImplementationError(f"invalid {name}")
    path = PurePosixPath(manifest.allowed_argv0)
    if (not path.is_absolute() or ".." in path.parts or path.as_posix() != manifest.allowed_argv0
            or path.name.lower() in _FORBIDDEN_ARGV0 or any(c.isspace() for c in manifest.allowed_argv0)):
        raise ToolImplementationError("unsafe CLI executable identity")
    commands = tuple(str(x) for x in manifest.allowed_subcommands)
    if not commands or len(set(commands)) != len(commands):
        raise ToolImplementationError("CLI subcommand allowlist is empty or duplicated")
    for command in commands:
        if not _SAFE_TOKEN.fullmatch(command) or command.lower() in _FORBIDDEN_COMMANDS:
            raise ToolImplementationError("unsafe CLI subcommand")
    _validate_schema(manifest.input_schema, "input")
    _validate_schema(manifest.output_schema, "output")
    if not _SAFE_ID.fullmatch(manifest.effect_class):
        raise ToolImplementationError("unsafe effect class")
    if not isinstance(manifest.generated_skill_qualified, bool):
        raise ToolImplementationError("generated skill qualification flag is invalid")
    skill_sha = manifest.generated_skill_qualification_sha256
    if manifest.generated_skill_qualified:
        if not _SHA.fullmatch(skill_sha):
            raise ToolImplementationError("generated skill cannot self-qualify")
    elif skill_sha:
        raise ToolImplementationError("generated skill qualification evidence is inconsistent")
    evidence = manifest.qualification_evidence_sha256
    if manifest.state == "QUALIFIED":
        if not _SHA.fullmatch(evidence):
            raise ToolImplementationError("qualified implementation lacks external evidence")
    elif evidence:
        raise ToolImplementationError("candidate cannot claim qualification evidence")
    expected = _digest(_payload(manifest, signed=False))
    if manifest.manifest_sha256 != expected:
        raise ToolImplementationError("manifest digest mismatch")


def seal_manifest(value: Mapping[str, Any] | ToolImplementationManifest) -> ToolImplementationManifest:
    raw = _payload(value, signed=True) if isinstance(value, ToolImplementationManifest) else dict(value)
    expected = {field.name for field in fields(ToolImplementationManifest)}
    if set(raw) != expected:
        raise ToolImplementationError("manifest fields mismatch")
    raw["allowed_subcommands"] = tuple(str(x) for x in raw["allowed_subcommands"])
    raw["input_schema"] = _freeze(raw["input_schema"])
    raw["output_schema"] = _freeze(raw["output_schema"])
    raw["manifest_sha256"] = ""
    manifest = ToolImplementationManifest(**raw)
    manifest = replace(manifest, manifest_sha256=_digest(_payload(manifest, signed=False)))
    validate_manifest(manifest)
    return manifest


def qualify_manifest(candidate: ToolImplementationManifest, qualification_evidence_sha256: str) -> ToolImplementationManifest:
    validate_manifest(candidate)
    if candidate.state != "CANDIDATE":
        raise ToolImplementationError("only a candidate can enter qualification")
    if not _SHA.fullmatch(str(qualification_evidence_sha256)):
        raise ToolImplementationError("external qualification evidence digest is invalid")
    return seal_manifest({**_payload(candidate, signed=True), "state": "QUALIFIED",
                          "qualification_evidence_sha256": str(qualification_evidence_sha256)})
