from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


BACKEND_LAUNCHER_COMPATIBILITY_FAILED = "BACKEND_LAUNCHER_COMPATIBILITY_FAILED"

CLI_NOT_FOUND = "CLI_NOT_FOUND"
COMPATIBILITY_FAILED = "COMPATIBILITY_FAILED"
TIMEOUT = "TIMEOUT"
CANCELLED = "CANCELLED"
NONZERO_EXIT = "NONZERO_EXIT"
STRUCTURED_OUTPUT_MISSING = "STRUCTURED_OUTPUT_MISSING"
STRUCTURED_OUTPUT_INVALID = "STRUCTURED_OUTPUT_INVALID"
ABNORMAL_SUCCESS_AMBIGUITY = "ABNORMAL_SUCCESS_AMBIGUITY"

READ_ONLY_SANDBOX = "read-only"
WORKSPACE_WRITE_SANDBOX = "workspace-write"

STATE_CHANGING_CAPABILITIES = frozenset(
    {
        "filesystem_write",
        "shell",
        "test",
        "git",
        "implementation",
        "integration",
    }
)

REQUIRED_DEFAULT_OPTIONS = (
    "exec_subcommand",
    "stdin_prompt",
    "cwd_option",
    "sandbox_option",
    "output_schema_option",
    "output_last_message_option",
)

COMPATIBILITY_VERIFIED = "COMPATIBILITY_VERIFIED"

PROBE_EXECUTABLE_MISSING = "PROBE_EXECUTABLE_MISSING"
PROBE_VERSION_FAILED = "PROBE_VERSION_FAILED"
PROBE_EXEC_HELP_FAILED = "PROBE_EXEC_HELP_FAILED"
PROBE_REQUIRED_CAPABILITY_MISSING = "PROBE_REQUIRED_CAPABILITY_MISSING"
OVERRIDE_PARSE_FAILED = "OVERRIDE_PARSE_FAILED"
OVERRIDE_AMBIGUOUS = "OVERRIDE_AMBIGUOUS"
OVERRIDE_LEGACY_UNSUPPORTED = "OVERRIDE_LEGACY_UNSUPPORTED"
OVERRIDE_DANGEROUS_BYPASS = "OVERRIDE_DANGEROUS_BYPASS"
OVERRIDE_PROMPT_IN_ARGV = "OVERRIDE_PROMPT_IN_ARGV"
OVERRIDE_REQUIRED_OPTION_MISSING = "OVERRIDE_REQUIRED_OPTION_MISSING"
PROCESS_SPAWN_FAILED = "PROCESS_SPAWN_FAILED"

COMPATIBILITY_FAILURE_CLASSES = frozenset(
    {
        CLI_NOT_FOUND,
        COMPATIBILITY_FAILED,
        PROBE_EXECUTABLE_MISSING,
        PROBE_VERSION_FAILED,
        PROBE_EXEC_HELP_FAILED,
        PROBE_REQUIRED_CAPABILITY_MISSING,
        OVERRIDE_PARSE_FAILED,
        OVERRIDE_AMBIGUOUS,
        OVERRIDE_LEGACY_UNSUPPORTED,
        OVERRIDE_DANGEROUS_BYPASS,
        OVERRIDE_PROMPT_IN_ARGV,
        OVERRIDE_REQUIRED_OPTION_MISSING,
        PROCESS_SPAWN_FAILED,
    }
)

DANGEROUS_FLAGS = frozenset(
    {
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
    }
)

LEGACY_UNSUPPORTED_FLAGS = frozenset({"--prompt-file", "--output-dir"})


class CodexLauncherError(RuntimeError):
    """Typed launcher/process failure with stable taxonomy."""

    def __init__(self, failure_class: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.status = (
            BACKEND_LAUNCHER_COMPATIBILITY_FAILED
            if failure_class in COMPATIBILITY_FAILURE_CLASSES
            else failure_class
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "failure_class": self.failure_class,
            "message": str(self),
        }


@dataclass(frozen=True, slots=True)
class CodexCliCapabilityManifest:
    executable_detected: bool
    executable_path_fingerprint: str
    cli_version: str
    exec_subcommand: bool
    stdin_prompt: bool
    cwd_option: bool
    sandbox_option: bool
    output_schema_option: bool
    output_last_message_option: bool
    json_events_option: bool
    probe_returncodes: dict[str, int | None]
    status: str
    failure_class: str | None = None
    missing_capabilities: tuple[str, ...] = ()
    _executable_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("_executable_path", None)
        return payload


@dataclass(frozen=True, slots=True)
class CodexLauncherInvocation:
    argv: tuple[str, ...]
    stdin_mode: str
    sandbox_mode: str
    output_schema_path: str
    final_output_path: str
    json_events: bool
    timeout_seconds: int = 600
    retry: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CodexProcessResult:
    status: str
    failure_class: str | None
    returncode: int | None
    timed_out: bool
    cancelled: bool
    killed: bool
    duration_seconds: float
    stdout: str
    stderr: str
    final_output_path: str
    final_output_exists: bool
    structured_output_valid: bool | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=15)


def _fingerprint_path(path: str) -> str:
    if not path:
        return ""
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def _bounded_text(value: str | None, limit: int = 20000) -> str:
    if not value:
        return ""
    return value[:limit]


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _probe_status(values: Mapping[str, bool], executable_detected: bool) -> str:
    if not executable_detected:
        return BACKEND_LAUNCHER_COMPATIBILITY_FAILED
    missing = [name for name in REQUIRED_DEFAULT_OPTIONS if not values.get(name, False)]
    if missing:
        return BACKEND_LAUNCHER_COMPATIBILITY_FAILED
    return COMPATIBILITY_VERIFIED


def _probe_failure_class(
    values: Mapping[str, bool],
    executable_detected: bool,
    probe_returncodes: Mapping[str, int | None],
) -> str | None:
    if not executable_detected:
        return PROBE_EXECUTABLE_MISSING
    if probe_returncodes.get("codex --version") != 0:
        return PROBE_VERSION_FAILED
    if probe_returncodes.get("codex exec --help") != 0:
        return PROBE_EXEC_HELP_FAILED
    if [name for name in REQUIRED_DEFAULT_OPTIONS if not values.get(name, False)]:
        return PROBE_REQUIRED_CAPABILITY_MISSING
    return None


def probe_codex_cli_capabilities(
    executable_resolver: Callable[[str], str | None] | None = None,
    runner: Runner | None = None,
) -> CodexCliCapabilityManifest:
    resolver = executable_resolver or shutil.which
    run = runner or _default_runner
    executable = resolver("codex")
    probe_returncodes: dict[str, int | None] = {
        "codex --version": None,
        "codex exec --help": None,
    }
    version_output = ""
    help_output = ""

    if not executable:
        return CodexCliCapabilityManifest(
            executable_detected=False,
            executable_path_fingerprint="",
            cli_version="",
            exec_subcommand=False,
            stdin_prompt=False,
            cwd_option=False,
            sandbox_option=False,
            output_schema_option=False,
            output_last_message_option=False,
            json_events_option=False,
            probe_returncodes=probe_returncodes,
            status=BACKEND_LAUNCHER_COMPATIBILITY_FAILED,
            failure_class=PROBE_EXECUTABLE_MISSING,
            _executable_path="",
        )

    try:
        version_probe = run([executable, "--version"])
        probe_returncodes["codex --version"] = version_probe.returncode
        version_output = _bounded_text((version_probe.stdout or "") + (version_probe.stderr or ""))
    except (OSError, subprocess.SubprocessError):
        probe_returncodes["codex --version"] = None

    try:
        help_probe = run([executable, "exec", "--help"])
        probe_returncodes["codex exec --help"] = help_probe.returncode
        help_output = _bounded_text((help_probe.stdout or "") + (help_probe.stderr or ""))
    except (OSError, subprocess.SubprocessError):
        probe_returncodes["codex exec --help"] = None

    help_succeeded = probe_returncodes["codex exec --help"] == 0
    version = ""
    for line in version_output.splitlines():
        stripped = line.strip()
        if stripped and not stripped.upper().startswith("WARNING:"):
            version = stripped
            break

    values = {
        "exec_subcommand": help_succeeded and _contains_any(help_output, ["Usage: codex exec", "codex exec [OPTIONS]"]),
        "stdin_prompt": help_succeeded and "read from stdin" in help_output and "-" in help_output,
        "cwd_option": help_succeeded and "-C," in help_output and "--cd" in help_output,
        "sandbox_option": help_succeeded and "--sandbox" in help_output and READ_ONLY_SANDBOX in help_output and WORKSPACE_WRITE_SANDBOX in help_output,
        "output_schema_option": help_succeeded and "--output-schema" in help_output,
        "output_last_message_option": help_succeeded and "--output-last-message" in help_output and "-o," in help_output,
        "json_events_option": help_succeeded and "--json" in help_output,
    }
    missing = tuple(name for name in REQUIRED_DEFAULT_OPTIONS if not values.get(name, False))

    failure_class = _probe_failure_class(values, True, probe_returncodes)
    return CodexCliCapabilityManifest(
        executable_detected=True,
        executable_path_fingerprint=_fingerprint_path(executable),
        cli_version=version,
        exec_subcommand=values["exec_subcommand"],
        stdin_prompt=values["stdin_prompt"],
        cwd_option=values["cwd_option"],
        sandbox_option=values["sandbox_option"],
        output_schema_option=values["output_schema_option"],
        output_last_message_option=values["output_last_message_option"],
        json_events_option=values["json_events_option"],
        probe_returncodes=probe_returncodes,
        status=BACKEND_LAUNCHER_COMPATIBILITY_FAILED if failure_class else COMPATIBILITY_VERIFIED,
        failure_class=failure_class,
        missing_capabilities=missing,
        _executable_path=executable,
    )


def sandbox_for_capabilities(required_capabilities: Iterable[str] | None) -> str:
    normalized = {str(item).strip() for item in (required_capabilities or ()) if str(item).strip()}
    if STATE_CHANGING_CAPABILITIES.intersection(normalized):
        return WORKSPACE_WRITE_SANDBOX
    return READ_ONLY_SANDBOX


def _assert_manifest_compatible(manifest: CodexCliCapabilityManifest) -> None:
    if manifest.status != COMPATIBILITY_VERIFIED:
        detail = f" ({manifest.failure_class})" if manifest.failure_class else ""
        raise CodexLauncherError(COMPATIBILITY_FAILED, f"Codex CLI capability probe did not verify the required contract{detail}.")
    missing = [name for name in REQUIRED_DEFAULT_OPTIONS if not bool(getattr(manifest, name))]
    if missing:
        raise CodexLauncherError(COMPATIBILITY_FAILED, f"Codex CLI capability probe is missing required options: {', '.join(missing)}")


def _default_schema_path(output_dir: Path) -> Path:
    return output_dir / "codex_output_schema.json"


def _default_final_output_path(output_dir: Path) -> Path:
    return output_dir / "codex_last_message.json"


def _option_value(argv: Sequence[str], names: frozenset[str]) -> str | None:
    for index, token in enumerate(argv):
        if token in names:
            if index + 1 >= len(argv):
                return None
            return argv[index + 1]
        for name in names:
            prefix = name + "="
            if token.startswith(prefix):
                return token[len(prefix) :]
    return None


def _has_option(argv: Sequence[str], names: frozenset[str]) -> bool:
    return _option_value(argv, names) is not None


def _resolved_path_text(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _manifest_executable_path(manifest: CodexCliCapabilityManifest) -> str:
    executable = getattr(manifest, "_executable_path", "")
    if executable:
        return executable
    current = shutil.which("codex")
    if current and _fingerprint_path(current) == manifest.executable_path_fingerprint:
        return current
    raise CodexLauncherError(COMPATIBILITY_FAILED, "Codex CLI executable path is unavailable from capability resolution.")


def _resolve_override_executable(executable: str) -> str | None:
    if os.sep in executable or (os.altsep and os.altsep in executable):
        return str(Path(executable).expanduser())
    return shutil.which(executable)


def _validate_override_executable(argv0: str, expected_executable: str) -> None:
    if _resolve_override_executable(argv0) != expected_executable:
        raise CodexLauncherError(COMPATIBILITY_FAILED, "Codex override executable does not match the probed Codex CLI capability.")


def _validate_override_path(
    argv: Sequence[str],
    names: frozenset[str],
    expected_path: Path,
    message: str,
) -> None:
    value = _option_value(argv, names)
    if value is None or _resolved_path_text(value) != _resolved_path_text(expected_path):
        raise CodexLauncherError(COMPATIBILITY_FAILED, message)


def _flag_name(token: str) -> str:
    return token.split("=", 1)[0]


def _validate_no_forbidden_flags(argv: Sequence[str]) -> None:
    flags = {_flag_name(token) for token in argv if token.startswith("-")}
    present_dangerous = DANGEROUS_FLAGS.intersection(flags)
    if present_dangerous:
        raise CodexLauncherError(OVERRIDE_DANGEROUS_BYPASS, "Codex override contains a dangerous bypass flag.")
    present_legacy = LEGACY_UNSUPPORTED_FLAGS.intersection(flags)
    if present_legacy:
        raise CodexLauncherError(OVERRIDE_LEGACY_UNSUPPORTED, "Codex override contains legacy unsupported prompt/output flags.")


def _option_positions(argv: Sequence[str], names: frozenset[str]) -> set[int]:
    positions: set[int] = set()
    for index, token in enumerate(argv):
        if token in names:
            positions.add(index)
            if index + 1 < len(argv):
                positions.add(index + 1)
        elif any(token.startswith(name + "=") for name in names):
            positions.add(index)
    return positions


def _unexpected_prompt_args(argv: Sequence[str]) -> tuple[str, ...]:
    option_names = frozenset({"-C", "--cd", "-s", "--sandbox", "--output-schema", "-o", "--output-last-message", "-m", "--model"})
    value_positions = _option_positions(argv, option_names)
    allowed_flags = option_names.union({"--json"})
    unexpected: list[str] = []
    for index, token in enumerate(argv):
        if index in {0, 1, len(argv) - 1} or index in value_positions:
            continue
        if token in allowed_flags or any(token.startswith(name + "=") for name in option_names):
            continue
        unexpected.append(token)
    return tuple(unexpected)


def _validate_override(
    override: str,
    expected_sandbox: str,
    expected_executable: str,
    expected_project_root: Path,
    expected_schema_path: Path,
    expected_final_output_path: Path,
    json_events_supported: bool,
) -> tuple[str, ...]:
    try:
        argv = tuple(shlex.split(override))
    except ValueError as exc:
        raise CodexLauncherError(OVERRIDE_PARSE_FAILED, f"Codex override could not be parsed: {exc}") from exc

    if len(argv) < 2:
        raise CodexLauncherError(OVERRIDE_AMBIGUOUS, "Codex override is incomplete.")
    _validate_no_forbidden_flags(argv)
    _validate_override_executable(argv[0], expected_executable)
    if argv[1] != "exec":
        failure = OVERRIDE_LEGACY_UNSUPPORTED if argv[1] == "run" else OVERRIDE_AMBIGUOUS
        raise CodexLauncherError(failure, "Codex override must use the exec subcommand.")
    if "run" in argv[1:]:
        raise CodexLauncherError(OVERRIDE_LEGACY_UNSUPPORTED, "Codex override uses a legacy unsupported subcommand.")
    if argv[-1] != "-":
        raise CodexLauncherError(OVERRIDE_PROMPT_IN_ARGV, "Codex override must read prompt text from stdin using '-' as the final argument.")
    if _unexpected_prompt_args(argv):
        raise CodexLauncherError(OVERRIDE_PROMPT_IN_ARGV, "Codex override contains non-option argv content where prompt text could be embedded.")
    if not _has_option(argv, frozenset({"-C", "--cd"})):
        raise CodexLauncherError(OVERRIDE_REQUIRED_OPTION_MISSING, "Codex override must include the project root option.")
    _validate_override_path(
        argv,
        frozenset({"-C", "--cd"}),
        expected_project_root,
        "Codex override project root does not match the supplied project root.",
    )
    sandbox = _option_value(argv, frozenset({"-s", "--sandbox"}))
    if sandbox != expected_sandbox:
        raise CodexLauncherError(OVERRIDE_AMBIGUOUS, "Codex override sandbox does not match required provider-neutral capabilities.")
    if not _has_option(argv, frozenset({"--output-schema"})):
        raise CodexLauncherError(OVERRIDE_REQUIRED_OPTION_MISSING, "Codex override must include --output-schema.")
    _validate_override_path(
        argv,
        frozenset({"--output-schema"}),
        expected_schema_path,
        "Codex override output schema path does not match the launcher transport contract.",
    )
    if not _has_option(argv, frozenset({"-o", "--output-last-message"})):
        raise CodexLauncherError(OVERRIDE_REQUIRED_OPTION_MISSING, "Codex override must include --output-last-message.")
    _validate_override_path(
        argv,
        frozenset({"-o", "--output-last-message"}),
        expected_final_output_path,
        "Codex override final output path does not match the launcher transport contract.",
    )
    if "--json" in argv and not json_events_supported:
        raise CodexLauncherError(COMPATIBILITY_FAILED, "Codex override requested JSON events but the CLI capability manifest does not advertise support.")
    return argv


def resolve_codex_launcher(
    manifest: CodexCliCapabilityManifest,
    project_root: str | Path,
    output_dir: str | Path,
    required_capabilities: Iterable[str] | None = None,
    output_schema_path: str | Path | None = None,
    final_output_path: str | Path | None = None,
    override_command: str | None = None,
    include_json_events: bool | None = None,
    model_ref: str | None = None,
) -> CodexLauncherInvocation:
    _assert_manifest_compatible(manifest)
    project_root_path = Path(project_root)
    output_dir_path = Path(output_dir)
    schema_path = Path(output_schema_path) if output_schema_path is not None else _default_schema_path(output_dir_path)
    final_path = Path(final_output_path) if final_output_path is not None else _default_final_output_path(output_dir_path)
    sandbox = sandbox_for_capabilities(required_capabilities)
    json_events = bool(manifest.json_events_option if include_json_events is None else include_json_events)
    if json_events and not manifest.json_events_option:
        raise CodexLauncherError(COMPATIBILITY_FAILED, "Codex CLI does not advertise JSON events support.")
    executable = _manifest_executable_path(manifest)

    override = (override_command if override_command is not None else os.getenv("CODEX_CLI_COMMAND", "")).strip()
    if override:
        argv = _validate_override(
            override,
            sandbox,
            executable,
            project_root_path,
            schema_path,
            final_path,
            manifest.json_events_option,
        )
        if model_ref is not None:
            bound_model = _option_value(argv, frozenset({"-m", "--model"}))
            if bound_model != model_ref:
                raise CodexLauncherError(COMPATIBILITY_FAILED, "Codex override model does not match Router-selected model binding.")
        output_schema = _option_value(argv, frozenset({"--output-schema"})) or str(schema_path)
        final_output = _option_value(argv, frozenset({"-o", "--output-last-message"})) or str(final_path)
        return CodexLauncherInvocation(
            argv=argv,
            stdin_mode="prompt_text",
            sandbox_mode=sandbox,
            output_schema_path=output_schema,
            final_output_path=final_output,
            json_events="--json" in argv,
        )

    argv_list = [
        executable,
        "exec",
        "-C",
        str(project_root_path),
        "--sandbox",
        sandbox,
        "--output-schema",
        str(schema_path),
        "-o",
        str(final_path),
    ]
    if model_ref is not None:
        if not str(model_ref).strip():
            raise CodexLauncherError(COMPATIBILITY_FAILED, "Router-selected Codex model binding is empty.")
        argv_list.extend(["--model", str(model_ref)])
    if json_events:
        argv_list.append("--json")
    argv_list.append("-")
    _validate_no_forbidden_flags(argv_list)
    return CodexLauncherInvocation(
        argv=tuple(argv_list),
        stdin_mode="prompt_text",
        sandbox_mode=sandbox,
        output_schema_path=str(schema_path),
        final_output_path=str(final_path),
        json_events=json_events,
    )


def _read_structured_output(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CodexLauncherError(STRUCTURED_OUTPUT_MISSING, "Codex final output file was not created.") from exc
    except json.JSONDecodeError as exc:
        raise CodexLauncherError(STRUCTURED_OUTPUT_INVALID, "Codex final output file was not valid JSON.") from exc
    return True


def execute_codex_invocation(
    invocation: CodexLauncherInvocation,
    prompt_text: str,
    timeout_seconds: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> CodexProcessResult:
    argv = list(invocation.argv)
    _validate_no_forbidden_flags(argv)
    timeout = invocation.timeout_seconds if timeout_seconds is None else timeout_seconds
    start = time.monotonic()
    process: subprocess.Popen[str] | None = None
    stdout = ""
    stderr = ""
    returncode: int | None = None
    timed_out = False
    cancelled = False
    killed = False
    failure_class: str | None = None
    status = "SUCCESS"
    structured_valid: bool | None = None
    final_path = Path(invocation.final_output_path)

    try:
        if invocation.retry != 0:
            raise CodexLauncherError(COMPATIBILITY_FAILED, "Codex launcher policy requires retry=0.")
        if timeout <= 0:
            raise CodexLauncherError(COMPATIBILITY_FAILED, "Codex launcher timeout must be positive.")
        if invocation.stdin_mode != "prompt_text":
            raise CodexLauncherError(COMPATIBILITY_FAILED, "Codex launcher requires stdin prompt transport.")
        if prompt_text in argv:
            raise CodexLauncherError(OVERRIDE_PROMPT_IN_ARGV, "Codex prompt text must not be present in argv.")
        if cancel_check is not None and cancel_check():
            raise CodexLauncherError(CANCELLED, "Codex launch cancelled before process start.")
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        deadline = start + timeout
        pending_input: str | None = prompt_text
        try:
            while True:
                if cancel_check is not None and cancel_check():
                    cancelled = True
                    failure_class = CANCELLED
                    status = CANCELLED
                    process.terminate()
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        killed = True
                        process.kill()
                        stdout, stderr = process.communicate()
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    stdout, stderr = process.communicate(input=pending_input, timeout=min(0.25, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
        except subprocess.TimeoutExpired:
            timed_out = True
            failure_class = TIMEOUT
            status = TIMEOUT
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                killed = True
                process.kill()
                stdout, stderr = process.communicate()
        returncode = process.returncode
        if cancelled:
            pass
        elif cancel_check is not None and cancel_check() and not timed_out:
            cancelled = True
            failure_class = CANCELLED
            status = CANCELLED
        elif timed_out:
            pass
        elif returncode != 0:
            failure_class = NONZERO_EXIT
            status = NONZERO_EXIT
        else:
            try:
                structured_valid = _read_structured_output(final_path)
            except CodexLauncherError as exc:
                failure_class = exc.failure_class
                status = exc.failure_class
                structured_valid = False
        if returncode == 0 and status == "SUCCESS" and not final_path.exists():
            failure_class = ABNORMAL_SUCCESS_AMBIGUITY
            status = ABNORMAL_SUCCESS_AMBIGUITY
    except (FileNotFoundError, OSError):
        failure_class = CLI_NOT_FOUND if isinstance(process, type(None)) else PROCESS_SPAWN_FAILED
        status = BACKEND_LAUNCHER_COMPATIBILITY_FAILED
    except CodexLauncherError as exc:
        failure_class = exc.failure_class
        status = exc.status
        if failure_class == CANCELLED:
            cancelled = True
    duration = time.monotonic() - start
    return CodexProcessResult(
        status=status,
        failure_class=failure_class,
        returncode=returncode,
        timed_out=timed_out,
        cancelled=cancelled,
        killed=killed,
        duration_seconds=round(duration, 3),
        stdout=stdout,
        stderr=stderr,
        final_output_path=str(final_path),
        final_output_exists=final_path.exists(),
        structured_output_valid=structured_valid,
    )
