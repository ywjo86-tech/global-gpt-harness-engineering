from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class DiscoveryLevel(str, Enum):
    EXISTING_CAPABILITY = "EXISTING_CAPABILITY"
    DISCOVERY = "DISCOVERY"
    PROJECT_INSTALL = "PROJECT_INSTALL"
    GLOBAL_INSTALL = "GLOBAL_INSTALL"


class DiscoveryStatus(str, Enum):
    EXISTING = "EXISTING"
    DISCOVERY_REQUIRED = "DISCOVERY_REQUIRED"
    DISCOVERY_COMPLETED = "DISCOVERY_COMPLETED"
    CANDIDATE_EVALUATED = "CANDIDATE_EVALUATED"
    INSTALL_REQUIRED = "INSTALL_REQUIRED"
    BLOCKED = "BLOCKED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


class CandidateEvaluationState(str, Enum):
    UNASSESSED = "UNASSESSED"
    METADATA_VALIDATED = "METADATA_VALIDATED"
    CONTENT_VALIDATED = "CONTENT_VALIDATED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    SAFE_FOR_CONSIDERATION = "SAFE_FOR_CONSIDERATION"
    BLOCKED = "BLOCKED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


class CandidateAdoptionState(str, Enum):
    PENDING_EVALUATION = "PENDING_EVALUATION"
    SAFE_FOR_CONSIDERATION = "SAFE_FOR_CONSIDERATION"
    SELECTED_FOR_ADOPTION = "SELECTED_FOR_ADOPTION"
    PENDING_SUPPLY_CHAIN_REVIEW = "PENDING_SUPPLY_CHAIN_REVIEW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    INSTALL_AUTHORIZED = "INSTALL_AUTHORIZED"
    BLOCKED = "BLOCKED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


class CandidateUseState(str, Enum):
    INSTALL_COMPLETED = "INSTALL_COMPLETED"
    ATTESTED = "ATTESTED"
    USE_AUTHORIZED = "USE_AUTHORIZED"
    USED_ASSET = "USED_ASSET"
    BLOCKED = "BLOCKED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class CandidateRisk:
    network: bool = False
    shell: bool = False
    package_install: bool = False
    secret: bool = False
    file_write: bool = False
    external_service: bool = False
    paid_service: bool = False
    deployment: bool = False
    global_change: bool = False
    destructive_action: bool = False

    @property
    def dangerous(self) -> bool:
        return any(asdict(self).values())


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    capability_id: str
    gate_id: str
    lv_id: str
    required_permissions: tuple[str, ...]
    owned_files: tuple[str, ...]
    optional: bool = False

    def __post_init__(self) -> None:
        if not self.capability_id or not self.gate_id or not self.lv_id:
            raise ValueError("capability requirement binding is incomplete")
        if not self.required_permissions or not self.owned_files:
            raise ValueError("capability requirement permissions and owned files are required")
        if any(not isinstance(value, str) or not value for value in (*self.required_permissions, *self.owned_files)):
            raise ValueError("capability requirement contains an invalid value")


@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    candidate_id: str
    source: str
    repository: str
    maintainer: str
    scope: str
    metadata: dict[str, Any]
    evaluation_state: str
    risk: CandidateRisk

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.candidate_id, self.source, self.repository, self.maintainer)):
            raise ValueError("candidate provenance is incomplete")
        if self.scope not in {"global", "project"}:
            raise ValueError("candidate scope is unknown")
        if not isinstance(self.metadata, dict) or self.metadata.get("skill_md_verified") is not True:
            raise ValueError("candidate SKILL.md verification is incomplete")
        if self.evaluation_state not in {state.value for state in CandidateEvaluationState}:
            raise ValueError("candidate evaluation is unknown")
        if not isinstance(self.risk, CandidateRisk):
            raise ValueError("candidate risk is invalid")

    def matches(self, requirement: CapabilityRequirement) -> bool:
        """Return true only for an exact permission and owned-file contract match."""
        permissions = self.metadata.get("permissions")
        owned_files = self.metadata.get("owned_files")
        if not isinstance(permissions, (list, tuple, set)) or not isinstance(owned_files, (list, tuple, set)):
            return False
        return set(requirement.required_permissions).issubset(permissions) and set(requirement.owned_files).issubset(owned_files)


@dataclass(frozen=True, slots=True)
class DiscoveryDecision:
    requirement: CapabilityRequirement
    discovery_level: DiscoveryLevel
    discovery_status: DiscoveryStatus
    selected_existing_asset: str = ""
    candidate_list: tuple[CapabilityCandidate, ...] = ()
    selected_candidate: str = ""
    blocked_reason: str = ""
    escalation_reason: str = ""
    approval_required: bool = False
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, CapabilityRequirement):
            raise ValueError("discovery requirement is invalid")
        if self.discovery_status == DiscoveryStatus.EXISTING:
            if self.discovery_level != DiscoveryLevel.EXISTING_CAPABILITY or not self.selected_existing_asset:
                raise ValueError("existing capability decision is incomplete")
        elif self.discovery_level == DiscoveryLevel.EXISTING_CAPABILITY:
            raise ValueError("existing capability level requires EXISTING status")
        if self.discovery_status in {DiscoveryStatus.BLOCKED, DiscoveryStatus.ESCALATION_REQUIRED} and not (self.blocked_reason or self.escalation_reason):
            raise ValueError("blocked or escalated decision requires a reason")
        if self.discovery_status == DiscoveryStatus.DISCOVERY_REQUIRED and self.discovery_level != DiscoveryLevel.DISCOVERY:
            raise ValueError("discovery-required status has an invalid level")
        if self.discovery_level == DiscoveryLevel.GLOBAL_INSTALL and self.discovery_status != DiscoveryStatus.ESCALATION_REQUIRED:
            raise ValueError("global install must require escalation")
        if self.discovery_level in {DiscoveryLevel.PROJECT_INSTALL, DiscoveryLevel.GLOBAL_INSTALL} and not self.approval_required:
            raise ValueError("install decision requires approval")
        if any(not isinstance(candidate, CapabilityCandidate) for candidate in self.candidate_list):
            raise ValueError("candidate list contains an invalid item")
        if self.selected_candidate:
            selected = next((candidate for candidate in self.candidate_list if candidate.candidate_id == self.selected_candidate), None)
            if (selected is None or selected.evaluation_state != CandidateEvaluationState.SAFE_FOR_CONSIDERATION.value
                    or not selected.matches(self.requirement) or selected.risk.dangerous):
                raise ValueError("selected candidate does not satisfy the capability contract")

    @property
    def discovery_required(self) -> bool:
        return self.discovery_level == DiscoveryLevel.DISCOVERY and self.discovery_status == DiscoveryStatus.DISCOVERY_REQUIRED

    @property
    def execution_allowed(self) -> bool:
        return self.discovery_status == DiscoveryStatus.EXISTING and self.discovery_level == DiscoveryLevel.EXISTING_CAPABILITY


@dataclass(slots=True)
class ProjectPaths:
    project_root: str
    development_plan: str
    changelog: str
    app_log: str
    orchestration_state_md: str
    runtime_dir: str
    orchestrator_runs_dir: str
    runtime_state_json: str
    fanout_plan_json: str
    fanin_report_json: str
    stage_gate_json: str
    threads_dir: str
    reports_dir: str

    @classmethod
    def from_root(cls, project_root: Path) -> "ProjectPaths":
        runtime_dir = project_root / "runtime"
        return cls(
            project_root=str(project_root),
            development_plan=str(project_root / "docs" / "DEVELOPMENT_PLAN.txt"),
            changelog=str(project_root / "CHANGELOG.txt"),
            app_log=str(project_root / "logs" / "app.log"),
            orchestration_state_md=str(project_root / "docs" / "harness" / "orchestration-state.md"),
            runtime_dir=str(runtime_dir),
            orchestrator_runs_dir=str(runtime_dir / "orchestrator_runs"),
            runtime_state_json=str(runtime_dir / "orchestrator_state.json"),
            fanout_plan_json=str(runtime_dir / "fanout_plan.json"),
            fanin_report_json=str(runtime_dir / "fanin_report.json"),
            stage_gate_json=str(runtime_dir / "stage_gate.json"),
            threads_dir=str(runtime_dir / "threads"),
            reports_dir=str(runtime_dir / "reports"),
        )

    def as_path_map(self) -> dict[str, Path]:
        return {key: Path(value) for key, value in asdict(self).items()}


@dataclass(slots=True)
class ExecutionContract:
    paths: ProjectPaths
    development_plan_text: str
    changelog_text: str
    app_log_text: str
    orchestration_state_text: str
    current_phase: str
    missing_files: list[str] = field(default_factory=list)
    contract_mapping: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "project_root": self.paths.project_root,
            "current_phase": self.current_phase,
            "missing_files": list(self.missing_files),
            "development_plan_path": self.paths.development_plan,
            "changelog_path": self.paths.changelog,
            "app_log_path": self.paths.app_log,
            "orchestration_state_path": self.paths.orchestration_state_md,
            "contract_mapping": dict(self.contract_mapping),
        }


@dataclass(slots=True)
class TaskSlice:
    thread_id: str
    assigned_agent: str
    input: str
    expected_output: str
    validation_criteria: list[str]
    editable_scope: list[str]
    forbidden_scope: list[str]
    merge_point: str
    status: str = "pending"
    risk_class: str = "general"
    run_id: str = ""
    run_root: str = ""
    task_prompt_path: str = ""
    input_manifest_path: str = ""
    expected_output_path: str = ""
    worker_request_path: str = ""
    output_dir: str = ""
    handoff_report_path: str = ""
    result_path: str = ""
    manual_execution_path: str = ""

    def as_request_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanningArtifact:
    current_phase: str
    planner_agent: str
    thread_count: int
    selected_agents: list[str]
    routing_notes: list[str]
    fanout_ready: bool
    execution_ready: bool
    thread_plan: list[dict[str, Any]]
    planning_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanningArtifact":
        return cls(**payload)


@dataclass(slots=True)
class WorkerRequest:
    project_root: str
    task: TaskSlice
    contract_summary: dict[str, Any]
    state_snapshot: dict[str, Any]
    extra_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": self.project_root,
            "task": asdict(self.task),
            "contract_summary": self.contract_summary,
            "state_snapshot": self.state_snapshot,
            "extra_context": self.extra_context,
        }


@dataclass(slots=True)
class WorkerResult:
    thread_id: str
    agent_name: str
    status: str
    summary: str
    findings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FanInReport:
    threads_received: list[str]
    completed_outputs: list[str]
    missing_outputs: list[str]
    failed_workers: list[str]
    conflicts: list[str]
    duplicate_work: list[str]
    requirement_coverage: str
    risk_summary: list[str]
    qa_required: bool
    next_step_decision: str
    final_handoff_readiness: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StageGateDecision:
    decision: str
    phase: str
    completion_criteria_checked: str
    evidence_reviewed: list[str]
    fan_in_reviewed: str
    open_questions: list[str]
    remaining_risks: list[str]
    next_step: str
    conditions: list[str] = field(default_factory=list)
    authorization: str = ""
    blocker_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.decision
        return payload


@dataclass(slots=True)
class RuntimeState:
    current_phase: str = "unknown"
    active_run_id: str = ""
    run_root: str = ""
    execution_mode: str = "mock"
    manual_execution_required: bool = False
    codex_cli_available: bool = False
    active_threads: list[dict[str, Any]] = field(default_factory=list)
    pending_workers: list[dict[str, Any]] = field(default_factory=list)
    completed_workers: list[dict[str, Any]] = field(default_factory=list)
    failed_workers: list[dict[str, Any]] = field(default_factory=list)
    fanout_status: str = "idle"
    fanin_status: str = "idle"
    collection_status: str = "idle"
    stage_gate_decision: dict[str, Any] = field(default_factory=dict)
    stage_gate_prompt_path: str = ""
    approval_required: bool = False
    next_step: str = ""
    last_updated: str = ""
    fanout_plan: list[dict[str, Any]] = field(default_factory=list)
    fanin_report: dict[str, Any] = field(default_factory=dict)
    collection_report: dict[str, Any] = field(default_factory=dict)
    planning_artifact: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeState":
        return cls(**payload)
