"""Typed snapshot of the active runtime state."""

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.bootstrap.registry.core_registry import (
    BackendCategory,
    Registry,
    build_registry_snapshot,
)
from aioa.catalog.loader import load_catalog_snapshot


_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[3] / ".cache" / "architecture" / "runtime_snapshot.json"
)


_ALL_BACKEND_CATEGORIES: tuple[BackendCategory, ...] = (
    "llm",
    "embeddings",
    "vector_store",
    "graph_store",
    "cache",
    "reranker",
)


@dataclass(frozen=True)
class RuntimeSnapshot:
    active_components: tuple[str, ...]
    active_implementations: tuple[str, ...]
    public_entrypoints: tuple[str, ...]
    active_providers: tuple[str, ...]


def build_runtime_snapshot_from_state(runtime_state: dict[str, object]) -> RuntimeSnapshot:
    """Normalize, sort, and freeze runtime state into a RuntimeSnapshot.

    Each recognized key is coerced to a sorted, deduplicated tuple of strings.
    Missing keys default to an empty tuple.
    """

    def _to_sorted_tuple(value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise TypeError(
                f"Expected list, tuple, or set; got {type(value).__name__!r}"
            )
        return tuple(sorted({str(item) for item in value}))

    return RuntimeSnapshot(
        active_components=_to_sorted_tuple(runtime_state.get("active_components")),
        active_implementations=_to_sorted_tuple(runtime_state.get("active_implementations")),
        public_entrypoints=_to_sorted_tuple(runtime_state.get("public_entrypoints")),
        active_providers=_to_sorted_tuple(runtime_state.get("active_providers")),
    )


def capture_runtime_snapshot(
    effective_entrypoints: Collection[str] | None = None,
) -> RuntimeSnapshot:
    """Build a RuntimeSnapshot from the live bootstrap registry and catalog.

    Sources:
    - active_components / active_implementations: gatekeeper state in core_registry
    - public_entrypoints: see below
    - active_providers: backend categories that have at least one registered factory

    public_entrypoints resolution:
    - If ``effective_entrypoints`` is provided, it is used directly. The caller is
      responsible for sourcing these from an independent runtime observation (e.g.
      FastAPI ``app.routes``, CLI module introspection). This is the only path that
      produces evidence independent of the catalog.
    - If ``effective_entrypoints`` is None, entrypoints are derived from the catalog
      filtered by live active_components (catalog projection). This reflects
      catalog + gatekeeper consistency, NOT independent proof that a route or CLI
      entrypoint is effectively wired. Any validation using this path is limited to
      internal consistency and must not be presented as closed wiring verification.
    """
    registry_state = build_registry_snapshot()
    active_pairs: dict[str, str] = registry_state["active"]  # type: ignore[assignment]
    live_components: set[str] = set(active_pairs.keys())

    if effective_entrypoints is not None:
        resolved_entrypoints: Collection[str] = effective_entrypoints
    else:
        catalog = load_catalog_snapshot()
        resolved_entrypoints = [
            entrypoint
            for responsibility in catalog.responsibilities
            if responsibility.is_public and live_components.intersection(responsibility.allowed_components)
            for entrypoint in responsibility.public_entrypoints
        ]

    active_providers: list[str] = [
        category
        for category in _ALL_BACKEND_CATEGORIES
        if Registry.list_backends(category)
    ]

    return build_runtime_snapshot_from_state(
        {
            "active_components": list(active_pairs.keys()),
            "active_implementations": list(active_pairs.values()),
            "public_entrypoints": list(resolved_entrypoints),
            "active_providers": active_providers,
        }
    )


def _catalog_hash() -> str:
    """Return a short SHA-256 digest of all catalog YAML files combined.

    Used as a staleness signal in the persisted snapshot. If the catalog
    changes between bootstrap and checker invocation, the hash mismatch
    causes load_persisted_runtime_snapshot() to return None, treating
    the snapshot as stale. This forces re-bootstrap to generate a fresh
    snapshot aligned with the current catalog structure.
    """
    try:
        from aioa.catalog.catalog_paths import list_catalog_yaml_files
        combined = hashlib.sha256()
        for yaml_path in sorted(list_catalog_yaml_files()):
            combined.update(yaml_path.read_bytes())
        return combined.hexdigest()[:12]
    except Exception:
        return "unknown"


def persist_runtime_snapshot(
    snapshot: RuntimeSnapshot,
    snapshot_path: Path = _SNAPSHOT_PATH,
) -> None:
    """Write the runtime snapshot to disk as a JSON artifact.

    Called by BootstrapContainer.create() after both post-assembly validations
    pass. The file represents the last known good runtime state and is the
    canonical source for check_architecture.py RC001/WV001 checks.

    Fields written:
    - active_components, active_implementations, public_entrypoints,
      active_providers: direct snapshot fields (sorted tuples → lists).
    - timestamp: ISO-8601 UTC timestamp of bootstrap completion.
    - catalog_hash: short SHA-256 of the catalog file at bootstrap time.
    """
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_components": list(snapshot.active_components),
        "active_implementations": list(snapshot.active_implementations),
        "public_entrypoints": list(snapshot.public_entrypoints),
        "active_providers": list(snapshot.active_providers),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "catalog_hash": _catalog_hash(),
    }
    snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_persisted_runtime_snapshot(
    snapshot_path: Path = _SNAPSHOT_PATH,
) -> RuntimeSnapshot | None:
    """Load the persisted runtime snapshot from disk.

    Returns None if:
    - The file does not exist
    - The file cannot be parsed
    - The catalog_hash in the snapshot does not match the current catalog

    Callers can treat None as "no known valid bootstrap" without raising.

    Staleness semantics: the catalog_hash is a staleness signal. If the catalog
    has changed since the snapshot was persisted (hash mismatch), the snapshot
    is considered stale and is treated as absent. This prevents mixing "old
    valid state" with "new structure not yet bootstrapped" — the caller must
    re-bootstrap to generate a fresh snapshot.
    """
    if not snapshot_path.exists():
        return None
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    # Staleness check: if catalog changed since bootstrap, snapshot is invalid
    stored_hash = payload.get("catalog_hash", "")
    current_hash = _catalog_hash()
    if stored_hash != current_hash:
        return None

    return build_runtime_snapshot_from_state({
        "active_components": payload.get("active_components", []),
        "active_implementations": payload.get("active_implementations", []),
        "public_entrypoints": payload.get("public_entrypoints", []),
        "active_providers": payload.get("active_providers", []),
    })
