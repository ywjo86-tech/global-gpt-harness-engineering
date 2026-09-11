#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${1:-https://github.com/ywjo86-tech/global-gpt-harness-engineering.git}"
INSTALL_ROOT="${2:-$HOME/AI-Workspace}"
FOLDER_NAME="${3:-global-gpt-harness-engineering}"
BRANCH="${4:-main}"
TARGET="$INSTALL_ROOT/$FOLDER_NAME"

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 2; }
mkdir -p "$INSTALL_ROOT"

if [[ -e "$TARGET" ]]; then
  [[ -d "$TARGET/.git" ]] || { echo "Target exists but is not a Git repository: $TARGET" >&2; exit 3; }
  git -C "$TARGET" fetch origin "$BRANCH"
  git -C "$TARGET" checkout "$BRANCH"
  git -C "$TARGET" pull --ff-only origin "$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO_URL" "$TARGET"
fi

missing=()
for relative in AGENTS.md .agents docs/harness templates; do
  [[ -e "$TARGET/$relative" ]] || missing+=("$relative")
done
if (( ${#missing[@]} )); then
  printf 'Missing required paths: %s\n' "${missing[*]}" >&2
  exit 4
fi

printf 'Global harness installed successfully.\nPath: %s\n' "$TARGET"
