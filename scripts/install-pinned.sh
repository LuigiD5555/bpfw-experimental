#!/usr/bin/env bash
# Wrapper around install.sh that pins tree-sitter to the 0.25.x series.
#
# The wheel declares `tree-sitter<0.27,>=0.25` for the multilang extra, so a
# plain install resolves tree-sitter 0.26.0. That release is incompatible with
# tree-sitter-go 0.25.0: scanning several Go files in one process segfaults
# (SIGSEGV, exit 139) inside the native binding while reading node byte offsets,
# which takes down `bpfw verify` and `bpfw batch audit` on any Go project.
#
# Verified against origami_v5 (56 Go files): 0.25.0, 0.25.1 and 0.25.2 all scan
# cleanly; 0.26.0 segfaults reproducibly. Pinning below 0.26 keeps the resolver
# inside the working series while staying within the wheel's declared range.
#
# Drop this pin once upstream ships a tree-sitter-go built against 0.26.
#
# Usage: ./install-pinned.sh [same options as install.sh]

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${BPFW_HOME:-$HOME/.local/share/bpfw}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TREE_SITTER_PIN="${TREE_SITTER_PIN:-tree-sitter<0.26}"

"$HERE/install.sh" "$@"

# install.sh resolves the version from wheel metadata; read it back the same way
# so this wrapper never hard-codes a release number.
WHEEL="${BPFW_WHEEL:-$(find "$HERE/../dist" -maxdepth 1 -name 'blueprint_framework-*.whl' -print -quit 2>/dev/null)}"
VERSION="$("$PYTHON_BIN" - "$WHEEL" <<'PY'
import sys
import zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    metadata_name = next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
    metadata = archive.read(metadata_name).decode('utf-8', errors='strict')
for line in metadata.splitlines():
    if line.startswith('Version: '):
        print(line.split(': ', 1)[1].strip())
        break
else:
    raise SystemExit('wheel metadata has no Version field')
PY
)"

APP_PYTHON="$APP_ROOT/versions/$VERSION/bin/python"
[[ -x "$APP_PYTHON" ]] || { echo "Expected interpreter not found: $APP_PYTHON" >&2; exit 1; }

# Only downgrade when the resolver actually pulled an affected release; a
# no-multilang install has no tree-sitter to correct.
if "$APP_PYTHON" -c "import tree_sitter" 2>/dev/null; then
  "$APP_PYTHON" -m pip --disable-pip-version-check install -q "$TREE_SITTER_PIN"
  "$APP_PYTHON" -c "
from importlib.metadata import version
print(f'tree-sitter pinned: {version(\"tree-sitter\")} (tree-sitter-go {version(\"tree-sitter-go\")})')
"
else
  echo "tree-sitter not installed (multilang skipped); no pin applied."
fi
