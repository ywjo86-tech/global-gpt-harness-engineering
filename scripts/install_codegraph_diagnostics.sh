#!/usr/bin/env bash
set -euo pipefail
VERSION=0.20.1
TAG=v0.20.1
ASSET=codegraph-server-linux-x64
EXPECTED=32b26422fa5ffe0a130955b7f7df771f722b2d427d67f53f104d9907bdfb24a6
PREFIX="$HOME/.local/share/gch/diagnostics/codegraph/$VERSION"
TARGET="$PREFIX/bin/codegraph-server"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
URL="https://github.com/codegraph-ai/CodeGraph/releases/download/$TAG/$ASSET"

curl --proto '=https' --tlsv1.2 -fL "$URL" -o "$TMP/$ASSET"
printf '%s  %s\n' "$EXPECTED" "$TMP/$ASSET" | sha256sum -c -
chmod 0755 "$TMP/$ASSET"
"$TMP/$ASSET" --help >/dev/null

if [[ -f "$TARGET" ]]; then
  printf '%s  %s\n' "$EXPECTED" "$TARGET" | sha256sum -c -
  printf '%s\n' "$TARGET"
  exit 0
fi
mkdir -p "$PREFIX/bin"
install -m 0755 "$TMP/$ASSET" "$TARGET.new-$$"
mv "$TARGET.new-$$" "$TARGET"
printf '%s\n' "$TARGET"
