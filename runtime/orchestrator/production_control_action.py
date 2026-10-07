from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .lifecycle_v2_p4_transition import execute_p4_cutover, prepare_p4_cutover
from .ocpv2_activation_window import SystemdUserServiceController, UserServiceController
from .operational_post_change_gate import evaluate_post_change_gate
from .operational_runtime_compatibility import (
    build_runtime_compatibility_manifest,
    load_runtime_compatibility_manifest,
    record_runtime_compatibility_manifest,
)
from .production_control_contract import (
    OCP_QUIESCE,
    OCP_RESUME,
    P4_CUTOVER,
    POST_CHANGE_VALIDATE,
    RETIRE_FULL_PLAN_RUN,
    SYNC_OPERATIONAL_RUNTIME_IDENTITY,
    ProductionControlActionRequestV1,
    ProductionControlActionResultV1,
    PRODUCTION_CONTROL_RESULT_SCHEMA_V1,
)
from .production_full_plan_entry import _approval_proof_is_fresh
from .production_full_plan_runner import DurableFullPlanSupervisor
from .runtime_release import verify_runtime_release

_ACTION_ROOT = "_workspace/production-control-actions"
_EVENT_SCHEMA = "orchestration.production-control-action-event.v1"
_SHA64 = "0123456789abcdef"


class ProductionControlActionError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise ProductionControlActionError("action ledger path unsafe")
    payload = _canonical(dict(value))
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise ProductionControlActionError("action ledger conflict")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProductionControlActionError("required action evidence missing")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionControlActionError("action evidence unreadable") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise ProductionControlActionError("action evidence noncanonical")
    return value


@dataclass(frozen=True, slots=True)
class ProductionControlBackendOutcome:
    status: str
    result_class: str
    effect: Mapping[str, Any]
    evidence_refs: tuple[str, ...] = ()
    evidence_digests: tuple[str, ...] = ()

    @property
    def effect_digest(self) -> str:
        return _digest(dict(self.effect))


class ProductionControlBackend(Protocol):
    def current_state_digest(self, request: ProductionControlActionRequestV1) -> str: ...
    def apply(self, request: ProductionControlActionRequestV1) -> ProductionControlBackendOutcome: ...


@dataclass(frozen=True, slots=True)
class ProductionControlServerConfig:
    harness_state_root: Path
    releases_root: Path
    runtime_link: Path
    runtime_compatibility_manifest: Path
    operational_identity_files: tuple[Path, ...] = ()
    job_search_root: Path | None = None
    post_change_context_provider: Callable[[ProductionControlActionRequestV1], Mapping[str, Any]] | None = None

    def __post_init__(self) -> None:
        for path in (
            self.harness_state_root,
            self.releases_root,
            self.runtime_link.parent,
            self.runtime_compatibility_manifest.parent,
        ):
            if path.is_symlink():
                raise ProductionControlActionError("production control server path unsafe")
        if self.job_search_root is None:
            object.__setattr__(self, "job_search_root", self.harness_state_root)


class ProductionControlLedger:
    def __init__(self, state_root: str | Path, *, lock_timeout_seconds: float = 5.0) -> None:
        self.state_root = Path(state_root).expanduser().absolute()
        if self.state_root.is_symlink() or not self.state_root.is_dir():
            raise ProductionControlActionError("Harness state root unsafe")
        self.root = self.state_root / _ACTION_ROOT
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ProductionControlActionError("action ledger root unsafe")
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        if self.lock_timeout_seconds <= 0 or self.lock_timeout_seconds > 30:
            raise ProductionControlActionError("action lock timeout invalid")

    def _key_root(self, request: ProductionControlActionRequestV1) -> Path:
        return self.root / request.idempotency_key

    def acquire(self):
        lock_path = self.root / ".global.lock"
        fd = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise ProductionControlActionError("production control action lock timeout")
                time.sleep(0.05)

    @staticmethod
    def release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def bind_request(self, request: ProductionControlActionRequestV1) -> None:
        root = self._key_root(request)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink():
            raise ProductionControlActionError("action key root unsafe")
        record = {
            "schema_version": "orchestration.production-control-action-binding.v1",
            "request_id": request.request_id,
            "idempotency_key": request.idempotency_key,
            "request_digest": request.request_digest,
            "action": request.action,
        }
        path = root / "request.json"
        if path.exists():
            existing = _read_json(path)
            if existing != record:
                raise ProductionControlActionError("IDEMPOTENCY_KEY_CONFLICT")
            return
        _write_once(path, record)

    def events(self, request: ProductionControlActionRequestV1) -> list[dict[str, Any]]:
        events_root = self._key_root(request) / "events"
        if not events_root.exists():
            return []
        if events_root.is_symlink() or not events_root.is_dir():
            raise ProductionControlActionError("action events root unsafe")
        result: list[dict[str, Any]] = []
        for path in sorted(events_root.iterdir(), key=lambda item: item.name):
            if path.name.startswith("."):
                continue
            result.append(_read_json(path))
        return result

    def append(
        self,
        request: ProductionControlActionRequestV1,
        *,
        status: str,
        phase: str,
        result_class: str,
        effect_digest: str = "",
        evidence_refs: Sequence[str] = (),
        evidence_digests: Sequence[str] = (),
    ) -> dict[str, Any]:
        events = self.events(request)
        sequence = len(events) + 1
        event = {
            "schema_version": _EVENT_SCHEMA,
            "sequence": sequence,
            "request_id": request.request_id,
            "request_digest": request.request_digest,
            "idempotency_key": request.idempotency_key,
            "action": request.action,
            "status": status,
            "phase": phase,
            "result_class": result_class,
            "effect_digest": effect_digest,
            "evidence_refs": list(evidence_refs),
            "evidence_digests": list(evidence_digests),
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        }
        event["event_digest"] = _digest(event)
        path = self._key_root(request) / "events" / f"{sequence:04d}-{status}.json"
        _write_once(path, event)
        return event


def validate_approval_proof(
    request: ProductionControlActionRequestV1,
    *,
    harness_state_root: str | Path,
    now: datetime | None = None,
) -> tuple[str, str]:
    root = Path(harness_state_root).expanduser().absolute()
    relative = Path(request.approval_proof_path)
    target = root.joinpath(*relative.parts)
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ProductionControlActionError("approval proof path escapes Harness state root") from exc
    if target.is_symlink() or not target.is_file():
        raise ProductionControlActionError("approval proof missing or unsafe")
    raw = target.read_bytes()
    if _sha_bytes(raw) != request.approval_proof_sha256:
        raise ProductionControlActionError("approval proof digest mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionControlActionError("approval proof malformed") from exc
    if (
        not isinstance(value, dict)
        or value.get("approval_ref") != request.approval_ref
        or value.get("activation_id") != request.activation_id
        or value.get("plan_digest") != request.plan_digest
        or not isinstance(value.get("proof"), Mapping)
        or not _approval_proof_is_fresh(value, now=now)
    ):
        raise ProductionControlActionError("approval proof binding mismatch")
    return relative.as_posix(), request.approval_proof_sha256


def _runtime_link_head(link: Path, releases_root: Path) -> str:
    if not link.is_symlink():
        raise ProductionControlActionError("runtime-current link required")
    try:
        target = link.resolve(strict=True)
        relative = target.relative_to(releases_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ProductionControlActionError("runtime-current target unsafe") from exc
    if len(relative.parts) != 1 or len(relative.parts[0]) != 40:
        raise ProductionControlActionError("runtime-current target invalid")
    return relative.parts[0]


class CanonicalProductionControlBackend:
    def __init__(
        self,
        config: ProductionControlServerConfig,
        *,
        service_controller: UserServiceController | None = None,
        daemon_reload: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.service_controller = service_controller or SystemdUserServiceController(timeout_seconds=20)
        self.daemon_reload = daemon_reload or self._daemon_reload

    @staticmethod
    def _daemon_reload() -> None:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def _release(self, head: str):
        path = self.config.releases_root / head
        return verify_runtime_release(path, head)

    def _validate_runtime_binding(self, request: ProductionControlActionRequestV1) -> None:
        current = _runtime_link_head(self.config.runtime_link, self.config.releases_root)
        expected_current = (
            request.target_runtime_source_head
            if request.action in {OCP_RESUME, POST_CHANGE_VALIDATE}
            else request.expected_runtime_source_head
        )
        if current != expected_current:
            raise ProductionControlActionError("runtime-current source mismatch")
        target = self._release(request.target_runtime_source_head)
        if target.manifest_sha256 != request.target_runtime_manifest_sha256:
            raise ProductionControlActionError("target runtime manifest mismatch")

    def _runtime_state(self) -> dict[str, Any]:
        manifest = load_runtime_compatibility_manifest(
            self.config.runtime_compatibility_manifest
        )
        identities = {}
        for path in self.config.operational_identity_files:
            if path.is_symlink() or not path.is_file():
                raise ProductionControlActionError("operational identity file unsafe")
            identities[path.name] = _sha_bytes(path.read_bytes())
        return {
            "runtime_current": _runtime_link_head(
                self.config.runtime_link, self.config.releases_root
            ),
            "compatibility_manifest_sha256": manifest["manifest_sha256"],
            "identity_file_sha256": identities,
        }

    def current_state_digest(self, request: ProductionControlActionRequestV1) -> str:
        self._validate_runtime_binding(request)
        if request.action == RETIRE_FULL_PLAN_RUN:
            run_id = str(request.parameters["run_id"])
            path = (
                self.config.harness_state_root
                / "_workspace/production-full-plan"
                / request.project_id
                / run_id
                / "state.json"
            )
            value = _read_json(path)
            state_sha = str(value.get("state_sha256") or "")
            if len(state_sha) != 64 or any(ch not in _SHA64 for ch in state_sha):
                raise ProductionControlActionError("Full Plan state digest invalid")
            return state_sha
        if request.action in {OCP_QUIESCE, OCP_RESUME}:
            snapshot = {
                unit: bool(self.service_controller.is_active(unit))
                for unit in request.parameters["units"]
            }
            return _digest(snapshot)
        return _digest(self._runtime_state())

    def _retire(self, request: ProductionControlActionRequestV1) -> ProductionControlBackendOutcome:
        run_id = str(request.parameters["run_id"])
        job_path = (
            self.config.harness_state_root
            / "_workspace/production-full-plan-jobs"
            / request.project_id
            / f"{run_id}.job.json"
        )
        job = _read_json(job_path)
        state_path = (
            self.config.harness_state_root
            / "_workspace/production-full-plan"
            / request.project_id
            / run_id
            / "state.json"
        )
        state = _read_json(state_path)
        if (
            str(state.get("state_sha256") or "") != request.expected_state_sha256
            or str(state.get("terminal_reason") or "")
            != str(request.parameters["expected_terminal_reason"])
            or state.get("lease") is not None
        ):
            raise ProductionControlActionError("Full Plan retirement state mismatch")
        supervisor = DurableFullPlanSupervisor(
            str(job.get("harness_state_root") or job["harness_root"]),
            project_id=job["project_id"],
            run_id=job["run_id"],
            gates=[gate["gate_id"] for gate in job["gates"]],
            authority_core_sha256=job["authority_core_sha256"],
            **dict(job.get("policy") or {}),
        )
        out = supervisor.cancel(
            f"PRODUCTION_CONTROL_RETIRED:{request.request_id}"
        )
        if out.get("state") != "CANCELLED":
            raise ProductionControlActionError("Full Plan retirement not verified")
        evidence = {"state_sha256": out.get("state_sha256"), "terminal_reason": out.get("terminal_reason")}
        return ProductionControlBackendOutcome(
            "VERIFIED",
            "FULL_PLAN_RUN_RETIRED",
            evidence,
            evidence_refs=(f"full-plan:{request.project_id}:{run_id}",),
            evidence_digests=(str(out["state_sha256"]),),
        )

    def _sync_runtime_identity(
        self, request: ProductionControlActionRequestV1
    ) -> ProductionControlBackendOutcome:
        current = _runtime_link_head(
            self.config.runtime_link, self.config.releases_root
        )
        if current != request.expected_runtime_source_head:
            raise ProductionControlActionError("runtime-current source mismatch")
        target = self._release(request.target_runtime_source_head)
        if target.manifest_sha256 != request.target_runtime_manifest_sha256:
            raise ProductionControlActionError("target runtime manifest mismatch")
        manifest = load_runtime_compatibility_manifest(
            self.config.runtime_compatibility_manifest
        )
        if (
            manifest["current_runtime_source_identity"]
            != request.expected_runtime_source_head
        ):
            raise ProductionControlActionError("compatibility runtime source mismatch")
        components = []
        for component in manifest["components"]:
            row = dict(component)
            if row["binding_mode"] == "CURRENT_RUNTIME":
                row["expected_source_head"] = request.target_runtime_source_head
            components.append(row)
        updated = build_runtime_compatibility_manifest(
            current_runtime_source_identity=request.target_runtime_source_head,
            releases_root=manifest["releases_root"],
            components=components,
        )

        originals: dict[Path, bytes] = {}
        try:
            for path in (
                self.config.runtime_compatibility_manifest,
                *self.config.operational_identity_files,
            ):
                if path.is_symlink() or not path.is_file():
                    raise ProductionControlActionError("operational identity file unsafe")
                originals[path] = path.read_bytes()
            for path in self.config.operational_identity_files:
                text = originals[path].decode("utf-8")
                old = request.expected_runtime_source_head
                new = request.target_runtime_source_head
                if text.count(old) != 1:
                    raise ProductionControlActionError(
                        "operational runtime identity occurrence mismatch"
                    )
                rendered = text.replace(old, new, 1).encode("utf-8")
                temp = path.with_name(path.name + f".tmp-{os.getpid()}")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(temp, flags, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(rendered)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, path)
            record_runtime_compatibility_manifest(
                self.config.runtime_compatibility_manifest, updated
            )
            self.daemon_reload()
        except Exception:
            for path, raw in originals.items():
                temp = path.with_name(path.name + f".rollback-{os.getpid()}")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(temp, flags, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, path)
            try:
                self.daemon_reload()
            except Exception:
                pass
            raise

        evidence = {
            "manifest_sha256": updated["manifest_sha256"],
            "target_runtime_source_head": request.target_runtime_source_head,
            "identity_file_sha256": {
                path.name: _sha_bytes(path.read_bytes())
                for path in self.config.operational_identity_files
            },
        }
        return ProductionControlBackendOutcome(
            "VERIFIED",
            "OPERATIONAL_RUNTIME_IDENTITY_SYNCED",
            evidence,
            evidence_refs=("operational-runtime-compatibility",),
            evidence_digests=(updated["manifest_sha256"],),
        )

    def _ocp_units(
        self, request: ProductionControlActionRequestV1, *, start: bool
    ) -> ProductionControlBackendOutcome:
        units = tuple(request.parameters["units"])
        before = {unit: bool(self.service_controller.is_active(unit)) for unit in units}
        for unit in units:
            if start:
                if not self.service_controller.is_active(unit):
                    self.service_controller.start(unit)
            elif self.service_controller.is_active(unit):
                self.service_controller.stop(unit)
        after = {unit: bool(self.service_controller.is_active(unit)) for unit in units}
        if start and not all(after.values()):
            raise ProductionControlActionError("OCP resume verification failed")
        if not start and any(after.values()):
            raise ProductionControlActionError("OCP quiesce verification failed")
        effect = {"before": before, "after": after, "units": list(units)}
        return ProductionControlBackendOutcome(
            "VERIFIED",
            "OCP_RESUMED" if start else "OCP_QUIESCED",
            effect,
            evidence_refs=("ocp-unit-state",),
            evidence_digests=(_digest(effect),),
        )

    def _p4_cutover(
        self, request: ProductionControlActionRequestV1
    ) -> ProductionControlBackendOutcome:
        source = self._release(request.expected_runtime_source_head)
        target = self._release(request.target_runtime_source_head)
        if target.manifest_sha256 != request.target_runtime_manifest_sha256:
            raise ProductionControlActionError("target runtime manifest mismatch")
        admission_digest = str(request.parameters["admission_digest"])
        qualification_digest = str(request.parameters["qualification_digest"])
        p4_entry_digest = str(request.parameters["p4_entry_digest"])
        cutover_admission_digest = str(request.parameters["cutover_admission_digest"])
        qualification = _read_json(
            self.config.harness_state_root
            / "p3-final-qualifications"
            / f"{admission_digest}.json"
        )
        entry = _read_json(
            self.config.harness_state_root
            / "p4-read-only-entries"
            / f"{admission_digest}.json"
        )
        cutover_admission = _read_json(
            self.config.harness_state_root
            / "p4-cutover-admissions"
            / f"{admission_digest}.json"
        )
        if (
            qualification.get("qualification_digest") != qualification_digest
            or entry.get("entry_digest") != p4_entry_digest
            or entry.get("qualification_digest") != qualification_digest
            or entry.get("status") != "P4_READ_ONLY_ENTERED"
            or cutover_admission.get("admission_digest") != admission_digest
            or cutover_admission.get("qualification_digest") != qualification_digest
            or cutover_admission.get("p4_entry_digest") != p4_entry_digest
            or cutover_admission.get("cutover_admission_digest") != cutover_admission_digest
            or cutover_admission.get("status") != "P4_CUTOVER_READY"
            or cutover_admission.get("runtime_current_switch_authorized") is not True
            or cutover_admission.get("source_head") != request.expected_runtime_source_head
            or cutover_admission.get("target_head") != request.target_runtime_source_head
            or cutover_admission.get("target_manifest_sha256")
            != request.target_runtime_manifest_sha256
        ):
            raise ProductionControlActionError("P4 lineage binding mismatch")
        refreshed_admission = prepare_p4_cutover(
            state_root=self.config.harness_state_root,
            runtime_link=self.config.runtime_link,
            source_release=source.release_path,
            target_release=target.release_path,
            target_head=request.target_runtime_source_head,
            admission_digest=admission_digest,
            qualification_digest=qualification_digest,
            p4_entry_digest=p4_entry_digest,
            job_search_root=self.config.job_search_root,
        )
        if (
            refreshed_admission.get("cutover_admission_digest")
            != cutover_admission_digest
            or refreshed_admission.get("status") != "P4_CUTOVER_READY"
            or refreshed_admission.get("runtime_current_switch_authorized") is not True
        ):
            raise ProductionControlActionError("P4 cutover admission became stale")
        result = execute_p4_cutover(
            state_root=self.config.harness_state_root,
            runtime_link=self.config.runtime_link,
            source_release=source.release_path,
            target_release=target.release_path,
            target_head=request.target_runtime_source_head,
            admission_digest=admission_digest,
            cutover_admission_digest=cutover_admission_digest,
            job_search_root=self.config.job_search_root,
        )
        if (
            result.get("status") != "P4_CUTOVER_COMPLETE"
            or result.get("rollback_verified") is not True
            or result.get("runtime_current_switched") is not True
        ):
            raise ProductionControlActionError("P4 cutover result invalid")
        return ProductionControlBackendOutcome(
            "VERIFIED",
            "P4_CUTOVER_COMPLETED",
            result,
            evidence_refs=(f"p4-cutover:{request.parameters['admission_digest']}",),
            evidence_digests=(str(result["result_digest"]),),
        )

    def _post_change_validate(
        self, request: ProductionControlActionRequestV1
    ) -> ProductionControlBackendOutcome:
        provider = self.config.post_change_context_provider
        if provider is None:
            raise ProductionControlActionError("post-change context provider unavailable")
        context = dict(provider(request))
        context["expected_runtime_source_identity"] = request.target_runtime_source_head
        result = evaluate_post_change_gate(**context)
        if result.get("status") != "PASS":
            raise ProductionControlActionError("post-change validation blocked")
        digest = str(result.get("receipt_sha256") or result.get("result_sha256") or _digest(result))
        if len(digest) != 64:
            digest = _digest(result)
        return ProductionControlBackendOutcome(
            "VERIFIED",
            "POST_CHANGE_VALIDATED",
            result,
            evidence_refs=("post-change-gate",),
            evidence_digests=(digest,),
        )

    def apply(self, request: ProductionControlActionRequestV1) -> ProductionControlBackendOutcome:
        if request.action == RETIRE_FULL_PLAN_RUN:
            return self._retire(request)
        if request.action == SYNC_OPERATIONAL_RUNTIME_IDENTITY:
            return self._sync_runtime_identity(request)
        if request.action == OCP_QUIESCE:
            return self._ocp_units(request, start=False)
        if request.action == OCP_RESUME:
            return self._ocp_units(request, start=True)
        if request.action == P4_CUTOVER:
            return self._p4_cutover(request)
        if request.action == POST_CHANGE_VALIDATE:
            return self._post_change_validate(request)
        raise ProductionControlActionError("unsupported production control action")


class ProductionControlActionExecutor:
    def __init__(
        self,
        *,
        harness_state_root: str | Path,
        backend: ProductionControlBackend,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self.state_root = Path(harness_state_root).expanduser().absolute()
        self.backend = backend
        self.ledger = ProductionControlLedger(
            self.state_root, lock_timeout_seconds=lock_timeout_seconds
        )

    def execute(
        self,
        request: ProductionControlActionRequestV1 | Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> ProductionControlActionResultV1:
        req = (
            request
            if isinstance(request, ProductionControlActionRequestV1)
            else ProductionControlActionRequestV1.from_mapping(request)
        )
        proof_ref, proof_digest = validate_approval_proof(
            req, harness_state_root=self.state_root, now=now
        )
        lock = self.ledger.acquire()
        try:
            self.ledger.bind_request(req)
            events = self.ledger.events(req)
            verified = [event for event in events if event.get("status") == "VERIFIED"]
            if verified:
                event = verified[-1]
                return ProductionControlActionResultV1(
                    schema_version=PRODUCTION_CONTROL_RESULT_SCHEMA_V1,
                    request_id=req.request_id,
                    action=req.action,
                    status="VERIFIED",
                    result_class="IDEMPOTENT_REPLAY_VERIFIED",
                    request_digest=req.request_digest,
                    idempotency_key=req.idempotency_key,
                    evidence_refs=tuple(event.get("evidence_refs") or ()),
                    evidence_digests=tuple(event.get("evidence_digests") or ()),
                    effect_digest=str(event.get("effect_digest") or ""),
                )

            effect_started = any(
                event.get("phase") == "EFFECT_STARTED"
                for event in events
            )
            if effect_started:
                self.ledger.append(
                    req,
                    status="BLOCKED",
                    phase="AMBIGUOUS_EFFECT",
                    result_class="AMBIGUOUS_EFFECT_RETRY_FORBIDDEN",
                    evidence_refs=(proof_ref,),
                    evidence_digests=(proof_digest,),
                )
                raise ProductionControlActionError("AMBIGUOUS_EFFECT_RETRY_FORBIDDEN")

            current_digest = self.backend.current_state_digest(req)
            if current_digest != req.expected_state_sha256:
                self.ledger.append(
                    req,
                    status="BLOCKED",
                    phase="STALE_STATE",
                    result_class="EXPECTED_STATE_MISMATCH",
                    evidence_refs=(proof_ref,),
                    evidence_digests=(proof_digest,),
                )
                raise ProductionControlActionError("EXPECTED_STATE_MISMATCH")

            self.ledger.append(
                req,
                status="PREPARED",
                phase="VALIDATED",
                result_class="ACTION_PREPARED",
                evidence_refs=(proof_ref,),
                evidence_digests=(proof_digest,),
            )
            self.ledger.append(
                req,
                status="PREPARED",
                phase="EFFECT_STARTED",
                result_class="ACTION_EFFECT_STARTED",
                evidence_refs=(proof_ref,),
                evidence_digests=(proof_digest,),
            )
            try:
                outcome = self.backend.apply(req)
            except Exception as exc:
                self.ledger.append(
                    req,
                    status="BLOCKED",
                    phase="EFFECT_AMBIGUOUS",
                    result_class="ACTION_EFFECT_AMBIGUOUS",
                    evidence_refs=(proof_ref,),
                    evidence_digests=(proof_digest,),
                )
                raise ProductionControlActionError(
                    "ACTION_EFFECT_AMBIGUOUS"
                ) from exc

            self.ledger.append(
                req,
                status="APPLIED",
                phase="EFFECT_APPLIED",
                result_class=outcome.result_class,
                effect_digest=outcome.effect_digest,
                evidence_refs=outcome.evidence_refs,
                evidence_digests=outcome.evidence_digests,
            )
            if outcome.status == "ROLLED_BACK":
                self.ledger.append(
                    req,
                    status="ROLLED_BACK",
                    phase="ROLLBACK_VERIFIED",
                    result_class=outcome.result_class,
                    effect_digest=outcome.effect_digest,
                    evidence_refs=outcome.evidence_refs,
                    evidence_digests=outcome.evidence_digests,
                )
                return ProductionControlActionResultV1(
                    schema_version=PRODUCTION_CONTROL_RESULT_SCHEMA_V1,
                    request_id=req.request_id,
                    action=req.action,
                    status="ROLLED_BACK",
                    result_class=outcome.result_class,
                    request_digest=req.request_digest,
                    idempotency_key=req.idempotency_key,
                    evidence_refs=outcome.evidence_refs,
                    evidence_digests=outcome.evidence_digests,
                    effect_digest=outcome.effect_digest,
                )
            if outcome.status != "VERIFIED":
                raise ProductionControlActionError("backend result not verified")
            self.ledger.append(
                req,
                status="VERIFIED",
                phase="POSTCONDITION_VERIFIED",
                result_class=outcome.result_class,
                effect_digest=outcome.effect_digest,
                evidence_refs=outcome.evidence_refs,
                evidence_digests=outcome.evidence_digests,
            )
            return ProductionControlActionResultV1(
                schema_version=PRODUCTION_CONTROL_RESULT_SCHEMA_V1,
                request_id=req.request_id,
                action=req.action,
                status="VERIFIED",
                result_class=outcome.result_class,
                request_digest=req.request_digest,
                idempotency_key=req.idempotency_key,
                evidence_refs=outcome.evidence_refs,
                evidence_digests=outcome.evidence_digests,
                effect_digest=outcome.effect_digest,
            )
        finally:
            self.ledger.release(lock)
