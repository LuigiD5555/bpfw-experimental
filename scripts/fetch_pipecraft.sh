#!/usr/bin/env bash
# Download the PipeCraft runtime from the matching GitHub release into the source tree,
# verify its SHA-256 against the pinned value, and place it where the package expects it.
# Run before `python -m build` so the wheel includes the binary. Idempotent.
set -euo pipefail

REPO="${BPFW_REPO:-LuigiD5555/bpfw-experimental}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
RUNTIME_VERSION="1.6.0-alpha.1"
PLATFORM="linux-x86_64"
RELEASE_TAG="${BPFW_RELEASE_TAG:-v$(python3 -c 'import tomllib,sys; print(tomllib.load(open(sys.argv[1],"rb"))["project"]["version"])' "$ROOT/pyproject.toml")}"
DEST="${BPFW_RUNTIME_DIR:-$ROOT/src/bpfw/_runtime/pipecraft/$RUNTIME_VERSION/$PLATFORM}"
PINNED_SHA256="$(python3 -c 'import tomllib,sys; print(tomllib.load(open(sys.argv[1],"rb"))["runtimes"]["pipecraft"]["sha256"])' "$ROOT/src/bpfw/runtime/manifest.toml")"

if [[ -f "$DEST/pipecraft" ]] && [[ "$(sha256sum "$DEST/pipecraft" | cut -d' ' -f1)" == "$PINNED_SHA256" ]]; then
  echo "PipeCraft already present and verified: $DEST/pipecraft"
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "fetch_pipecraft: the GitHub CLI (gh) is required to download the release asset." >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
gh release download "$RELEASE_TAG" --repo "$REPO" --pattern 'pipecraft' --pattern 'pipecraft.sha256' --dir "$TMP"

ACTUAL="$(sha256sum "$TMP/pipecraft" | cut -d' ' -f1)"
if [[ "$ACTUAL" != "$PINNED_SHA256" ]]; then
  echo "fetch_pipecraft: checksum mismatch. Expected $PINNED_SHA256, got $ACTUAL. Nothing was installed." >&2
  exit 1
fi

mkdir -p "$DEST"
install -m 0755 "$TMP/pipecraft" "$DEST/pipecraft"
cp "$TMP/pipecraft.sha256" "$DEST/pipecraft.sha256"
echo "PipeCraft $RUNTIME_VERSION installed from release $RELEASE_TAG into $DEST"
