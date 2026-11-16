#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_bpfw
cd "$PROJECT_ROOT"
printf '%s\n' 'BPFW_ALPHA14_ADOPTION'
printf '%s\n' '1) compact agent entry:'
printf '   %s\n' "$BPFW_BIN batch audit --json"
printf '%s\n' '2) if missing_uids > 0, plan only:'
printf '   %s\n' "$BPFW_BIN batch generate-uids --json"
printf '%s\n' '3) inspect the plan, then explicitly:'
printf '   %s\n' "$BPFW_BIN batch apply PLAN_ID"
printf '%s\n' '4) review compact candidates:'
printf '   %s\n' "$BPFW_BIN compact"
printf '%s\n' '5) normalize only after reviewing proposed changes:'
printf '   %s\n' "$BPFW_BIN normalize"
printf '%s\n' '6) final:'
printf '   %s\n' "$BPFW_BIN verify"
