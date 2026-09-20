#!/usr/bin/env bash
set -euo pipefail
VERSION=0.9.58
WHEEL=graphifyy-0.9.58-py3-none-any.whl
EXPECTED=e239803288e91c723d6e30540860bd6d5a1dc3f0914b9fc1104b0233e98aaeb8
PREFIX="$HOME/.local/share/gch/diagnostics/graphify/$VERSION"
TMP="$(mktemp -d)"
NEW="${PREFIX}.new-$$"
trap 'rm -rf "$TMP" "$NEW"' EXIT

python3.12 -m pip download --no-deps --only-binary=:all: --dest "$TMP" "graphifyy==$VERSION"
printf '%s  %s\n' "$EXPECTED" "$TMP/$WHEEL" | sha256sum -c -
python3.12 -m venv "$NEW"
"$NEW/bin/python" -m pip install "$TMP/$WHEEL[mcp]"
"$NEW/bin/graphify" --version | grep -F "$VERSION"

mkdir -p "$(dirname "$PREFIX")"
if [[ -e "$PREFIX" ]]; then
  "$PREFIX/bin/graphify" --version | grep -F "$VERSION"
  exit 0
fi
mv "$NEW" "$PREFIX"
trap 'rm -rf "$TMP"' EXIT
printf '%s\n' "$PREFIX/bin/graphify"
