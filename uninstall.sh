#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${BPFW_HOME:-$HOME/.local/share/bpfw}"
BIN_DIR="${BPFW_BIN_DIR:-$HOME/.local/bin}"
TARGET_VERSION=""
REMOVE_ALL=0
PURGE_USER_DATA=0

usage() {
  printf '%s\n' \
    "Usage: bpfw-uninstall [--version VERSION | --all] [--purge-user-data]" \
    "" \
    "  --version VERSION   Remove one managed BPFW version." \
    "  --all               Remove all managed versions and private runtimes." \
    "  --purge-user-data   Also remove global BPFW cache/config (never project .bpfw)." \
    "  --help              Show this help."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      [[ $# -ge 2 ]] || { echo "Missing value for --version" >&2; exit 2; }
      TARGET_VERSION="$2"; shift 2 ;;
    --all) REMOVE_ALL=1; shift ;;
    --purge-user-data) PURGE_USER_DATA=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$REMOVE_ALL" -eq 1 && -n "$TARGET_VERSION" ]]; then
  echo "Choose either --all or --version, not both." >&2
  exit 2
fi

if [[ "$REMOVE_ALL" -eq 0 && -z "$TARGET_VERSION" ]]; then
  REMOVE_ALL=1
fi

case "$APP_ROOT" in
  ""|/|"$HOME"|"$HOME/.local"|"$HOME/.local/share")
    echo "Refusing unsafe BPFW_HOME target: $APP_ROOT" >&2
    exit 1 ;;
esac

remove_link_if_managed() {
  local link_path="$1"
  [[ -L "$link_path" ]] || return 0
  local link_target
  link_target="$(readlink "$link_path")"
  case "$link_target" in
    "$APP_ROOT"/*) rm -f "$link_path" ;;
  esac
}

if [[ "$REMOVE_ALL" -eq 1 ]]; then
  remove_link_if_managed "$BIN_DIR/bpfw"
  remove_link_if_managed "$BIN_DIR/bpfw-uninstall"
  [[ -d "$APP_ROOT/versions" ]] && rm -rf -- "$APP_ROOT/versions"
  [[ -d "$APP_ROOT/runtimes" ]] && rm -rf -- "$APP_ROOT/runtimes"
  rm -f -- "$APP_ROOT/uninstall.sh"
  rmdir "$APP_ROOT" 2>/dev/null || true
  echo "Removed all managed BPFW versions and private runtimes."
else
  case "$TARGET_VERSION" in
    ""|*/*|.|..) echo "Invalid version: $TARGET_VERSION" >&2; exit 2 ;;
  esac
  version_path="$APP_ROOT/versions/$TARGET_VERSION"
  [[ -d "$version_path" ]] && rm -rf -- "$version_path"
  if [[ -L "$BIN_DIR/bpfw" ]]; then
    current_target="$(readlink "$BIN_DIR/bpfw")"
    case "$current_target" in "$version_path"/*) rm -f "$BIN_DIR/bpfw" ;; esac
  fi
  echo "Removed managed BPFW version $TARGET_VERSION."
fi

if [[ "$PURGE_USER_DATA" -eq 1 ]]; then
  cache_base="${XDG_CACHE_HOME:-$HOME/.cache}"
  config_base="${XDG_CONFIG_HOME:-$HOME/.config}"
  [[ -d "$cache_base/bpfw" ]] && rm -rf -- "$cache_base/bpfw"
  [[ -d "$config_base/bpfw" ]] && rm -rf -- "$config_base/bpfw"
  echo "Removed global BPFW cache and configuration."
fi

