#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export PROJECT_ROOT="${PROJECT_ROOT:-$ROOT}"
BPFW_BIN="${BPFW_BIN:-bpfw}"

require_bpfw() {
  if ! command -v "$BPFW_BIN" >/dev/null 2>&1; then
    cat >&2 <<'MSG'
BPFW_NOT_FOUND: this project does not vendor BPFW.
Install BPFW 0.2.0a14+ separately, ensure it is on PATH, or set BPFW_BIN=/path/to/bpfw.
MSG
    exit 127
  fi
  local raw ver num
  raw="$($BPFW_BIN version 2>/dev/null || true)"
  ver="$(printf '%s' "$raw" | grep -Eo '0\.2\.0a[0-9]+' | head -1 || true)"
  if [[ -z "$ver" ]]; then
    echo "BPFW_VERSION_UNRECOGNIZED: $raw" >&2
    exit 2
  fi
  num="${ver##*a}"
  if (( num < 14 )); then
    echo "BPFW_VERSION_TOO_OLD: need 0.2.0a14+, got $ver" >&2
    exit 2
  fi
}

run_bpfw() {
  require_bpfw
  cd "$PROJECT_ROOT"
  exec "$BPFW_BIN" "$@"
}
