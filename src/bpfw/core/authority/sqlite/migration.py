"""Backend selection and lossless, opt-in one-way authority migration."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from .store import AuthorityConflict, AuthorityIntegrityError, SqliteAuthorityStore, SCHEMA_VERSION, digest


def active_backend(project_root: Path) -> str:
    manifest = Path(project_root) / ".bpfw" / "manifest.json"
    if not manifest.exists():
        return "yaml"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        backend = payload["authority_backend"]
        if backend not in {"yaml", "sqlite"}:
            raise ValueError("unknown authority backend")
        if backend == "sqlite" and payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported SQLite authority schema")
        return backend
    except (OSError, KeyError, ValueError, TypeError) as error:
        raise AuthorityIntegrityError(f"Invalid authority manifest: {error}") from error


def refuse_legacy_write(project_root: Path) -> None:
    if active_backend(project_root) == "sqlite":
        raise AuthorityConflict("SQLite authority is active: legacy YAML writes are forbidden. Use bpfw batch import or SQLite Engine.")


def _legacy_raw(project_root: Path) -> dict[str, Any]:
    from bpfw.core.catalog.domain.repository import BlueprintRepository
    repo = BlueprintRepository(project_root)
    if active_backend(project_root) != "yaml":
        raise AuthorityConflict("Project already uses SQLite authority")
    if not repo.blueprint_path.is_file():
        raise FileNotFoundError(f"Legacy blueprint not found: {repo.blueprint_path}")
    data = repo.load().raw_data
    if not isinstance(data, dict) or not isinstance(data.get("blocks", []), list):
        raise AuthorityIntegrityError("Legacy authority blocks must be a list")
    return data


def migration_preview(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    data = _legacy_raw(root)
    ids = [b.get("id") for b in data.get("blocks", []) if isinstance(b, dict) and b.get("id")]
    uids = [b.get("uid") for b in data.get("blocks", []) if isinstance(b, dict) and b.get("uid")]
    from collections import Counter
    duplicates = sorted(x for x, n in Counter(ids).items() if n > 1)
    duplicate_uids = sorted(x for x, n in Counter(uids).items() if n > 1)
    return {"from": "yaml", "to": "sqlite", "source_digest": digest(data),
            "blocks": len(data["blocks"]), "duplicate_ids": duplicates,
            "duplicate_uids": duplicate_uids,
            "can_activate": not duplicates and not duplicate_uids,
            "legacy_files_preserved": True,
            "note": "Migration is opt-in. Unported legacy writers are blocked after activation."}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    fd_path = path.with_name(path.name + ".tmp." + uuid.uuid4().hex)
    try:
        with fd_path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(fd_path, path)
        # directory fsync makes backend activation robust to power loss.
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        fd = os.open(path.parent, flags)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        fd_path.unlink(missing_ok=True)


def migrate_legacy(project_root: Path, *, apply: bool = False) -> dict[str, Any]:
    root = Path(project_root).resolve()
    report = migration_preview(root)
    if not apply:
        return report
    if not report["can_activate"]:
        raise AuthorityConflict("Duplicate ID/UID in legacy authority; resolve before migration")
    final = root / ".bpfw" / "authority.sqlite"
    manifest = root / ".bpfw" / "manifest.json"
    if final.exists() or manifest.exists():
        raise AuthorityConflict("Authority DB or manifest already exists; refuse overwrite")
    data = _legacy_raw(root)
    if digest(data) != report["source_digest"]:
        raise AuthorityConflict("Legacy authority changed between preview and migration")
    staging = final.with_name("authority.staging." + uuid.uuid4().hex + ".sqlite")
    store = SqliteAuthorityStore(root, staging)
    try:
        store.initialize()
        origin = {}
        if isinstance(data.get("includes"), list):
            from bpfw.core.authority import AuthorityRepository
            origin = {bid: str(source) for bid, source in AuthorityRepository(root).load().block_origins.items()}
        store.import_document(data, origins=origin)
        restored = store.load_document()
        check = store.doctor()
        if restored != data or not check["ok"]:
            raise AuthorityIntegrityError("SQLite equivalence/integrity check failed before activation")
        # Re-read legacy authority: don't activate stale snapshot.
        if digest(_legacy_raw(root)) != report["source_digest"]:
            raise AuthorityConflict("Legacy authority changed during migration")
        os.replace(staging, final)
        _atomic_json(manifest, {"authority_backend": "sqlite", "schema_version": SCHEMA_VERSION,
                                "source_digest": report["source_digest"], "project_id": uuid.uuid4().hex})
    finally:
        staging.unlink(missing_ok=True)
    return {**report, "activated": True, "database": str(final), "manifest": str(manifest),
            "revision": 1}
