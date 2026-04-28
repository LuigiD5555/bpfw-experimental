from __future__ import annotations

from pathlib import Path

from bpfw.integrity.manifest import load_manifest


class AuthorityRestorer:
    """Best-effort authority restorer from current manifest baseline."""

    def restore(self, project_root: Path, relative_path: str) -> bool:
        del project_root, relative_path
        # V1 keeps deterministic behavior and does not attempt content reconstruction
        # from hashes only. It reports block and relocks.
        return False

    def first_drifted_authority_path(self, project_root: Path) -> str:
        from bpfw.authority.resources import AuthorityResourceRegistry
        from bpfw.integrity.hash_provider import compute_sha256

        manifest_payload = load_manifest(project_root=project_root)
        files = manifest_payload.get("files")
        if not isinstance(files, list):
            return ""

        registry = AuthorityResourceRegistry()
        for entry in files:
            if not isinstance(entry, dict):
                continue
            relative_path = str(entry.get("path", "")).strip()
            expected_hash = str(entry.get("sha256", "")).strip()
            if not relative_path or not expected_hash:
                continue
            absolute_path = project_root / relative_path
            if not absolute_path.exists() or not absolute_path.is_file():
                continue
            if not registry.is_authority_path(relative_path):
                continue
            if compute_sha256(absolute_path) != expected_hash:
                return relative_path
        return ""
