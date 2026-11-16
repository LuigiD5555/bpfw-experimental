"""Deterministic batch planning/apply engine for Blueprint authority."""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from bpfw.core.automation.profiles import infer_artifact_metadata, redundant_artifact_fields, resolve_artifact_profile, strip_ephemeral


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(data: dict[str, Any]) -> str:
    clean = strip_ephemeral(data)
    encoded = json.dumps(clean, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parse_value(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        lowered = text.strip().lower()
        if lowered == "true": return True
        if lowered == "false": return False
        if lowered in {"null", "none"}: return None
        return text


def _get_path(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in [p for p in path.split(".") if p]:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _has_path(obj: dict[str, Any], path: str) -> bool:
    cur: Any = obj
    parts = [p for p in path.split(".") if p]
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def _set_path(obj: dict[str, Any], path: str, value: Any, only_missing: bool = False) -> bool:
    parts = [p for p in path.split(".") if p]
    if not parts: return False
    cur: dict[str, Any] = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            if only_missing and part in cur: return False
            nxt = {}; cur[part] = nxt
        cur = nxt
    leaf = parts[-1]
    if only_missing and leaf in cur: return False
    if leaf in cur and cur[leaf] == value: return False
    cur[leaf] = deepcopy(value)
    return True


def _remove_path(obj: dict[str, Any], path: str) -> bool:
    parts = [p for p in path.split(".") if p]
    if not parts: return False
    cur: Any = obj
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur: return False
        cur = cur[part]
    if isinstance(cur, dict) and parts[-1] in cur:
        del cur[parts[-1]]; return True
    return False


def _match(entity: dict[str, Any], where: str | None) -> bool:
    if not where: return True
    if "!=" in where:
        field, expected = where.split("!=", 1); return str(_get_path(entity, field.strip())) != expected.strip()
    if "=" not in where: return False
    field, expected = where.split("=", 1)
    value = _get_path(entity, field.strip())
    return str(value).lower() == expected.strip().lower()


def _entities(data: dict[str, Any], scope: str) -> Iterable[tuple[str, dict[str, Any], str | None]]:
    blocks = data.get("blocks") if isinstance(data.get("blocks"), list) else []
    if scope == "block":
        for block in blocks:
            if isinstance(block, dict): yield str(block.get("id") or block.get("uid") or "block"), block, None
        return
    child_key = {"artifact": "artifacts", "invariant": "invariants", "connection": "connections"}.get(scope)
    if child_key:
        for block in blocks:
            if not isinstance(block, dict): continue
            parent = str(block.get("id") or block.get("uid") or "block")
            values = block.get(child_key)
            if not isinstance(values, list): continue
            for idx, item in enumerate(values):
                if isinstance(item, dict):
                    name = str(item.get("id") or item.get("uid") or item.get("symbol") or item.get("target") or f"{scope}-{idx+1}")
                    yield name, item, parent


@dataclass(slots=True)
class AuthorityHandle:
    data: dict[str, Any]
    authority_document: Any | None
    sharded: bool
    sqlite_revision: int | None = None


class AutomationEngine:
    """Plan and apply deterministic changes against Blueprint authority."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.plan_root = self.project_root / ".bpfw" / "plans"

    def load(self) -> AuthorityHandle:
        from bpfw.core.authority.sqlite.migration import active_backend
        if active_backend(self.project_root) == "sqlite":
            from bpfw.core.authority.sqlite.store import SqliteAuthorityStore
            store = SqliteAuthorityStore(self.project_root)
            return AuthorityHandle(deepcopy(strip_ephemeral(store.load_document())), None, False, store.revision())
        from bpfw.core.catalog.paths import resolve_blueprint_path
        from bpfw.core.yaml_io import load_yaml_text
        path = resolve_blueprint_path(self.project_root)
        if not path.exists(): raise FileNotFoundError(f"Blueprint not found: {path}")
        root = load_yaml_text(path.read_text(encoding="utf-8")) or {}
        if not isinstance(root, dict): raise ValueError("Blueprint root must be a mapping")
        authority = root.get("authority")
        if isinstance(authority, dict) and authority.get("layout") == "sharded":
            from bpfw.core.authority import AuthorityRepository
            doc = AuthorityRepository(self.project_root).load()
            return AuthorityHandle(deepcopy(strip_ephemeral(doc.blueprint_data)), doc, True)
        return AuthorityHandle(deepcopy(strip_ephemeral(root)), None, False)

    def save(self, handle: AuthorityHandle, data: dict[str, Any], trigger: str = "bpfw automation") -> None:
        clean = strip_ephemeral(data)
        if handle.sqlite_revision is not None:
            from bpfw.core.blueprint_engine.engine import BlueprintEngine
            BlueprintEngine(self.project_root).replace_authority_document(
                clean, reason=trigger, expected_revision=handle.sqlite_revision)
            return
        from bpfw.core.catalog.access_control import authorize_blueprint_writes_for_tool, authorize_temporary_blueprint_unlock_for_tool
        if handle.sharded and handle.authority_document is not None:
            from bpfw.core.authority import AuthorityRepository
            handle.authority_document.blueprint_data = clean
            handle.authority_document.replace_blocks(clean.get("blocks", []))
            with authorize_blueprint_writes_for_tool("automation"):
                with authorize_temporary_blueprint_unlock_for_tool("automation"):
                    AuthorityRepository(self.project_root).save(handle.authority_document)
            return
        from bpfw.core.catalog.writer import write_blueprint
        from bpfw.core.catalog.paths import resolve_blueprint_path
        with authorize_blueprint_writes_for_tool("automation"):
            with authorize_temporary_blueprint_unlock_for_tool("automation"):
                write_blueprint(resolve_blueprint_path(self.project_root), clean)

    def mutate(self, data: dict[str, Any], operation: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        target = deepcopy(strip_ephemeral(data)); changes: list[dict[str, Any]] = []
        if operation == "generate-uids":
            before = deepcopy(target)
            self._generate_uids(target, seed=str(args.get("seed") or "bpfw-automation"))
            self._diff_uids(before, target, changes)
            return target, changes
        if operation == "normalize":
            self._normalize(target, changes)
            return target, changes
        if operation == "compact":
            self._compact(target, changes, min_occurrences=int(args.get("min_occurrences", 3)))
            return target, changes
        if operation == "move-path":
            old = str(args.get("from") or "").replace("\\", "/").rstrip("/")
            new = str(args.get("to") or "").replace("\\", "/").rstrip("/")
            for block in target.get("blocks", []) if isinstance(target.get("blocks"), list) else []:
                if not isinstance(block, dict): continue
                for entity in [block.get("code")] + (block.get("artifacts", []) if isinstance(block.get("artifacts"), list) else []):
                    if not isinstance(entity, dict) or not isinstance(entity.get("path"), str): continue
                    current = entity["path"].replace("\\", "/")
                    if current == old or current.startswith(old + "/"):
                        updated = new + current[len(old):]
                        entity["path"] = updated
                        changes.append({"entity": str(entity.get("id") or entity.get("symbol") or current), "parent": block.get("id"), "field": "path", "before": current, "after": updated})
            return target, changes
        scope = str(args.get("scope") or "artifact")
        where = args.get("where")
        field = str(args.get("field") or "")
        for name, entity, parent in _entities(target, scope):
            match_entity = resolve_artifact_profile(target, entity) if scope == "artifact" else entity
            if not _match(match_entity, str(where) if where else None): continue
            before = deepcopy(_get_path(entity, field)) if field else None
            changed = False
            if operation == "set": changed = _set_path(entity, field, _parse_value(str(args.get("value", ""))))
            elif operation == "default": changed = _set_path(entity, field, _parse_value(str(args.get("value", ""))), only_missing=True)
            elif operation == "remove": changed = _remove_path(entity, field)
            elif operation == "rename-field":
                new_field = str(args.get("to") or "")
                if _has_path(entity, field):
                    value = deepcopy(_get_path(entity, field)); _remove_path(entity, field); _set_path(entity, new_field, value); changed = True
            elif operation == "replace-value":
                expected = _parse_value(str(args.get("from", ""))); replacement = _parse_value(str(args.get("to", "")))
                if _has_path(entity, field) and _get_path(entity, field) == expected:
                    _set_path(entity, field, replacement); changed = True
            if changed:
                after_field = str(args.get("to")) if operation == "rename-field" else field
                changes.append({"entity": name, "parent": parent, "scope": scope, "field": after_field, "before": before, "after": deepcopy(_get_path(entity, after_field))})
        return target, changes

    def create_plan(self, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        plan_id = f"plan_{uuid.uuid4().hex[:16]}"
        args = deepcopy(args)
        if operation == "generate-uids":
            args.setdefault("seed", plan_id)
        handle = self.load(); after, changes = self.mutate(handle.data, operation, args)
        plan = {"schema": "bpfw.automation.plan/v1", "plan_id": plan_id, "created_at": _now(), "operation": operation, "args": args, "before_digest": _digest(handle.data), "after_digest": _digest(after), "change_count": len(changes), "changes": changes[:500]}
        self.plan_root.mkdir(parents=True, exist_ok=True)
        (self.plan_root / f"{plan_id}.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        return plan

    def apply_plan(self, plan_id: str) -> dict[str, Any]:
        path = self.plan_root / f"{plan_id}.json"
        if not path.is_file(): raise FileNotFoundError(f"Plan not found: {plan_id}")
        plan = json.loads(path.read_text(encoding="utf-8")); handle = self.load()
        if _digest(handle.data) != plan.get("before_digest"):
            raise RuntimeError("Plan is stale: Blueprint authority changed after the plan was created.")
        after, changes = self.mutate(handle.data, str(plan["operation"]), dict(plan.get("args") or {}))
        if _digest(after) != plan.get("after_digest"):
            raise RuntimeError("Plan is not reproducible against current automation rules.")
        if changes:
            self.save(handle, after, trigger=f"bpfw automation {plan_id}")
        return {**plan, "applied": True, "applied_at": _now(), "change_count": len(changes)}

    @staticmethod
    def _generate_uids(data: dict[str, Any], seed: str) -> None:
        prefixes = {"block": "bp", "artifact": "art", "invariant": "inv", "connection": "rel"}
        def make(kind: str, key: str) -> str:
            return f"{prefixes[kind]}_{uuid.uuid5(uuid.NAMESPACE_URL, seed + ':' + kind + ':' + key).hex}"
        blocks = data.get("blocks", []) if isinstance(data.get("blocks"), list) else []
        for bi, block in enumerate(blocks):
            if not isinstance(block, dict): continue
            block_key = str(block.get("id") or f"block-{bi}")
            if not block.get("uid"): block["uid"] = make("block", block_key)
            code = block.get("code")
            if isinstance(code, dict) and code.get("path") and not code.get("uid"):
                code["uid"] = make("artifact", block_key + ':code:' + str(code.get("symbol") or code.get("path")))
            for child_key, kind in (("artifacts", "artifact"), ("invariants", "invariant"), ("connections", "connection")):
                vals = block.get(child_key) if isinstance(block.get(child_key), list) else []
                for ci, item in enumerate(vals):
                    if not isinstance(item, dict) or item.get("uid"): continue
                    identity = item.get("id") or item.get("symbol") or item.get("target") or item.get("path") or str(ci)
                    item["uid"] = make(kind, block_key + ':' + child_key + ':' + str(identity))

    @staticmethod
    def _diff_uids(before: dict[str, Any], after: dict[str, Any], changes: list[dict[str, Any]]) -> None:
        bblocks = before.get("blocks", []) if isinstance(before.get("blocks"), list) else []
        ablocks = after.get("blocks", []) if isinstance(after.get("blocks"), list) else []
        for b, a in zip(bblocks, ablocks):
            if not isinstance(b, dict) or not isinstance(a, dict): continue
            if not b.get("uid") and a.get("uid"): changes.append({"entity": a.get("id"), "scope": "block", "field": "uid", "after": a.get("uid")})
            for key, scope in (("artifacts", "artifact"), ("invariants", "invariant"), ("connections", "connection")):
                bv = b.get(key, []) if isinstance(b.get(key), list) else []; av = a.get(key, []) if isinstance(a.get(key), list) else []
                for bi, ai in zip(bv, av):
                    if isinstance(bi, dict) and isinstance(ai, dict) and not bi.get("uid") and ai.get("uid"):
                        changes.append({"entity": ai.get("id") or ai.get("symbol") or ai.get("target"), "parent": a.get("id"), "scope": scope, "field": "uid", "after": ai.get("uid")})

    @staticmethod
    def _normalize(data: dict[str, Any], changes: list[dict[str, Any]]) -> None:
        blocks = data.get("blocks", []) if isinstance(data.get("blocks"), list) else []
        for block in blocks:
            if not isinstance(block, dict): continue
            code = block.get("code")
            if isinstance(code, dict) and isinstance(code.get("path"), str):
                before_path = code["path"]; new_path = before_path.replace("\\", "/")
                if new_path != before_path:
                    code["path"] = new_path
                    changes.append({"entity": block.get("id"), "field": "code.path", "before": before_path, "after": new_path})
            arts = block.get("artifacts") if isinstance(block.get("artifacts"), list) else []
            for art in arts:
                if not isinstance(art, dict): continue
                before = deepcopy(art)
                name = art.get("id") or art.get("symbol") or art.get("path")
                if isinstance(art.get("path"), str): art["path"] = art["path"].replace("\\", "/")
                for key, value in infer_artifact_metadata(art).items():
                    if key not in art: art[key] = value
                for key in redundant_artifact_fields(data, art): art.pop(key, None)
                if before == art: continue
                all_keys = sorted(set(before) | set(art))
                for key in all_keys:
                    old, new = before.get(key), art.get(key)
                    if old != new:
                        changes.append({"entity": name, "parent": block.get("id"), "scope": "artifact", "field": key, "before": old, "after": new if key in art else "<inherited/removed>"})

    @staticmethod
    def _compact(data: dict[str, Any], changes: list[dict[str, Any]], min_occurrences: int) -> None:
        # Deterministic compaction only creates profiles from exact repeated safe metadata tuples.
        groups: dict[tuple[Any, ...], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        keys = ("type", "language", "role", "required")
        for block in data.get("blocks", []) if isinstance(data.get("blocks"), list) else []:
            if not isinstance(block, dict): continue
            for art in block.get("artifacts", []) if isinstance(block.get("artifacts"), list) else []:
                if not isinstance(art, dict) or art.get("profile"): continue
                signature = tuple(art.get(k) for k in keys)
                if sum(v is not None for v in signature) < 2: continue
                groups.setdefault(signature, []).append((block, art))
        profiles = data.setdefault("profiles", {})
        if not isinstance(profiles, dict): return
        counter = 1
        for signature, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
            if len(items) < min_occurrences: continue
            profile_data = {k: v for k, v in zip(keys, signature) if v is not None}
            base_name = "_".join(str(profile_data.get(k, "")).lower().replace("-", "_") for k in ("type", "language", "role") if profile_data.get(k)) or f"profile_{counter}"
            name = base_name; suffix = 2
            while name in profiles and profiles[name] != profile_data:
                name = f"{base_name}_{suffix}"; suffix += 1
            if name not in profiles:
                profiles[name] = profile_data; changes.append({"entity": name, "scope": "profile", "field": "profile", "before": None, "after": profile_data})
            for block, art in items:
                art["profile"] = name
                for key, value in profile_data.items():
                    if art.get(key) == value: art.pop(key, None)
                changes.append({"entity": art.get("id") or art.get("symbol") or art.get("path"), "parent": block.get("id"), "scope": "artifact", "field": "profile", "before": None, "after": name})
            counter += 1
