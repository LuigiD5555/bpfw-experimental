"""Single-authority SQLite compatibility adapters for the historical BPFW APIs.

No virtual YAML is written to disk. Legacy consumers get in-memory document
objects; mutations are compiled and persisted through one SQLite transaction.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .store import AuthorityConflict, SqliteAuthorityStore


def _origins(store: SqliteAuthorityStore, data: dict[str, Any]) -> dict[str, str]:
    includes = data.get("includes") or []
    default = str(includes[0]) if includes else ".bpfw/blocks/sqlite.yaml"
    with store.connect() as conn:
        mapped = {r["entity_uid"]: r["source"] for r in conn.execute(
            "SELECT entity_uid, source FROM import_provenance WHERE entity_type='block'")}
        rows = conn.execute("SELECT uid, external_id FROM blocks ORDER BY display_order").fetchall()
    return {r["external_id"]: mapped.get(r["uid"]) or default
            for r in rows if r["external_id"]}


def sqlite_authority_document(project_root: Path):
    """Reconstruct the historical AuthorityDocument API without reading old YAML."""
    from bpfw.core.authority.document import AuthorityDocument
    from bpfw.core.authority.index import AuthorityIndex
    from bpfw.core.authority.shard import AuthorityShard

    store = SqliteAuthorityStore(project_root)
    data = store.load_document()
    paths = data.get("includes") if isinstance(data.get("includes"), list) else []
    paths = [str(p) for p in paths if p]
    if not paths:
        paths = [".bpfw/blocks/sqlite.yaml"]
    index_data = {k: deepcopy(v) for k, v in data.items() if k != "blocks"}
    if not isinstance(index_data.get("authority"), dict) or index_data["authority"].get("layout") != "sharded":
        index_data["authority"] = {"layout": "sharded"}
    index_data["includes"] = paths
    index = AuthorityIndex(project_root / ".bpfw/blueprint.yaml", index_data)
    origin_names = _origins(store, data)
    buckets: dict[Path, list[dict[str, Any]]] = {Path(p): [] for p in paths}
    block_origins: dict[str, Path] = {}
    for block in data.get("blocks", []):
        bid = block.get("id")
        name = origin_names.get(bid) or paths[0]
        path = Path(name)
        buckets.setdefault(path, []).append(block)
        if bid:
            block_origins[bid] = path
    shards = {path: AuthorityShard(path, blocks) for path, blocks in buckets.items()}
    document = AuthorityDocument(index, data, block_origins, shards)
    document.sqlite_revision = store.revision()
    return document


def save_sqlite_authority_document(project_root: Path, document: Any):
    """Persist a legacy in-memory editing session with revision CAS."""
    from bpfw.core.authority.persistence import AuthorityPersistenceResult
    store = SqliteAuthorityStore(project_root)
    rev = getattr(document, "sqlite_revision", None)
    origins = {bid: str(origin) for bid, origin in document.block_origins.items()}
    store.replace_document(document.blueprint_data, actor="blueprint-engine",
                           reason="AuthorityRepository.save", expected_revision=rev,
                           origins=origins)
    document.sqlite_revision = store.revision()
    return AuthorityPersistenceResult(warnings=["Authority persisted transactionally in SQLite"])


def execute_sqlite_plan(project_root: Path, plan: Any, *, apply: bool) -> int:
    """Interpret every known BlueprintEngine operation in memory, atomically.

    Validation is independent of legacy YAML file existence. Malformed plans
    fail before the transactional persist; previews have zero write effects.
    """
    from bpfw.core.authority.patch.actions import PatchOperationKind as K, _validate_shard_path
    store = SqliteAuthorityStore(project_root)
    base_revision = store.revision()
    data = store.load_document()
    origin = _origins(store, data)
    blocks = data["blocks"]
    includes = data.get("includes")
    if not isinstance(includes, list):
        includes = []
    kind_count = 0

    def find(bid: str) -> dict:
        matches = [b for b in blocks if b.get("id") == bid or b.get("uid") == bid]
        if len(matches) != 1:
            raise AuthorityConflict(f"Expected exactly one block for {bid!r}; found {len(matches)}")
        return matches[0]

    def validate_path(path: Path) -> str:
        _validate_shard_path(Path(path))
        return str(path)

    for op in plan.operations:
        kind = op.kind
        if kind in {K.CREATE_SHARD_FILE, K.DELETE_SHARD_FILE, K.MOVE_SHARD_FILE, K.RENAME_SHARD_FILE}:
            if kind == K.CREATE_SHARD_FILE:
                dst = validate_path(op.shard_path)
                if dst in includes: raise AuthorityConflict(f"Shard already exists: {dst}")
                includes.append(dst)
                for block in op.initial_blocks:
                    if any(b.get("id") == block.get("id") for b in blocks):
                        raise AuthorityConflict(f"Duplicate ID: {block.get('id')}")
                    if not isinstance(block.get("id"), str) or not block["id"]:
                        raise AuthorityConflict("New block must have nonempty id")
                    blocks.append(deepcopy(block)); origin[block["id"]] = dst
            elif kind == K.DELETE_SHARD_FILE:
                src = validate_path(op.shard_path)
                if src not in includes: raise AuthorityConflict(f"Missing shard: {src}")
                members = [b for b in blocks if origin.get(b.get("id")) == src]
                if members and op.require_empty:
                    raise AuthorityConflict(f"Cannot remove nonempty logical shard: {src}")
                blocks[:] = [b for b in blocks if b not in members]
                for b in members: origin.pop(b.get("id"), None)
                includes.remove(src)
            else:
                src, dst = validate_path(op.source_shard_path), validate_path(op.target_shard_path)
                if src not in includes or dst in includes:
                    raise AuthorityConflict("Cannot move or rename logical shard: invalid source/target")
                includes[includes.index(src)] = dst
                origin = {bid: dst if loc == src else loc for bid, loc in origin.items()}
        elif kind == K.CREATE_BLOCK:
            dst = validate_path(op.target_shard_path)
            if dst not in includes:
                if not op.create_target_if_missing:
                    raise AuthorityConflict(f"Logical shard not found: {dst}")
                includes.append(dst)
            new = deepcopy(op.block_data)
            if not isinstance(new.get("id"), str) or not new["id"]:
                raise AuthorityConflict("Block requires nonempty id")
            if any(b.get("id") == new["id"] or (new.get("uid") and b.get("uid") == new["uid"]) for b in blocks):
                raise AuthorityConflict(f"Duplicate block: {new['id']}")
            blocks.append(new); origin[new["id"]] = dst
        elif kind in {K.ADD_IGNORE_RULE, K.REMOVE_IGNORE_RULE, K.ADD_COVERED_CODE, K.REMOVE_COVERED_CODE}:
            key = "ignored_code" if kind in {K.ADD_IGNORE_RULE, K.REMOVE_IGNORE_RULE} else "covered_code"
            section = data.setdefault("authority", {})
            if not isinstance(section, dict): raise AuthorityConflict("Invalid authority section")
            rules = section.setdefault(key, [])
            if not isinstance(rules, list): raise AuthorityConflict(f"Invalid authority.{key}")
            rule = deepcopy(op.rule_data)
            if not isinstance(rule, dict) or not rule: raise AuthorityConflict("Empty rule")
            if kind in {K.ADD_IGNORE_RULE, K.ADD_COVERED_CODE}:
                if rule not in rules: rules.append(rule)
            else:
                if rule not in rules: raise AuthorityConflict(f"Rule not present in authority.{key}")
                rules.remove(rule)
        else:
            block = find(op.block_id)
            old_id = block.get("id")
            if hasattr(op, "source_shard_path"):
                src = validate_path(op.source_shard_path)
                if src != origin.get(old_id):
                    raise AuthorityConflict(f"Block {old_id} not in expected logical shard {src}")
            if kind == K.MOVE_BLOCK:
                dst = validate_path(op.target_shard_path)
                if dst not in includes:
                    if not op.create_target_if_missing:
                        raise AuthorityConflict(f"Missing target shard: {dst}")
                    includes.append(dst)
                origin[old_id] = dst
            elif kind == K.DELETE_BLOCK:
                blocks.remove(block); origin.pop(old_id, None)
            elif kind == K.UPDATE_BLOCK_METADATA:
                invalid = set(op.metadata_changes) - op.ALLOWED_FIELDS
                if invalid: raise AuthorityConflict(f"Forbidden metadata fields: {sorted(invalid)}")
                if not op.metadata_changes: raise AuthorityConflict("Empty metadata changes")
                for key, value in op.metadata_changes.items(): block[key] = deepcopy(value)
            elif kind in {K.UPDATE_BLOCK_LOCATION, K.UPDATE_BLOCK_SYMBOL, K.UPDATE_BLOCK_CODE_REFERENCE}:
                code = block.setdefault("code", {})
                if not isinstance(code, dict): raise AuthorityConflict(f"Invalid code object: {old_id}")
                if kind in {K.UPDATE_BLOCK_LOCATION, K.UPDATE_BLOCK_CODE_REFERENCE}:
                    if not op.new_path: raise AuthorityConflict("Empty new_path")
                    code["path"] = op.new_path
                if kind in {K.UPDATE_BLOCK_SYMBOL, K.UPDATE_BLOCK_CODE_REFERENCE}:
                    if not op.new_symbol: raise AuthorityConflict("Empty new_symbol")
                    code["symbol"] = op.new_symbol
                    if op.new_name is not None: block["name"] = op.new_name
                if kind == K.UPDATE_BLOCK_CODE_REFERENCE and op.new_kind is not None:
                    code["kind"] = op.new_kind
            else:
                raise AuthorityConflict(f"Unported operation: {kind}")
        kind_count += 1

    if data.get("includes") != includes and ("includes" in data or includes):
        data["includes"] = includes
    if apply:
        store.replace_document(data, actor="blueprint-engine", reason="BlueprintChangeRequest",
                               expected_revision=base_revision, origins=origin)
    return kind_count
