# Meta Harness Installation

## Purpose

Meta Harness is the global harness repository used to design and install project-local Codex agent teams, reusable skills, templates, project pipelines, QA gates, and release handoff workflows.

In this repository, Meta Harness is installed by cloning or updating:

```text
https://github.com/ywjo86-tech/global-gpt-harness-engineering.git
```

## One-Command Install

On another Windows PC, run PowerShell and execute:

```powershell
iwr -Uri https://raw.githubusercontent.com/ywjo86-tech/global-gpt-harness-engineering/main/scripts/install-meta-harness.ps1 -OutFile install-meta-harness.ps1; powershell -ExecutionPolicy Bypass -File .\install-meta-harness.ps1
```

Default install path:

```text
%USERPROFILE%\Documents\AI-Workspace\global-gpt-harness-engineering
```

## What the Installer Does

1. Checks that Git is installed.
2. Creates `%USERPROFILE%\Documents\AI-Workspace` if needed.
3. Clones the Meta Harness repository if it is missing.
4. Updates the repository with `git pull --ff-only` if it already exists.
5. Verifies required harness paths:
   - `AGENTS.md`
   - `.agents`
   - `docs/harness`
   - `templates`

## First Test in Codex

Open the installed folder in Codex and ask:

```text
현재 Meta Harness에서 사용 가능한 스킬과 새 프로젝트 오케스트레이터를 요약해줘.
파일 수정 없이 확인만 해줘.
```

## Start a New Project

Use:

```text
새 프로젝트 시작

아이디어:
- ...

요구사항:
- ...

제약사항:
- ...

원하는 산출물:
- ...
```

## Notes

- This installer does not copy secrets, `.env` files, `_workspace/` artifacts, or project implementation folders.
- Private repositories may require GitHub authentication on the target PC.
- If Git is missing, install Git for Windows first and rerun the installer.
