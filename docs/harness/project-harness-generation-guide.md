# Project Harness Generation Guide

Use this guide when creating a Codex harness for a new project repository.

## 1. Intake

Capture the business reason for the project before designing files or agents.

Required output:

- Business purpose
- Target users or stakeholders
- In-scope and out-of-scope work
- Success criteria
- Sensitive data notes

Recommended skill: `project-intake`

## 2. Requirements

Turn intake notes into implementation-ready requirements.

Required output:

- Functional requirements
- Non-functional requirements
- Constraints and assumptions
- Risks
- Acceptance criteria
- Open questions

Recommended skill: `requirements-analysis`

## 3. Harness Design

Choose the smallest useful harness structure for the project.

Required output:

- Agent roles, if needed
- Reusable skills, if repeated work exists
- Project docs to create
- Template files to copy
- Local handoff artifacts under `_workspace/`
- Exclusions and security notes

Recommended skill: `harness-design`

## 4. Implementation Plan

Define the exact work before editing files.

Required output:

- Target files
- Change sequence
- Verification method
- Documentation updates
- Known risks

Keep implementation code in the project repository, not in this PMO repository.

## 5. QA

Review the project harness before release or handoff.

Required output:

- Changed file list
- Test or manual verification evidence
- Security review notes
- Documentation coverage
- Release readiness decision

Recommended skill: `qa-release-review`

## 6. Release Handoff

Prepare the final operating notes.

Required output:

- Summary of what was created
- How to run, test, or maintain the project
- Known limitations
- Follow-up work
- Owner or handoff contact

## Standard Flow

Intake -> Requirements -> Harness design -> Implementation plan -> QA -> Release handoff
