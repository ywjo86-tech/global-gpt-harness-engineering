#!/usr/bin/env python3
"""Fail-closed OCPv2 user-service bootstrap helper.

`check` is validation-only. `render` writes only to an explicit review directory.
`install-user-service` writes user-level configuration/unit files but never invokes the
service manager. `run-once` is the one-shot composition root used by the user timer.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable


PUBLIC_SOURCE_REPOSITORY_ID = 1254385549
ALL_MODES = {
    "DISABLED",
    "OBSERVE_ONLY",
    "CONTROL_READ_ONLY",
    "CONTROL_MUTATION_CANARY",
    "ACTIVE",
}
INSTALL_MODES = {"DISABLED", "OBSERVE_ONLY"}
RUNTIME_NON_MUTATING_MODES = {"DISABLED", "OBSERVE_ONLY", "CONTROL_READ_ONLY"}


class BootstrapError(ValueError):
    pass


class BootstrapConfig:
    def __init__(
        self,
        *,
        mode: str,
        repo_root: str | Path,
        control_repository_id: int,
        control_pr_number: int,
        allowed_actor_ids: Iterable[str],
        token_file: str | Path | None,
        state_root: str | Path | None,
    ) -> None:
        self.mode = str(mode)
        self.repo_root = Path(repo_root)
        self.control_repository_id = int(control_repository_id)
        self.control_pr_number = int(control_pr_number)
        self.allowed_actor_ids = tuple(str(item) for item in allowed_actor_ids)
        self.token_file = None if token_file is None or str(token_file) == "" else Path(token_file)
        self.state_root = None if state_root is None or str(state_root) == "" else Path(state_root)

    @classmethod
    def disabled(cls, *, repo_root: str | Path) -> "BootstrapConfig":
        return cls(
            mode="DISABLED",
            repo_root=repo_root,
            control_repository_id=0,
            control_pr_number=0,
            allowed_actor_ids=(),
            token_file=None,
            state_root=None,
        )


class RenderedPackage:
    def __init__(self, *, env_path: Path, service_path: Path, timer_path: Path) -> None:
        self.env_path = env_path
        self.service_path = service_path
        self.timer_path = timer_path


def _validated_path(path: Path, label: str, *, must_exist: bool) -> Path:
    if path.is_symlink():
        raise BootstrapError(f"{label} must not be a symlink")
    resolved = path.resolve()
    if must_exist and (not resolved.exists() or not resolved.is_dir()):
        raise BootstrapError(f"{label} must be an existing directory")
    return resolved


def _positive_decimal_ids(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or not text.isdecimal() or int(text) <= 0:
            raise BootstrapError("allowed actor IDs must be positive decimal values")
        normalized.append(str(int(text)))
    if len(set(normalized)) != len(normalized):
        raise BootstrapError("allowed actor IDs must be unique")
    return tuple(normalized)


def validate_install_mode(mode: str) -> str:
    value = str(mode)
    if value not in INSTALL_MODES:
        raise BootstrapError("install mode must be DISABLED or OBSERVE_ONLY")
    return value


def check_config(config: BootstrapConfig) -> BootstrapConfig:
    if config.mode not in ALL_MODES:
        raise BootstrapError("unknown OCP mode")
    repo_root = _validated_path(config.repo_root, "repo root", must_exist=True)

    if config.mode == "DISABLED":
        return BootstrapConfig.disabled(repo_root=repo_root)

    if config.control_repository_id <= 0:
        raise BootstrapError("control repository ID must be positive")
    if config.control_repository_id == PUBLIC_SOURCE_REPOSITORY_ID:
        raise BootstrapError("public source repository cannot be the control repository")
    if config.control_pr_number <= 0:
        raise BootstrapError("control PR number must be positive")
    actor_ids = _positive_decimal_ids(config.allowed_actor_ids)
    if not actor_ids:
        raise BootstrapError("at least one allowed actor ID is required")
    if config.token_file is None:
        raise BootstrapError("token file is required in control modes")
    token_file = config.token_file.absolute()
    if token_file.is_symlink():
        raise BootstrapError("token file must not be a symlink")
    if not token_file.exists() or not token_file.is_file():
        raise BootstrapError("token file must be an existing regular file")
    if token_file.stat().st_mode & 0o077:
        raise BootstrapError("token file permissions must deny group/world access")
    if config.state_root is None:
        raise BootstrapError("state root is required in control modes")
    state_root = config.state_root.absolute()
    if state_root.is_symlink():
        raise BootstrapError("state root must not be a symlink")

    return BootstrapConfig(
        mode=config.mode,
        repo_root=repo_root,
        control_repository_id=config.control_repository_id,
        control_pr_number=config.control_pr_number,
        allowed_actor_ids=actor_ids,
        token_file=token_file,
        state_root=state_root,
    )


def _env_text(config: BootstrapConfig) -> str:
    token_file = "" if config.token_file is None else str(config.token_file)
    state_root = "" if config.state_root is None else str(config.state_root)
    return "\n".join(
        [
            f"OCP_MODE={config.mode}",
            f"OCP_GITHUB_CONTROL_REPOSITORY_ID={config.control_repository_id}",
            f"OCP_GITHUB_CONTROL_PR_NUMBER={config.control_pr_number}",
            f"OCP_GITHUB_ALLOWED_ACTOR_IDS={','.join(config.allowed_actor_ids)}",
            f"OCP_GITHUB_TOKEN_FILE={token_file}",
            f"OCP_STATE_ROOT={state_root}",
            f"OCP_REPO_ROOT={config.repo_root}",
            "GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED=false",
            "GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG=",
            "",
        ]
    )


def _deploy_root() -> Path:
    return Path(__file__).resolve().parent


def render_package(config: BootstrapConfig, *, output_dir: str | Path) -> RenderedPackage:
    checked = check_config(config)
    output = Path(output_dir).absolute()
    if output.is_symlink():
        raise BootstrapError("render output must not be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    if not output.is_dir():
        raise BootstrapError("render output must be a directory")

    template = (_deploy_root() / "ocpv2.user.service.in").read_text(encoding="utf-8")
    timer = (_deploy_root() / "ocpv2.user.timer").read_text(encoding="utf-8")
    service = template.replace("@REPO_ROOT@", str(checked.repo_root))
    if "@REPO_ROOT@" in service:
        raise BootstrapError("service template contains unresolved repo root")

    env_path = output / "ocpv2.env"
    service_path = output / "ocpv2.service"
    timer_path = output / "ocpv2.timer"
    env_path.write_text(_env_text(checked), encoding="utf-8")
    os.chmod(env_path, 0o600)
    service_path.write_text(service, encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")
    return RenderedPackage(env_path=env_path, service_path=service_path, timer_path=timer_path)


def install_user_service(
    config: BootstrapConfig,
    *,
    user_config_root: str | Path | None = None,
    user_unit_root: str | Path | None = None,
) -> RenderedPackage:
    validate_install_mode(config.mode)
    checked = check_config(config)
    home = Path.home()
    config_root = Path(user_config_root) if user_config_root is not None else home / ".config" / "gch"
    unit_root = Path(user_unit_root) if user_unit_root is not None else home / ".config" / "systemd" / "user"
    if config_root.is_symlink() or unit_root.is_symlink():
        raise BootstrapError("user configuration roots must not be symlinks")
    config_root.mkdir(parents=True, exist_ok=True)
    unit_root.mkdir(parents=True, exist_ok=True)

    service_template = (_deploy_root() / "ocpv2.user.service.in").read_text(encoding="utf-8")
    service = service_template.replace("@REPO_ROOT@", str(checked.repo_root))
    timer = (_deploy_root() / "ocpv2.user.timer").read_text(encoding="utf-8")
    env_path = config_root / "ocpv2.env"
    service_path = unit_root / "ocpv2.service"
    timer_path = unit_root / "ocpv2.timer"
    env_path.write_text(_env_text(checked), encoding="utf-8")
    os.chmod(env_path, 0o600)
    service_path.write_text(service, encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")
    return RenderedPackage(env_path=env_path, service_path=service_path, timer_path=timer_path)


def _parse_env_file(path: str | Path) -> dict[str, str]:
    source = Path(path).absolute()
    if source.is_symlink() or not source.is_file():
        raise BootstrapError("environment file must be a regular non-symlink file")
    result: dict[str, str] = {}
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise BootstrapError("environment file contains malformed entry")
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def config_from_env_file(path: str | Path) -> BootstrapConfig:
    env = _parse_env_file(path)
    required = {
        "OCP_MODE",
        "OCP_GITHUB_CONTROL_REPOSITORY_ID",
        "OCP_GITHUB_CONTROL_PR_NUMBER",
        "OCP_GITHUB_ALLOWED_ACTOR_IDS",
        "OCP_GITHUB_TOKEN_FILE",
        "OCP_STATE_ROOT",
        "OCP_REPO_ROOT",
    }
    optional = {
        "GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED",
        "GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG",
    }
    if not required.issubset(env) or set(env) - required - optional:
        raise BootstrapError("environment file key set mismatch")
    try:
        repository_id = int(env["OCP_GITHUB_CONTROL_REPOSITORY_ID"])
        pr_number = int(env["OCP_GITHUB_CONTROL_PR_NUMBER"])
    except ValueError as exc:
        raise BootstrapError("control repository/PR IDs must be integers") from exc
    actor_ids = tuple(item.strip() for item in env["OCP_GITHUB_ALLOWED_ACTOR_IDS"].split(",") if item.strip())
    return BootstrapConfig(
        mode=env["OCP_MODE"],
        repo_root=env["OCP_REPO_ROOT"],
        control_repository_id=repository_id,
        control_pr_number=pr_number,
        allowed_actor_ids=actor_ids,
        token_file=env["OCP_GITHUB_TOKEN_FILE"] or None,
        state_root=env["OCP_STATE_ROOT"] or None,
    )


def _compose_non_mutating_service(config: BootstrapConfig):
    if config.mode not in RUNTIME_NON_MUTATING_MODES:
        raise BootstrapError("mutation runtime composition requires a separately authorized canonical executor")
    checked = check_config(config)
    if checked.mode == "DISABLED":
        return None

    repo_text = str(checked.repo_root)
    if repo_text not in sys.path:
        sys.path.insert(0, repo_text)

    from runtime.operator_transport.github_control_adapter import GitHubControlAdapter, GitHubControlConfig
    from runtime.operator_transport.github_rest_client import GitHubRESTClient
    from runtime.orchestrator.production_worker_executor import _secret_findings
    from runtime.orchestrator.remote_operator_envelope import validate_remote_envelope
    from runtime.orchestrator.remote_operator_ingress import validate_ingress
    from runtime.orchestrator.remote_operator_outbox import RemoteResultOutbox, RemoteResultProjectionV1
    from runtime.orchestrator.remote_operator_receipt import RemoteOperatorReceiptStore
    from runtime.orchestrator.remote_operator_service import RemoteOperatorService, RemoteOperatorServiceError

    assert checked.token_file is not None
    assert checked.state_root is not None
    rest_client = GitHubRESTClient(
        repository_id=checked.control_repository_id,
        control_pr_number=checked.control_pr_number,
        token_file=checked.token_file,
    )
    adapter = GitHubControlAdapter(
        config=GitHubControlConfig(
            allowed_repository_id=checked.control_repository_id,
            control_pr_number=checked.control_pr_number,
            allowed_actor_ids=frozenset(checked.allowed_actor_ids),
        ),
        rest_client=rest_client,
        secret_scan=_secret_findings,
    )
    receipt_store = RemoteOperatorReceiptStore(checked.state_root / "receipts")
    result_outbox = RemoteResultOutbox(checked.state_root / "outbox")

    def publish_pending_projection(projection: RemoteResultProjectionV1) -> None:
        # Replaying an already-sealed result projection is transport recovery only.
        # It does not grant execution, completion, provider-routing, or canonical
        # mutation authority to the bootstrap service.
        adapter.publish_projection(projection.to_dict())
        adapter.acknowledge_delivery(projection.message_id)

    result_outbox.publish_pending(publish_pending_projection)

    def decode(raw):
        try:
            value = json.loads(raw.content.decode("utf-8"))
        except Exception as exc:
            raise BootstrapError("remote control payload is not valid JSON") from exc
        envelope = validate_remote_envelope(value)
        expected_channel = f"PR:{checked.control_pr_number}"
        if (
            envelope.transport.adapter_id != "GITHUB_CONTROL_V1"
            or envelope.transport.channel_id != expected_channel
            or envelope.transport.source_actor_id != raw.source_actor_id
            or envelope.transport.source_message_id != raw.source_message_id
            or raw.source_repository_id != checked.control_repository_id
        ):
            raise BootstrapError("remote envelope transport binding mismatch")
        return envelope

    def ingress(envelope):
        return validate_ingress(
            envelope,
            receipt_store=receipt_store,
            allowed_adapter_id="GITHUB_CONTROL_V1",
            allowed_channel_id=f"PR:{checked.control_pr_number}",
            allowed_source_actor_ids=checked.allowed_actor_ids,
            expected_risk_envelope_digest=None,
        )

    def no_mutation_executor(envelope, directive):
        raise RemoteOperatorServiceError("mutation execution is not installed by the bootstrap package")

    return RemoteOperatorService(
        transport=adapter,
        decode_envelope=decode,
        ingress=ingress,
        execute_authorized=no_mutation_executor,
    )


def run_once(config: BootstrapConfig):
    checked = check_config(config)
    if checked.mode == "DISABLED":
        return {"mode": "DISABLED", "received": 0, "validated": 0, "executed": 0}
    service = _compose_non_mutating_service(checked)
    if service is None:
        raise BootstrapError("service composition unavailable")
    result = service.poll_once(mode=checked.mode)
    return {
        "mode": result.mode,
        "received": result.received,
        "validated": result.validated,
        "executed": result.executed,
        "projected": result.projected,
        "acknowledged": result.acknowledged,
        "blocked": result.blocked,
    }


def _config_from_args(args: argparse.Namespace) -> BootstrapConfig:
    state_root = args.state_root or os.environ.get("OCP_STATE_ROOT", "")
    return BootstrapConfig(
        mode=args.mode,
        repo_root=args.repo_root,
        control_repository_id=args.control_repository_id,
        control_pr_number=args.control_pr_number,
        allowed_actor_ids=tuple(item.strip() for item in args.allowed_actor_ids.split(",") if item.strip()),
        token_file=args.token_file or None,
        state_root=state_root or None,
    )


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--mode", required=True, choices=sorted(ALL_MODES))
    parser.add_argument("--control-repository-id", type=int, required=True)
    parser.add_argument("--control-pr-number", type=int, required=True)
    parser.add_argument("--allowed-actor-ids", default="")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--state-root", default="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OCPv2 user-service bootstrap helper")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    _add_config_args(check)
    render = sub.add_parser("render")
    _add_config_args(render)
    render.add_argument("--output-dir", required=True)
    install = sub.add_parser("install-user-service")
    _add_config_args(install)
    run = sub.add_parser("run-once")
    run.add_argument("--env-file", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run-once":
            result = run_once(config_from_env_file(args.env_file))
        else:
            config = _config_from_args(args)
            if args.command == "check":
                checked = check_config(config)
                result = {
                    "mode": checked.mode,
                    "repo_root": str(checked.repo_root),
                    "control_repository_id": checked.control_repository_id,
                    "control_pr_number": checked.control_pr_number,
                    "allowed_actor_ids": list(checked.allowed_actor_ids),
                    "token_file_configured": checked.token_file is not None,
                    "state_root_configured": checked.state_root is not None,
                }
            elif args.command == "render":
                rendered = render_package(config, output_dir=args.output_dir)
                result = {
                    "env_path": str(rendered.env_path),
                    "service_path": str(rendered.service_path),
                    "timer_path": str(rendered.timer_path),
                }
            elif args.command == "install-user-service":
                rendered = install_user_service(config)
                result = {
                    "env_path": str(rendered.env_path),
                    "service_path": str(rendered.service_path),
                    "timer_path": str(rendered.timer_path),
                    "service_manager_invoked": False,
                }
            else:
                raise BootstrapError("unknown command")
    except BootstrapError as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": "OK", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())