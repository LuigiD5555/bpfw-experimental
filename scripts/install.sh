#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${BPFW_HOME:-$HOME/.local/share/bpfw}"
BIN_DIR="${BPFW_BIN_DIR:-$HOME/.local/bin}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHEEL="${BPFW_WHEEL:-$(find "$HERE/../dist" -maxdepth 1 -name 'blueprint_framework-*.whl' -print -quit 2>/dev/null)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
UNINSTALL_EXISTING=0
INSTALL_MULTILANG=1
REPAIR_LEGACY_PERMISSIONS=0

usage() {
  printf '%s\n' \
    "Usage: ./install.sh [--uninstall-existing] [--repair-legacy-permissions] [--without-multilang]" \
    "" \
    "  --uninstall-existing  Remove all managed BPFW versions and runtimes first." \
    "  --repair-legacy-permissions" \
    "                        Reclaim a root-owned legacy BPFW_HOME using sudo." \
    "  --without-multilang   Skip optional Go/Rust/HTML/CSS parser packages." \
    "  --help                Show this help."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall-existing) UNINSTALL_EXISTING=1; shift ;;
    --repair-legacy-permissions) REPAIR_LEGACY_PERMISSIONS=1; shift ;;
    --without-multilang) INSTALL_MULTILANG=0; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$WHEEL" ]]; then
  echo "BPFW installer: no wheel found. Build one with python -m build (writes dist/) or set BPFW_WHEEL=/path/to/wheel." >&2
  exit 1
fi

# Read the canonical version from wheel metadata instead of duplicating a
# hard-coded release number in the installer.
VERSION="$($PYTHON_BIN - "$WHEEL" <<'PY'
import sys
import zipfile
wheel = sys.argv[1]
with zipfile.ZipFile(wheel) as archive:
    metadata_name = next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
    metadata = archive.read(metadata_name).decode('utf-8', errors='strict')
for line in metadata.splitlines():
    if line.startswith('Version: '):
        print(line.split(': ', 1)[1].strip())
        break
else:
    raise SystemExit('BPFW installer: wheel metadata has no Version field')
PY
)"
APP_HOME="$APP_ROOT/versions/$VERSION"

if [[ "$UNINSTALL_EXISTING" -eq 1 ]]; then
  case "$APP_ROOT" in
    ""|/|"$HOME"|"$HOME/.local"|"$HOME/.local/share")
      echo "Refusing unsafe BPFW_HOME target: $APP_ROOT" >&2
      exit 1 ;;
  esac
  foreign_owner=""
  if [[ -e "$APP_ROOT" ]]; then
    foreign_owner="$(find "$APP_ROOT" ! -uid "$(id -u)" -print -quit 2>/dev/null || true)"
  fi
  if [[ -n "$foreign_owner" ]]; then
    if [[ "$REPAIR_LEGACY_PERMISSIONS" -eq 1 ]]; then
      echo "Repairing ownership of legacy BPFW installation: $APP_ROOT"
      sudo chown -R "$(id -u):$(id -g)" -- "$APP_ROOT"
    else
      echo "BPFW found legacy files not owned by the current user: $foreign_owner" >&2
      echo "Re-run with --repair-legacy-permissions to reclaim only $APP_ROOT." >&2
      exit 1
    fi
  fi
  if [[ -x "$APP_ROOT/uninstall.sh" ]]; then
    "$APP_ROOT/uninstall.sh" --all
  else
    if [[ -L "$BIN_DIR/bpfw" ]]; then
      old_target="$(readlink "$BIN_DIR/bpfw")"
      case "$old_target" in "$APP_ROOT"/*) rm -f "$BIN_DIR/bpfw" ;; esac
    fi
    [[ -d "$APP_ROOT/versions" ]] && rm -rf -- "$APP_ROOT/versions"
    [[ -d "$APP_ROOT/runtimes" ]] && rm -rf -- "$APP_ROOT/runtimes"
  fi
fi

mkdir -p "$APP_ROOT/versions"
rm -rf "$APP_HOME"
"$PYTHON_BIN" -m venv "$APP_HOME"
if [[ "$INSTALL_MULTILANG" -eq 1 ]]; then
  "$APP_HOME/bin/python" -m pip --disable-pip-version-check install "${WHEEL}[multilang]"
else
  "$APP_HOME/bin/python" -m pip --disable-pip-version-check install "$WHEEL"
fi

# Materialize and verify the private PipeCraft runtime now, not on the user's first command.
"$APP_HOME/bin/python" - <<'PY'
from bpfw.runtime.pipecraft import PipeCraftRuntimeManager
info = PipeCraftRuntimeManager().ensure_installed()
print(f"Managed PipeCraft {info.version}: {info.path}")
PY

mkdir -p "$BIN_DIR"
install -m 0755 "$HERE/uninstall.sh" "$APP_ROOT/uninstall.sh"
ln -sfn "$APP_HOME/bin/bpfw" "$BIN_DIR/bpfw"
ln -sfn "$APP_ROOT/uninstall.sh" "$BIN_DIR/bpfw-uninstall"

echo "BPFW installed: $BIN_DIR/bpfw"
echo "BPFW uninstaller: $BIN_DIR/bpfw-uninstall"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Note: add $BIN_DIR to PATH if your shell does not already include it." ;;
esac
