from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


class ProjectOnboardingError(ValueError):
    pass


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PLAN_CANDIDATES = ("IMPLEMENTATION_PLAN.md", "docs/DEVELOPMENT_PLAN.txt")
_ENTRY_FIELDS = {
    "schema_version", "alias", "project_id", "project_root", "canonical_plan",
    "canonical_plan_sha256", "entry_command", "controller_command_id", "controller_argv",
    "harness_shared", "launcher_mutation_required",
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verified_project(path: str | Path) -> Path:
    root = Path(path)
    if not root.is_absolute() or not root.is_dir() or root != root.resolve():
        raise ProjectOnboardingError("project root must be absolute, existing, and free of symlink components")
    if not _ID.fullmatch(root.name):
        raise ProjectOnboardingError("unsafe project ID")
    return root


def _plan(root: Path) -> Path | None:
    found = [root / relative for relative in _PLAN_CANDIDATES if (root / relative).is_file() and not (root / relative).is_symlink()]
    if len(found) > 1:
        raise ProjectOnboardingError("canonical plan is ambiguous")
    return found[0] if found else None


def build_alias_entry(project_root: str | Path, alias: str) -> dict[str, Any]:
    root = _verified_project(project_root)
    if not _ID.fullmatch(alias):
        raise ProjectOnboardingError("unsafe alias")
    plan = _plan(root)
    if plan is None:
        raise ProjectOnboardingError("canonical plan is absent; synthesis is forbidden")
    relative_plan = plan.relative_to(root).as_posix()
    return {
        "schema_version": "orchestration.project.alias.v1",
        "alias": alias,
        "project_id": root.name,
        "project_root": str(root),
        "canonical_plan": relative_plan,
        "canonical_plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "entry_command": [alias, "codex"],
        "controller_command_id": "GLOBAL_GATE_RUN",
        "controller_argv": ["python3", "-m", "runtime.orchestrator.cli", "gate-run"],
        "harness_shared": True,
        "launcher_mutation_required": False,
    }


def validate_alias_entry(entry: dict[str, Any], project_root: str | Path | None = None) -> None:
    if set(entry) != _ENTRY_FIELDS or entry.get("schema_version") != "orchestration.project.alias.v1":
        raise ProjectOnboardingError("alias entry field or schema mismatch")
    if not _ID.fullmatch(entry.get("alias", "")) or not _ID.fullmatch(entry.get("project_id", "")):
        raise ProjectOnboardingError("unsafe alias entry identity")
    if entry.get("entry_command") != [entry["alias"], "codex"]:
        raise ProjectOnboardingError("alias command contract mismatch")
    if entry.get("controller_command_id") != "GLOBAL_GATE_RUN" or entry.get("controller_argv") != ["python3", "-m", "runtime.orchestrator.cli", "gate-run"]:
        raise ProjectOnboardingError("common Harness controller contract mismatch")
    if entry.get("harness_shared") is not True or entry.get("launcher_mutation_required") is not False:
        raise ProjectOnboardingError("launcher/Harness sharing contract mismatch")
    root = _verified_project(project_root or entry["project_root"])
    if str(root) != entry["project_root"] or root.name != entry["project_id"]:
        raise ProjectOnboardingError("alias entry project binding mismatch")
    plan = _plan(root)
    if plan is None or plan.relative_to(root).as_posix() != entry["canonical_plan"]:
        raise ProjectOnboardingError("canonical plan binding mismatch")
    if hashlib.sha256(plan.read_bytes()).hexdigest() != entry["canonical_plan_sha256"]:
        raise ProjectOnboardingError("canonical plan SHA drift")


class OnboardingRegistry:
    """Alias-per-file declarative registry; entries are immutable after creation."""

    def __init__(self, root: str | Path):
        supplied = Path(root)
        if supplied.exists() and (not supplied.is_dir() or supplied.is_symlink()):
            raise ProjectOnboardingError("registry root is unsafe")
        self.root = supplied

    def entries(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        values: list[dict[str, Any]] = []
        aliases: set[str] = set()
        projects: dict[str, str] = {}
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink():
                raise ProjectOnboardingError("symlinked registry entry is forbidden")
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ProjectOnboardingError("registry entry is unreadable") from exc
            validate_alias_entry(entry)
            alias = entry["alias"]
            if path.name != f"{alias}.json" or alias in aliases:
                raise ProjectOnboardingError("alias collision in registry")
            prior = projects.get(entry["project_id"])
            if prior is not None and prior != alias:
                raise ProjectOnboardingError("project has conflicting aliases")
            aliases.add(alias); projects[entry["project_id"]] = alias; values.append(entry)
        return values

    def inspect(self, project_root: str | Path, alias: str) -> dict[str, Any]:
        root = _verified_project(project_root)
        existing = self.entries()
        collision = next((item for item in existing if item["alias"] == alias and item["project_id"] != root.name), None)
        if collision:
            return {"status": "ONBOARDING_BLOCKED", "reason": "alias collision", "mutation_performed": False}
        plan = _plan(root)
        if plan is None:
            return {
                "status": "ONBOARDING_REQUIRED", "reason": "canonical plan absent",
                "canonical_plan_synthesized": False, "mutation_performed": False,
            }
        candidate = build_alias_entry(root, alias)
        match = next((item for item in existing if item["alias"] == alias), None)
        if match is not None:
            validate_alias_entry(match, root)
            return {"status": "COMPATIBLE", "entry": match, "mutation_performed": False}
        return {"status": "REGISTRATION_READY", "entry": candidate, "mutation_performed": False}

    def register(self, project_root: str | Path, alias: str) -> dict[str, Any]:
        report = self.inspect(project_root, alias)
        if report["status"] != "REGISTRATION_READY":
            return report
        entry = report["entry"]
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{alias}.json"
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(_canonical(entry)); handle.flush(); os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ProjectOnboardingError("immutable alias entry already exists") from exc
        return {"status": "REGISTERED", "entry": entry, "mutation_performed": True}

    def bootstrap(
        self,
        project_root: str | Path,
        alias: str,
        *,
        mapping_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Create the minimum, production-shaped project contract and register it.

        This is deliberately a declarative bootstrap: it never invents a plan.  A
        caller must provide an existing canonical plan.  The isolated mapping root
        is separate from the alias registry because the contract adapter's mapping
        filenames are project IDs while this registry's filenames are aliases.
        """
        root = _verified_project(project_root)
        if mapping_root is None:
            mapping_dir = self.root.parent / "mappings"
        else:
            mapping_dir = Path(mapping_root)
        if not mapping_dir.is_absolute() or (mapping_dir.exists() and (mapping_dir.is_symlink() or not mapping_dir.is_dir())):
            raise ProjectOnboardingError("mapping root is unsafe")
        mapping_dir = mapping_dir.resolve()
        plan = _plan(root)
        if plan is None:
            return {"status": "ONBOARDING_REQUIRED", "reason": "canonical plan absent", "mutation_performed": False}
        # Bootstrap is intentionally idempotent, but never takes ownership of a
        # dirty repository or an existing entry that points elsewhere.
        git_dir = root / ".git"
        if git_dir.exists() and git_dir.is_symlink():
            raise ProjectOnboardingError("project .git must not be a symlink")
        if git_dir.exists():
            status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True)
            if status.stdout.strip():
                raise ProjectOnboardingError("project repository must be clean before bootstrap")
        contract_files = {
            "changelog": root / "CHANGELOG.txt",
            "app_log": root / "logs" / "app.log",
            "orchestration_state_md": root / "docs" / "harness" / "orchestration-state.md",
            "business_approval": root / "docs" / "APPROVAL_LOG.md",
            "gate_state": root / "docs" / "GATE_STATE.md",
            "gate_ledger": root / "docs" / "GATE_STATE.md",
        }
        defaults = {
            "changelog": "# Changelog\n",
            "app_log": "",
            "orchestration_state_md": "# Orchestration State\n\nCurrent phase: onboarding\n",
            "business_approval": "# Approval Log\n",
            "gate_state": "# Gate State\n\nStatus: FIRST_GATE_WAITING_APPROVAL\n",
        }
        created: list[Path] = []
        for key, path in contract_files.items():
            if key == "gate_ledger":
                continue
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise ProjectOnboardingError(f"bootstrap contract is not a regular file: {key}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(defaults[key], encoding="utf-8")
                created.append(path)
        plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
        mapping = {
            "project_id": root.name,
            "contract_paths": {
                "development_plan": plan.relative_to(root).as_posix(),
                "changelog": "CHANGELOG.txt",
                "app_log": "logs/app.log",
                "orchestration_state_md": "docs/harness/orchestration-state.md",
            },
            "required_contract_keys": ["development_plan", "changelog", "app_log", "orchestration_state_md"],
            "canonical_implementation_source": {"path": plan.relative_to(root).as_posix(), "sha256": plan_sha},
            "approved_source_reference": {"path": plan.relative_to(root).as_posix(), "sha256": plan_sha},
            "static_validation": {
                "business_lv_approval": "docs/APPROVAL_LOG.md",
                "gate_state": "docs/GATE_STATE.md",
                "gate_state_ledger": "docs/GATE_STATE.md",
            },
            "canonical_transition": {},
            "interpreter_policy_id": "IMMUTABLE_EXTERNAL_INTERPRETER",
        }
        mapping_dir.mkdir(parents=True, exist_ok=True)
        mapping_path = mapping_dir / f"{root.name}.json"
        if mapping_path.exists():
            if mapping_path.is_symlink() or mapping_path.read_bytes() != _canonical(mapping):
                raise ProjectOnboardingError("existing project mapping conflicts with bootstrap")
        else:
            mapping_path.write_bytes(_canonical(mapping)); created.append(mapping_path)
        alias_report = self.register(root, alias)
        if alias_report.get("status") not in {"REGISTERED", "COMPATIBLE"}:
            return alias_report
        if not git_dir.exists():
            subprocess.run(["git", "init", "-b", "main"], cwd=root, capture_output=True, text=True, check=True)
        subprocess.run(["git", "add", "--", plan.relative_to(root).as_posix(), "CHANGELOG.txt", "logs/app.log", "docs/harness/orchestration-state.md", "docs/APPROVAL_LOG.md", "docs/GATE_STATE.md"], cwd=root, capture_output=True, text=True, check=True)
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
        if staged:
            subprocess.run(["git", "-c", "user.name=Harness Bootstrap", "-c", "user.email=harness-bootstrap@localhost", "commit", "-m", "chore: bootstrap orchestration contract"], cwd=root, capture_output=True, text=True, check=True)
        created_names = [str(path.relative_to(root)) if path.is_relative_to(root) else str(path.relative_to(mapping_dir)) for path in created]
        return {"status": "BOOTSTRAPPED", "entry": alias_report.get("entry"), "mapping": mapping, "mapping_path": str(mapping_path), "created_files": created_names, "mutation_performed": bool(created or staged)}
