"""Architecture enforcement: catalog ↔ runtime bidirectional alignment via wiring verifier."""

import pytest

from bpfw.catalog.models import CatalogSnapshot, ResponsibilityDefinition
from bpfw.catalog.runtime_snapshot import RuntimeSnapshot
from bpfw.catalog.wiring_verifier import (
    AmbiguousImplementationOwnershipError,
    MissingDeclaredEntrypointError,
    UndeclaredRuntimeComponentError,
    UndeclaredRuntimeEntrypointError,
    UndeclaredWiringPathError,
    verify_catalog_runtime_alignment,
)
from tests.architecture.conftest import make_responsibility, make_snapshot


def _make_runtime(
    active_components: tuple[str, ...] = (),
    active_implementations: tuple[str, ...] = (),
    public_entrypoints: tuple[str, ...] = (),
    active_providers: tuple[str, ...] = (),
) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        active_components=active_components,
        active_implementations=active_implementations,
        public_entrypoints=public_entrypoints,
        active_providers=active_providers,
    )


def test_aligned_catalog_and_runtime_passes() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.search",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("WeaviateSearchImpl",),
        )
    )
    runtime = _make_runtime(
        active_components=("SearchEngine",),
        active_implementations=("WeaviateSearchImpl",),
        public_entrypoints=("src.api.search",),
    )
    verify_catalog_runtime_alignment(catalog, runtime)


def test_undeclared_active_component_raises() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.search",
            allowed_components=("SearchEngine",),
            allowed_implementations=("WeaviateSearchImpl",),
        )
    )
    runtime = _make_runtime(active_components=("UnknownEngine",))
    with pytest.raises(UndeclaredRuntimeComponentError):
        verify_catalog_runtime_alignment(catalog, runtime)


def test_missing_declared_entrypoint_raises() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.search",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("WeaviateSearchImpl",),
        )
    )
    # Component is live but entrypoint is absent from runtime snapshot
    runtime = _make_runtime(
        active_components=("SearchEngine",),
        active_implementations=("WeaviateSearchImpl",),
        public_entrypoints=(),
    )
    with pytest.raises(MissingDeclaredEntrypointError):
        verify_catalog_runtime_alignment(catalog, runtime)


def test_undeclared_runtime_entrypoint_raises() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.search",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("WeaviateSearchImpl",),
        )
    )
    runtime = _make_runtime(
        active_components=("SearchEngine",),
        active_implementations=("WeaviateSearchImpl",),
        public_entrypoints=("src.api.search", "src.api.undeclared"),
    )
    with pytest.raises(UndeclaredRuntimeEntrypointError):
        verify_catalog_runtime_alignment(catalog, runtime)


def test_lateral_wiring_path_raises() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.search",
            allowed_components=("SearchEngine",),
            allowed_implementations=("WeaviateSearchImpl",),
        )
    )
    # Active implementation belongs to allowed_implementations but declared active is different
    runtime = _make_runtime(
        active_components=("SearchEngine",),
        active_implementations=("AlternativeImpl",),
    )
    with pytest.raises(UndeclaredWiringPathError):
        verify_catalog_runtime_alignment(catalog, runtime)


def test_ambiguous_implementation_ownership_raises() -> None:
    # Same implementation declared in two responsibilities
    catalog = make_snapshot(
        make_responsibility(
            "r.alpha",
            allowed_components=("ComponentA",),
            allowed_implementations=("SharedImpl",),
        ),
        make_responsibility(
            "r.beta",
            allowed_components=("ComponentB",),
            allowed_implementations=("SharedImpl",),
        ),
    )
    runtime = _make_runtime(
        active_components=("ComponentA",),
        active_implementations=("SharedImpl",),
    )
    with pytest.raises(AmbiguousImplementationOwnershipError):
        verify_catalog_runtime_alignment(catalog, runtime)
