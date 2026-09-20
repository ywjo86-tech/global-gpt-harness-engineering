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
  if "$PREFIX/bin/graphify" --version 2>/dev/null | grep -F "$VERSION" >/dev/null; then
    exit 0
  fi
  rm -rf "$PREFIX"
fi
# venv console scripts embed the temporary prefix; rewrite them before atomic promotion.
for script in "$NEW/bin/graphify" "$NEW/bin/graphify-mcp"; do
  if [[ -f "$script" ]]; then
    sed -i "1s|^#!.*|#!$PREFIX/bin/python|" "$script"
  fi
done
mv "$NEW" "$PREFIX"
"$PREFIX/bin/graphify" --version | grep -F "$VERSION"
trap 'rm -rf "$TMP"' EXIT
printf '%s\n' "$PREFIX/bin/graphify"
