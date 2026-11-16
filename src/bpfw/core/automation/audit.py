"""Compact, machine-readable Blueprint automation audit."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bpfw.core.artifacts import ArtifactResolver, block_artifacts
from bpfw.core.artifacts.flow import discover_flow_artifact_candidates
from bpfw.core.automation.profiles import redundant_artifact_fields


def audit_blueprint(project_root: Path) -> dict[str, Any]:
    from bpfw.core.catalog.loader import BlueprintLoader
    load = BlueprintLoader(project_root=project_root).load()
    data = load.data if isinstance(load.data, dict) else {}
    blocks = data.get("blocks", []) if isinstance(data.get("blocks"), list) else []
    resolver = ArtifactResolver(project_root)
    totals = {"blocks": 0, "artifacts": 0, "invariants": 0, "connections": 0}
    missing_uids: list[dict[str, Any]] = []
    missing_files: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    redundant: list[dict[str, Any]] = []
    unknown_profiles: list[dict[str, Any]] = []
    profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
    bound_code: set[tuple[str, str]] = set()
    profile_signatures: Counter[tuple[Any, ...]] = Counter()
    examples: dict[tuple[Any, ...], list[str]] = defaultdict(list)

    for block in blocks:
        if not isinstance(block, dict): continue
        totals["blocks"] += 1; block_id = str(block.get("id") or "")
        if not block.get("uid"): missing_uids.append({"scope": "block", "block": block_id})
        for key, scope in (("invariants", "invariant"), ("connections", "connection")):
            vals = block.get(key) if isinstance(block.get(key), list) else []
            totals["invariants" if key == "invariants" else "connections"] += len([v for v in vals if isinstance(v, dict)])
            for v in vals:
                if isinstance(v, dict) and not v.get("uid"): missing_uids.append({"scope": scope, "block": block_id, "entity": v.get("id") or v.get("target")})
        explicit_arts = block.get("artifacts") if isinstance(block.get("artifacts"), list) else []
        for art in explicit_arts:
            if not isinstance(art, dict): continue
            profile_name = art.get("profile")
            if isinstance(profile_name, str) and profile_name not in profiles:
                unknown_profiles.append({"block": block_id, "artifact": art.get("id") or art.get("path"), "profile": profile_name})
            for field in redundant_artifact_fields(data, art): redundant.append({"block": block_id, "artifact": art.get("id") or art.get("path"), "field": field})
            sig = tuple(art.get(k) for k in ("type", "language", "role", "required"))
            if sum(v is not None for v in sig) >= 2 and not art.get("profile"):
                profile_signatures[sig] += 1
                if len(examples[sig]) < 5: examples[sig].append(f"{block_id}:{art.get('id') or art.get('path')}")
        for art in block_artifacts(block):
            totals["artifacts"] += 1
            if art.get("id") != "legacy_code" and not art.get("uid"): missing_uids.append({"scope": "artifact", "block": block_id, "entity": art.get("id") or art.get("path")})
            path = str(art.get("path") or "")
            if path and not (project_root / path).is_file(): missing_files.append({"block": block_id, "artifact": art.get("id") or path, "path": path}); continue
            resolved = resolver.resolve(art)
            if path and art.get("symbol") and not resolved.resolved: unresolved.append({"block": block_id, "artifact": art.get("id") or path, "path": path, "symbol": art.get("symbol"), "message": resolved.message})
            if str(art.get("type") or "code") == "code": bound_code.add((path.replace("\\", "/"), str(art.get("symbol") or "")))

    unbound_code: list[dict[str, Any]] = []
    try:
        from bpfw.core.catalog.verify import scan_project_from_blueprint
        scan = scan_project_from_blueprint(project_root, data, domain_document=load.domain_document)
        for unit in scan.discovered_units:
            key = (str(unit.path).replace("\\", "/"), str(unit.symbol))
            if key not in bound_code:
                unbound_code.append({"path": str(unit.path).replace("\\", "/"), "symbol": unit.symbol, "kind": unit.symbol_type, "language": unit.language})
    except Exception:
        pass
    flow = discover_flow_artifact_candidates(project_root, data)
    possible_profiles = []
    for sig, count in profile_signatures.most_common():
        if count < 3: continue
        fields = {k: v for k, v in zip(("type", "language", "role", "required"), sig) if v is not None}
        possible_profiles.append({"count": count, "fields": fields, "examples": examples[sig]})

    return {
        "schema": "bpfw.automation.audit/v1",
        "authority_state": load.state,
        "totals": totals,
        "issues": {
            "missing_uids": missing_uids,
            "missing_files": missing_files,
            "unresolved_symbols": unresolved,
            "redundant_fields": redundant,
            "unknown_profiles": unknown_profiles,
            "unbound_code_units": unbound_code,
            "unbound_flow_artifacts": flow,
        },
        "possible_profiles": possible_profiles,
        "summary": {
            "missing_uids": len(missing_uids), "missing_files": len(missing_files), "unresolved_symbols": len(unresolved),
            "redundant_fields": len(redundant), "unknown_profiles": len(unknown_profiles), "unbound_code_units": len(unbound_code), "unbound_flow_artifacts": len(flow), "possible_profiles": len(possible_profiles),
        },
    }
