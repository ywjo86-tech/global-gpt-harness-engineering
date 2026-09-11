# HamoniKR / Linux Migration Guide

Status: migration groundwork branch (`migration/hamonikr-linux`)

## Compatibility result

The global harness core is substantially OS-neutral. Runtime modules such as `runtime/orchestrator/codex_adapter.py` use `pathlib`, `os`, `shlex`, `shutil.which`, and argument-list based `subprocess` calls, so they are suitable for Linux provided the required CLI tools are installed on PATH.

The primary Windows bindings found in the current repository are the installer/helper layer and Windows-specific command examples:

- `scripts/install-global-harness.ps1`
- `scripts/install-meta-harness.ps1`
- documentation examples containing PowerShell and `C:\Users\...` paths

The PowerShell files remain available for Windows. This branch adds Linux equivalents instead of deleting Windows support.

## Added Linux installers

```text
scripts/install-global-harness.sh
scripts/install-meta-harness.sh
```

Default Linux installation root:

```text
$HOME/AI-Workspace/global-gpt-harness-engineering
```

Run:

```bash
bash scripts/install-global-harness.sh
```

To install the migration branch during validation:

```bash
bash scripts/install-global-harness.sh \
  https://github.com/ywjo86-tech/global-gpt-harness-engineering.git \
  "$HOME/AI-Workspace" \
  global-gpt-harness-engineering \
  migration/hamonikr-linux
```

## Recommended HamoniKR prerequisites

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip curl
```

Install Codex or other CLIs separately and verify they are on PATH before enabling CLI execution modes.

## Validation

From the repository root, run the existing test suite with a Linux Python environment. Any test that assumes a literal Windows path should be classified as a fixture/documentation issue unless the runtime itself depends on that path.

Do not replace portable path handling with hard-coded `/home/...` paths in runtime modules. Linux home/workspace locations should remain parameters, environment variables, or paths derived from the working directory.

## Migration rule

Keep the repository cross-platform:

- `.ps1` = Windows installation/administration compatibility
- `.sh` = Linux installation/administration compatibility
- Python runtime = OS-neutral unless an explicit OS adapter is required
- secrets = environment or ignored `.env`, never committed
