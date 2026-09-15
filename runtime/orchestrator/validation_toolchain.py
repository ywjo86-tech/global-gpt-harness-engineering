from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence


class ValidationToolchainError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationCommandSet:
    profile_ids: tuple[str, ...]
    focused: tuple[tuple[str, ...], ...]
    full: tuple[tuple[str, ...], ...]
    compile: tuple[tuple[str, ...], ...]
    deferred: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_ids": list(self.profile_ids),
            "focused": [list(item) for item in self.focused],
            "full": [list(item) for item in self.full],
            "compile": [list(item) for item in self.compile],
            "deferred": self.deferred,
        }


def _scope_flags(owned_files: Sequence[str]) -> tuple[bool, bool, bool]:
    android = any(
        path in {"settings.gradle.kts", "gradle/libs.versions.toml"}
        or path.startswith("android-app/") or path == "android-app/"
        for path in owned_files
    )
    node = any(path.startswith("backend/") or path == "backend/" for path in owned_files)
    python = any(path.endswith(".py") or path.startswith("tests/") for path in owned_files)
    return android, node, python


def _safe_regular_file(root: Path, path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    current = path.parent
    while current != root:
        if current.is_symlink():
            return False
        if root not in current.parents and current != root:
            return False
        current = current.parent
    return True


def _nested_wrapper_pinned(root: Path) -> bool:
    jar = root / "android-app" / "gradle" / "wrapper" / "gradle-wrapper.jar"
    props = root / "android-app" / "gradle" / "wrapper" / "gradle-wrapper.properties"
    if not _safe_regular_file(root, jar) or not _safe_regular_file(root, props):
        return False
    try:
        values = {}
        for raw in props.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    except (OSError, UnicodeError):
        return False
    url = values.get("distributionUrl", "")
    digest = values.get("distributionSha256Sum", "")
    return bool(re.search(r"/gradle-[0-9]+(?:\.[0-9]+)+(?:-[A-Za-z0-9.-]+)?-bin\.zip$", url)) and bool(re.fullmatch(r"[0-9a-f]{64}", digest))


def _android_runner(root: Path) -> tuple[str, tuple[str, ...]]:
    root_wrapper = root / "gradlew"
    if _safe_regular_file(root, root_wrapper):
        return "ANDROID_GRADLE_WRAPPER", ("./gradlew",)
    nested_wrapper = root / "android-app" / "gradlew"
    if _safe_regular_file(root, nested_wrapper) and _nested_wrapper_pinned(root):
        # The wrapper lives inside the approved android-app/ scope while the
        # canonical Gradle project root remains the repository root. Invoking
        # through sh avoids requiring executable-bit mutation from the bounded
        # text-write transport.
        return "ANDROID_GRADLE_WRAPPER", ("sh", "android-app/gradlew", "-p", ".")
    system_gradle = shutil.which("gradle")
    if system_gradle:
        resolved = Path(system_gradle).resolve()
        try:
            inside_workspace = resolved.is_relative_to(root)
        except AttributeError:
            inside_workspace = root == resolved or root in resolved.parents
        if resolved.is_file() and not inside_workspace:
            return "ANDROID_GRADLE_SYSTEM_BOOTSTRAP", (str(resolved), "--no-daemon")
    raise ValidationToolchainError("Android owned scope requires a complete pinned Gradle wrapper or trusted system Gradle bootstrap")


def _node_runner(root: Path) -> tuple[str, tuple[str, ...]]:
    package = root / "backend" / "package.json"
    if not package.is_file() or package.is_symlink():
        raise ValidationToolchainError("backend package.json is missing or unsafe")
    try:
        payload = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationToolchainError("backend package.json is malformed") from exc
    scripts = payload.get("scripts")
    if not isinstance(scripts, Mapping) or not isinstance(scripts.get("test"), str) or not scripts["test"].strip():
        raise ValidationToolchainError("backend package.json must declare a non-empty test script")
    if not isinstance(scripts.get("build"), str) or not scripts["build"].strip():
        raise ValidationToolchainError("backend package.json must declare a non-empty build script")
    manager = payload.get("packageManager")
    name = str(manager).split("@", 1)[0] if isinstance(manager, str) and manager else ""
    if not name:
        locks = [("npm", root / "backend" / "package-lock.json"),
                 ("pnpm", root / "backend" / "pnpm-lock.yaml"),
                 ("yarn", root / "backend" / "yarn.lock")]
        present = [candidate for candidate, path in locks if path.is_file() and not path.is_symlink()]
        if len(present) != 1:
            raise ValidationToolchainError("backend package manager is not uniquely declared")
        name = present[0]
    if name == "npm":
        return "NODE_NPM", ("npm", "--prefix", "backend")
    if name == "pnpm":
        return "NODE_PNPM", ("pnpm", "--dir", "backend")
    if name == "yarn":
        return "NODE_YARN", ("yarn", "--cwd", "backend")
    raise ValidationToolchainError(f"unsupported backend package manager: {name}")


def resolve_validation_commands(root: Path, owned_files: Sequence[str], *, allow_deferred: bool = False) -> ValidationCommandSet:
    android, node, python_scope = _scope_flags(owned_files)
    profiles: list[str] = []
    focused: list[tuple[str, ...]] = []
    full: list[tuple[str, ...]] = []
    compile_commands: list[tuple[str, ...]] = []
    deferred = False

    if android:
        try:
            android_profile, gradle_prefix = _android_runner(root)
        except ValidationToolchainError:
            if allow_deferred:
                profiles.append("ANDROID_GRADLE_BOOTSTRAP")
                deferred = True
            else:
                raise
        else:
            profiles.append(android_profile)
            focused.append((*gradle_prefix, "check"))
            full.append((*gradle_prefix, "check"))
            compile_commands.append((*gradle_prefix, "assembleDebug"))

    if node:
        try:
            node_profile, prefix = _node_runner(root)
        except ValidationToolchainError:
            if allow_deferred and not (root / "backend" / "package.json").exists():
                profiles.append("NODE_PACKAGE_MANIFEST")
                deferred = True
            else:
                raise
        else:
            profiles.append(node_profile)
            focused.append((*prefix, "test"))
            full.append((*prefix, "test"))
            compile_commands.append((*prefix, "run", "build"))

    py_tests = [path for path in owned_files if path.startswith("tests/") and path.endswith(".py")]
    if python_scope and not android and not node:
        interpreter = root / ".venv" / "bin" / "python"
        if py_tests:
            profiles.append("PYTHON_PYTEST")
            focused.append((".venv/bin/python", "-m", "pytest", "-q", *py_tests))
            full.append((".venv/bin/python", "-m", "pytest", "-q"))
            py_owned = [path for path in owned_files if path.endswith(".py")]
            compile_commands.append((".venv/bin/python", "-m", "compileall", "-q", *py_owned))
            if not interpreter.is_file():
                if allow_deferred:
                    deferred = True
                else:
                    raise ValidationToolchainError("Python owned scope requires project venv")
        elif allow_deferred:
            profiles.append("PYTHON_PYTEST")
            deferred = True
        else:
            raise ValidationToolchainError("Python owned scope requires owned focused tests")

    if not profiles:
        if not owned_files:
            return ValidationCommandSet((), (), (), (), False)
        manifest_scopes: list[str] = []
        try:
            _android_runner(root)
        except ValidationToolchainError:
            pass
        else:
            manifest_scopes.append("android-app/")
        if (root / "backend" / "package.json").is_file() and not (root / "backend" / "package.json").is_symlink():
            manifest_scopes.append("backend/")
        if manifest_scopes:
            return resolve_validation_commands(root, manifest_scopes, allow_deferred=False)
        if allow_deferred:
            return ValidationCommandSet(("PROJECT_NATIVE_UNRESOLVED",), (), (), (), True)
        raise ValidationToolchainError("no project-native validation toolchain matches owned scope or project manifests")
    if not deferred and (not focused or not full or not compile_commands):
        raise ValidationToolchainError("project-native validation toolchain is incomplete")
    return ValidationCommandSet(tuple(profiles), tuple(focused), tuple(full), tuple(compile_commands), deferred)


def run_command_group(
    root: Path,
    commands: Sequence[Sequence[str]],
    runner: Callable[[Path, list[str]], Mapping[str, Any]],
) -> dict[str, Any]:
    if not commands:
        return {"command": ["not-applicable"], "exit_code": 0, "timeout": False, "skipped": True, "steps": []}
    steps: list[dict[str, Any]] = []
    final_code: int | None = 0
    timed_out = False
    spawn_error = False
    for command in commands:
        result = dict(runner(root, list(command)))
        steps.append(result)
        if result.get("spawn_error"):
            spawn_error = True; final_code = None; break
        if result.get("timeout"):
            timed_out = True; final_code = result.get("exit_code"); break
        if result.get("exit_code") != 0:
            final_code = result.get("exit_code"); break
    payload: dict[str, Any] = {
        "command": (list(steps[0].get("command", ["project-native-validation-group"]))
                    if len(steps) == 1 else ["project-native-validation-group"]),
        "exit_code": final_code,
        "timeout": timed_out,
        "steps": steps,
    }
    if len(steps) == 1:
        for key, value in steps[0].items():
            if key.startswith("test_") or key in {"collection_failure_phase", "import_failure_family", "dependency_presence_class"}:
                payload[key] = value
    if spawn_error:
        payload["spawn_error"] = True
    return payload


def validate_profile_resolution(expected: Sequence[str], actual: Sequence[str]) -> None:
    expected_set = set(expected)
    actual_set = set(actual)
    if "ANDROID_GRADLE_WRAPPER" in expected_set and "ANDROID_GRADLE_WRAPPER" not in actual_set:
        raise ValidationToolchainError("Android validation profile did not resolve")
    if "ANDROID_GRADLE_BOOTSTRAP" in expected_set and not ({"ANDROID_GRADLE_WRAPPER", "ANDROID_GRADLE_SYSTEM_BOOTSTRAP"} & actual_set):
        raise ValidationToolchainError("Android bootstrap validation profile did not resolve")
    if "PYTHON_PYTEST" in expected_set and "PYTHON_PYTEST" not in actual_set:
        raise ValidationToolchainError("Python validation profile did not resolve")
    if "NODE_PACKAGE_MANIFEST" in expected_set and not any(item.startswith("NODE_") for item in actual_set):
        raise ValidationToolchainError("Node validation profile did not resolve")
    explicit_node = {item for item in expected_set if item.startswith("NODE_") and item != "NODE_PACKAGE_MANIFEST"}
    if explicit_node and not explicit_node.issubset(actual_set):
        raise ValidationToolchainError("Node validation profile changed after sealing")
    if "PROJECT_NATIVE_UNRESOLVED" not in expected_set:
        allowed = set(expected_set)
        if "ANDROID_GRADLE_BOOTSTRAP" in allowed:
            allowed.remove("ANDROID_GRADLE_BOOTSTRAP")
            allowed.update(item for item in actual_set if item in {"ANDROID_GRADLE_WRAPPER", "ANDROID_GRADLE_SYSTEM_BOOTSTRAP"})
        if "NODE_PACKAGE_MANIFEST" in allowed:
            allowed.remove("NODE_PACKAGE_MANIFEST")
            allowed.update(item for item in actual_set if item.startswith("NODE_"))
        if not actual_set.issubset(allowed):
            raise ValidationToolchainError("post-worker validation profile expanded beyond sealed scope")
