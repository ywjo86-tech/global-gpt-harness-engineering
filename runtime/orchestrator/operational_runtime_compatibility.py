"""Digest-bound compatibility contract for split Harness runtime services."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence

from .durable_io import atomic_write_json

RUNTIME_COMPATIBILITY_SCHEMA_V1 = "orchestration.operational-runtime-compatibility.v1"
RUNTIME_COMPATIBILITY_RESULT_V1 = "orchestration.operational-runtime-compatibility-result.v1"
_CURRENT = "CURRENT_RUNTIME"
_PINNED = "PINNED_COMPATIBLE"
_MODES = frozenset({_CURRENT, _PINNED})
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_UNIT = re.compile(r"[A-Za-z0-9_.@:-]+\.service\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,160}\Z")


class OperationalRuntimeCompatibilityError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: Mapping[str, Any], field: str) -> str:
    unsigned = {k: v for k, v in value.items() if k != field}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def build_runtime_compatibility_manifest(
    *,
    current_runtime_source_identity: str,
    releases_root: str | Path,
    components: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    current = str(current_runtime_source_identity or "").strip()
    if not _SHA40.fullmatch(current):
        raise OperationalRuntimeCompatibilityError("current runtime source invalid")
    root = Path(releases_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise OperationalRuntimeCompatibilityError("releases root invalid")
    rendered: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_units: set[str] = set()
    for raw in components:
        if not isinstance(raw, Mapping):
            raise OperationalRuntimeCompatibilityError("component mapping required")
        component_id = str(raw.get("component_id") or "").strip()
        unit = str(raw.get("unit") or "").strip()
        mode = str(raw.get("binding_mode") or "").strip()
        head = str(raw.get("expected_source_head") or "").strip()
        refs = raw.get("compatibility_evidence_refs")
        if (
            not _SAFE_ID.fullmatch(component_id)
            or component_id in seen_ids
            or not _SAFE_UNIT.fullmatch(unit)
            or unit in seen_units
            or mode not in _MODES
            or not _SHA40.fullmatch(head)
            or not isinstance(refs, (list, tuple))
            or any(not isinstance(item, str) or not item.strip() for item in refs)
        ):
            raise OperationalRuntimeCompatibilityError("component binding invalid")
        if mode == _CURRENT and head != current:
            raise OperationalRuntimeCompatibilityError(
                "current component must bind current runtime source"
            )
        if mode == _PINNED and not refs:
            raise OperationalRuntimeCompatibilityError(
                "pinned component requires compatibility evidence"
            )
        seen_ids.add(component_id)
        seen_units.add(unit)
        rendered.append({
            "component_id": component_id,
            "unit": unit,
            "binding_mode": mode,
            "expected_source_head": head,
            "compatibility_evidence_refs": list(refs),
        })
    if not rendered:
        raise OperationalRuntimeCompatibilityError("component bindings required")
    payload: dict[str, Any] = {
        "schema_version": RUNTIME_COMPATIBILITY_SCHEMA_V1,
        "current_runtime_source_identity": current,
        "releases_root": str(root),
        "components": sorted(rendered, key=lambda item: item["component_id"]),
    }
    payload["manifest_sha256"] = _digest(payload, "manifest_sha256")
    return validate_runtime_compatibility_manifest(payload)


def validate_runtime_compatibility_manifest(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperationalRuntimeCompatibilityError("manifest mapping required")
    raw = dict(value)
    required = {
        "schema_version",
        "current_runtime_source_identity",
        "releases_root",
        "components",
        "manifest_sha256",
    }
    if set(raw) != required or raw.get("schema_version") != RUNTIME_COMPATIBILITY_SCHEMA_V1:
        raise OperationalRuntimeCompatibilityError("manifest shape/schema mismatch")
    current = raw.get("current_runtime_source_identity")
    if not isinstance(current, str) or not _SHA40.fullmatch(current):
        raise OperationalRuntimeCompatibilityError("manifest current runtime invalid")
    root = Path(str(raw.get("releases_root") or "")).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise OperationalRuntimeCompatibilityError("manifest releases root invalid")
    components = raw.get("components")
    if not isinstance(components, list) or not components:
        raise OperationalRuntimeCompatibilityError("manifest components invalid")
    rebuilt = build_runtime_compatibility_manifest_unsealed(
        current=current,
        releases_root=root,
        components=components,
    )
    expected = hashlib.sha256(_canonical(rebuilt)).hexdigest()
    if raw.get("manifest_sha256") != expected:
        raise OperationalRuntimeCompatibilityError("manifest digest mismatch")
    return raw


def build_runtime_compatibility_manifest_unsealed(
    *,
    current: str,
    releases_root: Path,
    components: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    seen_ids: set[str] = set()
    seen_units: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in components:
        if not isinstance(item, Mapping):
            raise OperationalRuntimeCompatibilityError("component mapping invalid")
        if set(item) != {
            "component_id", "unit", "binding_mode",
            "expected_source_head", "compatibility_evidence_refs",
        }:
            raise OperationalRuntimeCompatibilityError("component shape mismatch")
        component_id = str(item["component_id"])
        unit = str(item["unit"])
        mode = str(item["binding_mode"])
        head = str(item["expected_source_head"])
        refs = item["compatibility_evidence_refs"]
        if (
            not _SAFE_ID.fullmatch(component_id)
            or component_id in seen_ids
            or not _SAFE_UNIT.fullmatch(unit)
            or unit in seen_units
            or mode not in _MODES
            or not _SHA40.fullmatch(head)
            or not isinstance(refs, list)
            or any(not isinstance(ref, str) or not ref for ref in refs)
            or (mode == _CURRENT and head != current)
            or (mode == _PINNED and not refs)
        ):
            raise OperationalRuntimeCompatibilityError("component binding invalid")
        seen_ids.add(component_id)
        seen_units.add(unit)
        normalized.append(dict(item))
    return {
        "schema_version": RUNTIME_COMPATIBILITY_SCHEMA_V1,
        "current_runtime_source_identity": current,
        "releases_root": str(releases_root),
        "components": sorted(normalized, key=lambda item: item["component_id"]),
    }


def record_runtime_compatibility_manifest(
    path: str | Path,
    manifest: Mapping[str, Any],
) -> Path:
    value = validate_runtime_compatibility_manifest(manifest)
    target = Path(path).expanduser().absolute()
    if target.exists() and target.is_symlink():
        raise OperationalRuntimeCompatibilityError("manifest output unsafe")
    return atomic_write_json(target, value)


def load_runtime_compatibility_manifest(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().absolute()
    if source.is_symlink() or not source.is_file():
        raise OperationalRuntimeCompatibilityError("manifest missing/unsafe")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperationalRuntimeCompatibilityError("manifest unreadable") from exc
    return validate_runtime_compatibility_manifest(value)


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    uid = os.getuid()
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    env = {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
        "XDG_RUNTIME_DIR": runtime_dir,
        "DBUS_SESSION_BUS_ADDRESS": (
            os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            or f"unix:path={runtime_dir}/bus"
        ),
    }
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        shell=False,
        timeout=10,
        env=env,
        check=False,
    )


def observe_unit_working_directory(
    unit: str,
    *,
    runner: Callable[[Sequence[str]], object] | None = None,
) -> Path:
    if not _SAFE_UNIT.fullmatch(unit):
        raise OperationalRuntimeCompatibilityError("unit invalid")
    control = runner or _default_runner
    try:
        completed = control((
            "systemctl", "--user", "show", unit,
            "--property=WorkingDirectory",
        ))
    except Exception as exc:
        raise OperationalRuntimeCompatibilityError("unit observation failed") from exc
    if getattr(completed, "returncode", None) != 0:
        raise OperationalRuntimeCompatibilityError("unit observation failed")
    stdout = getattr(completed, "stdout", "")
    lines = [line for line in str(stdout).splitlines() if line]
    if len(lines) != 1 or not lines[0].startswith("WorkingDirectory="):
        raise OperationalRuntimeCompatibilityError("unit observation invalid")
    raw = lines[0].split("=", 1)[1]
    if not raw:
        raise OperationalRuntimeCompatibilityError("unit working directory missing")
    path = Path(raw).expanduser()
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise OperationalRuntimeCompatibilityError(
            "unit working directory unavailable"
        ) from exc


def evaluate_runtime_compatibility(
    manifest: Mapping[str, Any],
    *,
    observed_working_directories: Mapping[str, str | Path] | None = None,
    runner: Callable[[Sequence[str]], object] | None = None,
    expected_current_runtime_source: str = "",
) -> dict[str, Any]:
    value = validate_runtime_compatibility_manifest(manifest)
    root = Path(value["releases_root"])
    failures: list[str] = []
    expected_current = str(expected_current_runtime_source or "").strip()
    if expected_current and value["current_runtime_source_identity"] != expected_current:
        failures.append("CURRENT_RUNTIME_SOURCE_MISMATCH")
    observations: list[dict[str, str]] = []
    supplied = dict(observed_working_directories or {})

    for component in value["components"]:
        unit = component["unit"]
        try:
            observed = (
                Path(supplied[unit]).expanduser().resolve(strict=True)
                if unit in supplied
                else observe_unit_working_directory(unit, runner=runner)
            )
        except (OSError, OperationalRuntimeCompatibilityError):
            failures.append(f"{component['component_id']}:WORKING_DIRECTORY_UNAVAILABLE")
            observations.append({
                "component_id": component["component_id"],
                "unit": unit,
                "expected_source_head": component["expected_source_head"],
                "observed_source_head": "UNAVAILABLE",
                "binding_mode": component["binding_mode"],
            })
            continue

        try:
            relative = observed.relative_to(root)
            observed_head = relative.parts[0] if len(relative.parts) == 1 else ""
        except ValueError:
            observed_head = ""
        if not _SHA40.fullmatch(observed_head):
            failures.append(f"{component['component_id']}:RELEASE_PATH_INVALID")
            observed_head = "INVALID"
        elif observed_head != component["expected_source_head"]:
            failures.append(f"{component['component_id']}:SOURCE_HEAD_MISMATCH")
        observations.append({
            "component_id": component["component_id"],
            "unit": unit,
            "expected_source_head": component["expected_source_head"],
            "observed_source_head": observed_head,
            "binding_mode": component["binding_mode"],
        })

    result: dict[str, Any] = {
        "schema_version": RUNTIME_COMPATIBILITY_RESULT_V1,
        "manifest_sha256": value["manifest_sha256"],
        "current_runtime_source_identity": value["current_runtime_source_identity"],
        "status": "PASS" if not failures else "BLOCKED",
        "failures": failures,
        "observations": observations,
    }
    result["result_sha256"] = _digest(result, "result_sha256")
    return result


def validate_runtime_compatibility_result(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperationalRuntimeCompatibilityError("compatibility result mapping required")
    raw = dict(value)
    required = {
        "schema_version",
        "manifest_sha256",
        "current_runtime_source_identity",
        "status",
        "failures",
        "observations",
        "result_sha256",
    }
    if set(raw) != required or raw.get("schema_version") != RUNTIME_COMPATIBILITY_RESULT_V1:
        raise OperationalRuntimeCompatibilityError("compatibility result shape/schema mismatch")
    if not isinstance(raw.get("manifest_sha256"), str) or not _SHA64.fullmatch(raw["manifest_sha256"]):
        raise OperationalRuntimeCompatibilityError("compatibility manifest digest invalid")
    if not isinstance(raw.get("current_runtime_source_identity"), str) or not _SHA40.fullmatch(raw["current_runtime_source_identity"]):
        raise OperationalRuntimeCompatibilityError("compatibility current runtime invalid")
    if raw.get("status") not in {"PASS", "BLOCKED"}:
        raise OperationalRuntimeCompatibilityError("compatibility status invalid")
    failures = raw.get("failures")
    observations = raw.get("observations")
    if not isinstance(failures, list) or any(not isinstance(item, str) or not item for item in failures):
        raise OperationalRuntimeCompatibilityError("compatibility failures invalid")
    if not isinstance(observations, list):
        raise OperationalRuntimeCompatibilityError("compatibility observations invalid")
    if raw["status"] == "PASS" and failures:
        raise OperationalRuntimeCompatibilityError("passing compatibility result has failures")
    if raw["status"] == "BLOCKED" and not failures:
        raise OperationalRuntimeCompatibilityError("blocked compatibility result lacks failures")
    for item in observations:
        if not isinstance(item, Mapping) or set(item) != {
            "component_id", "unit", "expected_source_head",
            "observed_source_head", "binding_mode",
        }:
            raise OperationalRuntimeCompatibilityError("compatibility observation invalid")
        if any(not isinstance(item[key], str) for key in item):
            raise OperationalRuntimeCompatibilityError("compatibility observation values invalid")
    digest = raw.get("result_sha256")
    if not isinstance(digest, str) or not _SHA64.fullmatch(digest):
        raise OperationalRuntimeCompatibilityError("compatibility result digest invalid")
    if digest != _digest(raw, "result_sha256"):
        raise OperationalRuntimeCompatibilityError("compatibility result digest mismatch")
    return raw


def record_runtime_compatibility_result(
    path: str | Path,
    result: Mapping[str, Any],
) -> Path:
    value = validate_runtime_compatibility_result(result)
    target = Path(path).expanduser().absolute()
    if target.exists() and target.is_symlink():
        raise OperationalRuntimeCompatibilityError(
            "compatibility result output unsafe"
        )
    return atomic_write_json(target, value)
