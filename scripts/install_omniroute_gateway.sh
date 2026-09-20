#!/usr/bin/env bash
set -euo pipefail
umask 077

VERSION=3.8.50
EXPECTED_INTEGRITY='sha512-qK6REDWQYGh8lwGwDgFMsBqAMXnxIePudr8cSuSYeB9iIlywNhDJxHKt6Cwa31lPci8jXE5bbvl+az0lvyt0Mg=='
GCH_ROOT="$HOME/.local/share/gch/omniroute"
PREFIX="$HOME/.local/share/gch/omniroute/runtime"
PARENT="$GCH_ROOT"
WRAPPER="$HOME/.local/bin/gch-omniroute"
LOCK_FILE="$GCH_ROOT/install.lock"
mkdir -p "$PARENT"
exec 9>"$LOCK_FILE"
flock -n 9 || { printf "OmniRoute install already running\n" >&2; exit 75; }
TMP="$(mktemp -d)"
STAGE="$(mktemp -d "$PARENT/runtime.new.XXXXXX")"
cleanup() {
  rm -rf "$TMP"
  if [ -n "${STAGE:-}" ] && [ -d "$STAGE" ]; then rm -rf "$STAGE"; fi
}
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

npm install --prefix "$STAGE" --omit=dev --no-audit --no-fund "$TARBALL"
"$STAGE/node_modules/.bin/omniroute" --version | grep -Fx '3.8.50'

ROLLBACK=""
if [ -e "$PREFIX" ]; then
  ROLLBACK="$PREFIX.rollback-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$PREFIX" "$ROLLBACK"
fi
mv "$STAGE" "$PREFIX"
STAGE=""
mkdir -p "$(dirname "$WRAPPER")"
ln -sfn "$PREFIX/node_modules/.bin/omniroute" "$WRAPPER"
trap 'rm -rf "$TMP"' EXIT

printf 'OMNIROUTE_RUNTIME=%s\n' "$PREFIX"
printf 'OMNIROUTE_VERSION=%s\n' "$VERSION"
printf 'OMNIROUTE_INTEGRITY=%s\n' "$INTEGRITY"
if [ -n "$ROLLBACK" ]; then
  printf 'OMNIROUTE_ROLLBACK=%s\n' "$ROLLBACK"
fi
