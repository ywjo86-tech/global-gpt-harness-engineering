# Main Development Plan

## 1. Project Overview
- Project Name: Global Agent Feature Development V02
- Purpose: Establish a hierarchical development planning workflow for the Global Agent so future work starts from a deep, controlled plan rather than immediate implementation.
- Core Problem: Planning is currently concentrated in a single large report, which increases token usage and makes execution harder to scope.
- Expected Outcome: A reusable planning system built around a Main Development Plan, Step Detail Plans, optional Nested Detail Plans, PLAN_INDEX linkage, step handoffs, and final deployment handoff.

## 2. Requirement Analysis
- User Requirements:
  - Analyze the current repository structure before changing files.
  - Propose files to create or modify before implementation.
  - Propose the first loop target before any edits.
  - Use the V02 final report as the development policy source.
- Explicit Requirements:
  - The Main Development Plan must act as the control document.
  - Step Detail Plans must break major phases into smaller execution units.
  - Nested Detail Plans must be available when a step becomes too complex.
  - PLAN_INDEX.md must connect all planning documents.
  - Each phase must end with a handoff document.
- Inferred Requirements:
  - The repository should favor doc-driven harness development over ad hoc execution.
  - The planning system should reduce repeated full-document reads.
  - The workflow should minimize user intervention while preserving approval points.
- Questions to Confirm Later:
  - Whether any global `.codex` agent files need policy updates in a later loop.
  - Whether the planning system should also be mirrored into `docs/harness/` for broader reuse.

## 3. Scope Definition
- Included:
  - Hierarchical planning documents for V02.
  - Indexing and handoff conventions.
  - Progress tracking and QA criteria for document-driven execution.
  - Scope control rules and change-candidate tracking.
- Excluded:
  - Direct code changes outside the V02 planning artifact set.
  - Broad repository restructuring.
  - Large edits to existing global harness policy files in the first loop.
- Scope Expansion Guardrails:
  - Do not add implementation work that is not already represented in the active plan tree.
  - Do not expand into unrelated harness refactors without explicit approval.
  - Record new ideas as scope change candidates instead of silently absorbing them.
- Future Improvement Candidates:
  - Mirroring the hierarchy pattern into broader harness documentation.
  - Adding reusable templates for plan, step, nested, and handoff documents.
  - Creating validation helpers for link integrity and phase status checks.

## 4. Architecture Overview
- Main Control Layer:
  - `MAIN_DEVELOPMENT_PLAN.md` defines project direction, scope, risk, and phase intent.
- Coordination Layer:
  - `PLAN_INDEX.md` links the active main plan, detail plans, nested plans, and handoff files.
- Execution Layer:
  - `STEP_NN_DETAIL_PLAN.md` documents each phase in bounded detail.
  - `STEP_NN_MM_DETAIL_PLAN.md` splits complex phase work into smaller units when needed.
- Handoff Layer:
  - `HANDOFF_STEP_NN.md` captures phase completion, QA result, and transition notes.
  - `HANDOFF_FINAL_DEPLOYMENT.md` consolidates the final delivery state.
- External Dependencies:
  - Repository-level docs and existing harness policy files for alignment.
  - No runtime dependency is required for this planning phase.

## 5. Development Phases

| Phase | Step Name | Purpose | Linked Detail Plan | Completion Criteria |
|---|---|---|---|---|
| 1 | Planning Foundation | Establish the control document, directory structure, and working conventions. | `STEP_01_DETAIL_PLAN.md` | Main plan approved and ready for indexed execution. |
| 2 | Plan Index and Step Templates | Define PLAN_INDEX linkage, step plan structure, and nested plan rules. | `STEP_02_DETAIL_PLAN.md` | Detail plan templates are unambiguous and reusable. |
| 3 | Handoff and Progress System | Define step handoff, final handoff, and progress tracking records. | `STEP_03_DETAIL_PLAN.md` | Handoff files and progress rules are fully specified. |
| 4 | QA and Release Readiness | Define validation checks, scope control, and release readiness criteria. | `STEP_04_DETAIL_PLAN.md` | The planning system is ready for repeatable use. |

## 6. Evaluation Criteria
- Quantitative Criteria:
  - 100% of planned hierarchy files are linked in the index.
  - 100% of phases have a named detail plan.
  - 0 unresolved file-path references in the planning set.
  - 0 unapproved scope expansions in the active loop.
- QA Criteria:
  - Planning artifacts are internally consistent.
  - Handoff requirements are explicit.
  - Failure conditions and stop conditions are recorded.
- UI Criteria:
  - Not applicable for the current scope.
  - If UI work is introduced later, a dedicated UI Expected Preview must be created before implementation.
- Final Readiness Criteria:
  - Main plan, plan index, step plans, and handoff files are connected.
  - Phase ownership and completion criteria are clear.
  - Future loops can proceed using only the active plan documents.

## 7. Handoff Strategy
- Step Handoff:
  - At the end of each phase, record what changed, what was verified, and what the next phase needs.
  - Update PLAN_INDEX status after the handoff is complete.
- Final Deployment Handoff:
  - Summarize the complete hierarchy, validation outcome, and any remaining scope candidates.
  - Preserve the final state of the planning system for future reuse.

## 8. Progress Tracking
- Total Phases: 4
- Progress Calculation: completed phases / total phases
- Current Progress: 0%
- Tracking Rule:
  - Update progress only after a phase handoff is complete.
  - Do not count draft-only work as completed progress.

## 9. Risk Prediction
- Expected Risks:
  - The plan tree may grow too large if step scope is not controlled.
  - Nested plans may be created too early and add unnecessary overhead.
  - Index drift may occur if handoffs are not reflected promptly.
- Direction Change Risk:
  - New planning ideas may pull the workflow away from the original report.
- Scope Expansion Risk:
  - Broad refactors can appear attractive but would violate the one-loop focus.
- Technical Uncertainty:
  - Future policy files may need coordination across `.agents`, `.codex`, and `docs/harness`.
- Mitigation Strategy:
  - Keep one loop focused on one target.
  - Record all new ideas as scope change candidates.
  - Use handoff documents as the only source of phase completion truth.

## 10. Linked Detail Plans

| Detail Plan | Purpose | Status |
|---|---|---|
| `STEP_01_DETAIL_PLAN.md` | Planning foundation | Not Started |
| `STEP_02_DETAIL_PLAN.md` | Plan index and step templates | Not Started |
| `STEP_03_DETAIL_PLAN.md` | Handoff and progress system | Not Started |
| `STEP_04_DETAIL_PLAN.md` | QA and release readiness | Not Started |

## 11. Scope Change Candidate Handling
- Discovery Rule:
  - Any idea outside the active phase must be written down instead of implemented immediately.
- Record Format:
  - Discovery point
  - Candidate change
  - Included in current main plan or not
  - Included in current detail plan or not
  - Impact scope
  - Required approval
- Processing Rule:
  - Current phase changes only.
  - Future version candidate registration is allowed.
  - User approval is required before scope expansion.

## 12. Stop Conditions
- Stop if:
  - The current loop tries to touch more than one target.
  - A file-path reference becomes inconsistent.
  - An unapproved scope expansion is required.
  - The next phase depends on a document that does not yet exist.
- User Confirmation Needed When:
  - A later loop needs to modify `.codex` agents or repo-wide policy files.
  - A nested detail plan becomes necessary.
  - Any UI work is introduced.

