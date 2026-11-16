#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
if [[ $# -ne 1 ]]; then
  echo "usage: $0 PLAN_ID" >&2
  exit 2
fi
run_bpfw batch apply "$1"
