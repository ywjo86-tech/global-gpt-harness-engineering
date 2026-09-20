#!/usr/bin/env bash
set -euo pipefail
umask 077

VERSION=3.8.50
EXPECTED_INTEGRITY='sha512-qK6REDWQYGh8lwGwDgFMsBqAMXnxIePudr8cSuSYeB9iIlywNhDJxHKt6Cwa31lPci8jXE5bbvl+az0lvyt0Mg=='
PREFIX="$HOME/.local/share/gch/omniroute-runtime"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP" "$PREFIX.new"; }
trap cleanup EXIT

NODE_VERSION="$(node --version)"
node - "$NODE_VERSION" <<'NODE'
const raw = process.argv[2].replace(/^v/, '').split('.').map(Number);
const [major, minor, patch] = raw;
const ok = (major === 22 && (minor > 22 || (minor === 22 && patch >= 2))) ||
           (major >= 24 && major < 27);
if (!ok) process.exit(1);
NODE

PACK_JSON="$(npm pack "omniroute@$VERSION" --json --pack-destination "$TMP")"
TARBALL="$TMP/$(python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["filename"])' <<<"$PACK_JSON")"
INTEGRITY="$(python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["integrity"])' <<<"$PACK_JSON")"
test "$INTEGRITY" = "$EXPECTED_INTEGRITY"

mkdir -p "$(dirname "$PREFIX")"
rm -rf "$PREFIX.new"
mkdir -p "$PREFIX.new"
npm install --prefix "$PREFIX.new" --omit=dev --no-audit --no-fund "$TARBALL"
"$PREFIX.new/node_modules/.bin/omniroute" --version | grep -Fx '3.8.50'

ROLLBACK=""
if [ -e "$PREFIX" ]; then
  ROLLBACK="$PREFIX.rollback-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$PREFIX" "$ROLLBACK"
fi
mv "$PREFIX.new" "$PREFIX"
trap 'rm -rf "$TMP"' EXIT

printf 'OMNIROUTE_RUNTIME=%s\n' "$PREFIX"
printf 'OMNIROUTE_VERSION=%s\n' "$VERSION"
printf 'OMNIROUTE_INTEGRITY=%s\n' "$INTEGRITY"
if [ -n "$ROLLBACK" ]; then
  printf 'OMNIROUTE_ROLLBACK=%s\n' "$ROLLBACK"
fi
