"""Blueprint profile/default materialization without inflating authority YAML."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

_LANGUAGE_BY_SUFFIX = {
    ".go": "go", ".py": "python", ".rs": "rust", ".html": "html", ".htm": "html", ".css": "css",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml", ".md": "markdown",
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def artifact_defaults(blueprint: dict[str, Any], artifact_type: str | None) -> dict[str, Any]:
    defaults = blueprint.get("defaults")
    if not isinstance(defaults, dict):
        return {}
    raw = defaults.get("artifacts")
    if not isinstance(raw, dict):
        return {}
    # Common scalar/default fields live directly under defaults.artifacts.
    common = {k: deepcopy(v) for k, v in raw.items() if not isinstance(v, dict)}
    typed = raw.get(str(artifact_type or "code"))
    if isinstance(typed, dict):
        common = _deep_merge(common, typed)
    return common


def block_defaults(blueprint: dict[str, Any]) -> dict[str, Any]:
    defaults = blueprint.get("defaults")
    if not isinstance(defaults, dict):
        return {}
    raw = defaults.get("blocks")
    return deepcopy(raw) if isinstance(raw, dict) else {}


def resolve_artifact_profile(blueprint: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    """Return effective artifact: defaults -> profile -> explicit fields."""
    explicit = deepcopy(artifact)
    profile_name = explicit.get("profile")
    profile: dict[str, Any] = {}
    profiles = blueprint.get("profiles")
    if isinstance(profiles, dict) and isinstance(profile_name, str):
        candidate = profiles.get(profile_name)
        if isinstance(candidate, dict):
            profile = deepcopy(candidate)
    artifact_type = explicit.get("type") or profile.get("type") or "code"
    effective = artifact_defaults(blueprint, str(artifact_type))
    effective = _deep_merge(effective, profile)
    effective = _deep_merge(effective, explicit)
    return effective


def materialize_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied effective blueprint for typed/runtime consumers."""
    result = deepcopy(blueprint)
    blocks = result.get("blocks")
    if not isinstance(blocks, list):
        return result
    bdefaults = block_defaults(blueprint)
    materialized: list[Any] = []
    for block in blocks:
        if not isinstance(block, dict):
            materialized.append(block)
            continue
        effective_block = _deep_merge(bdefaults, block)
        arts = block.get("artifacts")
        if isinstance(arts, list):
            effective_block["artifacts"] = [
                resolve_artifact_profile(blueprint, art) if isinstance(art, dict) else art for art in arts
            ]
        materialized.append(effective_block)
    result["blocks"] = materialized
    return result


def attach_runtime_artifacts(blueprint: dict[str, Any]) -> None:
    """Attach non-persistent effective artifacts to raw blocks for legacy UI callers."""
    blocks = blueprint.get("blocks")
    if not isinstance(blocks, list):
        return
    for block in blocks:
        if not isinstance(block, dict):
            continue
        arts = block.get("artifacts")
        if isinstance(arts, list):
            block["__bpfw_effective_artifacts"] = [
                resolve_artifact_profile(blueprint, art) if isinstance(art, dict) else art for art in arts
            ]


def strip_ephemeral(value: Any) -> Any:
    """Remove in-memory BPFW keys before authority persistence."""
    if isinstance(value, dict):
        return {k: strip_ephemeral(v) for k, v in value.items() if not str(k).startswith("__bpfw_")}
    if isinstance(value, list):
        return [strip_ephemeral(v) for v in value]
    return value


def infer_artifact_metadata(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic metadata additions only; never infer semantic intent."""
    updates: dict[str, Any] = {}
    raw_path = artifact.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return updates
    path = Path(raw_path.replace("\\", "/"))
    posix = path.as_posix().lower()
    suffix = path.suffix.lower()
    if not artifact.get("language") and suffix in _LANGUAGE_BY_SUFFIX and suffix in {".go", ".py", ".rs", ".html", ".htm", ".css"}:
        updates["language"] = _LANGUAGE_BY_SUFFIX[suffix]
    if not artifact.get("type"):
        if path.name.upper() == "SKILL.MD": updates["type"] = "skill"
        elif "/prompts/" in f"/{posix}" or posix.startswith("prompts/"): updates["type"] = "prompt"
        elif suffix in {".yaml", ".yml", ".json", ".toml"}: updates["type"] = "config"
        elif suffix in {".go", ".py", ".rs", ".html", ".htm", ".css"}: updates["type"] = "code"
        elif suffix == ".md": updates["type"] = "spec"
    effective_type = str(artifact.get("type") or updates.get("type") or "")
    if not artifact.get("role"):
        if path.name.endswith("_test.go") or path.name.startswith("test_") and suffix == ".py": updates["role"] = "verification"
        elif path.name.upper() == "SKILL.MD": updates["role"] = "orchestration"
        elif effective_type == "prompt": updates["role"] = "behavior_contract"
        elif effective_type == "config": updates["role"] = "configuration"
    return updates


def redundant_artifact_fields(blueprint: dict[str, Any], artifact: dict[str, Any]) -> list[str]:
    """Fields explicit in artifact but identical to inherited defaults/profile."""
    profile_name = artifact.get("profile")
    profiles = blueprint.get("profiles")
    profile_data = profiles.get(profile_name) if isinstance(profiles, dict) and isinstance(profile_name, str) else None
    artifact_type = artifact.get("type") or (profile_data.get("type") if isinstance(profile_data, dict) else None) or "code"
    inherited = artifact_defaults(blueprint, str(artifact_type))
    if isinstance(profile_data, dict):
        inherited = _deep_merge(inherited, profile_data)
    skip = {"id", "uid", "profile", "path", "symbol", "selector", "properties"}
    return [k for k, v in artifact.items() if k not in skip and k in inherited and inherited[k] == v]
