"""Architecture enforcement: runtime entrypoints not declared in the catalog must be rejected."""

import pytest

from bpfw.catalog.runtime_snapshot import RuntimeSnapshot
from bpfw.catalog.wiring_verifier import (
    UndeclaredRuntimeEntrypointError,
    verify_catalog_runtime_alignment,
)
from tests.architecture.conftest import make_responsibility, make_snapshot


def _make_runtime(
    active_components: tuple[str, ...] = (),
    active_implementations: tuple[str, ...] = (),
    public_entrypoints: tuple[str, ...] = (),
) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        active_components=active_components,
        active_implementations=active_implementations,
        public_entrypoints=public_entrypoints,
        active_providers=(),
    )


def test_runtime_entrypoint_matching_catalog_passes() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.search",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("WeaviateImpl",),
        )
    )
    runtime = _make_runtime(
        active_components=("SearchEngine",),
        active_implementations=("WeaviateImpl",),
        public_entrypoints=("src.api.search",),
    )
    verify_catalog_runtime_alignment(catalog, runtime)


def test_runtime_entrypoint_not_in_catalog_raises() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.search",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("WeaviateImpl",),
        )
    )
    runtime = _make_runtime(
        active_components=("SearchEngine",),
        active_implementations=("WeaviateImpl",),
        public_entrypoints=("src.api.search", "src.api.shadow_endpoint"),
    )
    with pytest.raises(UndeclaredRuntimeEntrypointError):
        verify_catalog_runtime_alignment(catalog, runtime)


def test_entirely_undeclared_runtime_entrypoint_raises() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.empty",
            allowed_components=("SomeComponent",),
            allowed_implementations=("SomeImpl",),
        )
    )
    runtime = _make_runtime(
        public_entrypoints=("src.api.ghost",),
    )
    with pytest.raises(UndeclaredRuntimeEntrypointError):
        verify_catalog_runtime_alignment(catalog, runtime)


def test_empty_runtime_entrypoints_passes() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.search",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("WeaviateImpl",),
        )
    )
    # No active components → entrypoint enforcement is skipped; no runtime entrypoints → passes
    runtime = _make_runtime()
    verify_catalog_runtime_alignment(catalog, runtime)
