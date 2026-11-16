#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

VENDOR_DIR="${BPFW_VENDOR_DIR:-vendor/bpfw}"

if [[ -f .bpfw/blueprint.yaml ]] && grep -Eq "path:[[:space:]]+${VENDOR_DIR//\//\\/}/" .bpfw/blueprint.yaml; then
  echo "REFUSING: current Blueprint authority still binds artifacts under $VENDOR_DIR." >&2
  echo "Update the Blueprint authority to drop the vendored artifacts before removing the runtime." >&2
  exit 2
fi

if [[ -d "$VENDOR_DIR" ]]; then
  rm -rf -- "$VENDOR_DIR"
  rmdir "$(dirname "$VENDOR_DIR")" 2>/dev/null || true
  echo "Removed project-local $VENDOR_DIR runtime."
else
  echo "No project-local $VENDOR_DIR runtime is present."
fi

if command -v bpfw >/dev/null 2>&1; then
  echo "External BPFW: $(bpfw version 2>/dev/null || true)"
else
  cat <<'MSG'
External BPFW is not installed yet.
Install BPFW 0.2.0a14+ separately, then run:
  ./tools/blueprint/audit.sh
  ./tools/blueprint/verify.sh
MSG
fi
