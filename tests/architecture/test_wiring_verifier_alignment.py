"""Tests for wiring verifier: bidirectional catalog ↔ runtime alignment.

Covers the four hardening scenarios from Prompt 43:
1. Implementation ownership must be per-responsibility (no ambiguous flat dict).
2. Live public responsibilities must not silently omit entrypoints due to component drift.
3. More than one active implementation per responsibility must fail.
4. Lifecycle scope is documented: verifier does not re-enforce lifecycle blocking.
"""

import pytest

from bpfw.catalog.models import CatalogSnapshot, ResponsibilityDefinition
from bpfw.catalog.runtime_snapshot import RuntimeSnapshot
from bpfw.catalog.wiring_verifier import (
    AmbiguousImplementationOwnershipError,
    MissingDeclaredEntrypointError,
    UndeclaredRuntimeComponentError,
    UndeclaredRuntimeEntrypointError,
    UndeclaredWiringPathError,
    collect_declared_public_entrypoints,
    verify_catalog_runtime_alignment,
)
from tests.architecture.conftest import make_responsibility, make_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Baseline: fully aligned snapshot passes
# ---------------------------------------------------------------------------

def test_fully_aligned_snapshot_passes() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("ElasticSearchImpl",),
        ),
    )
    runtime = _make_runtime(
        active_components=("SearchEngine",),
        active_implementations=("ElasticSearchImpl",),
        public_entrypoints=("src.api.search",),
    )
    verify_catalog_runtime_alignment(snapshot, runtime)


def test_empty_runtime_passes_no_active_components() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("ElasticSearchImpl",),
        ),
    )
    runtime = _make_runtime()
    # No components active → no entrypoints expected → should pass.
    verify_catalog_runtime_alignment(snapshot, runtime)


# ---------------------------------------------------------------------------
# Scenario 1 — Implementation ownership per responsibility, no ambiguous flat dict
# ---------------------------------------------------------------------------

def test_implementation_owned_by_one_responsibility_passes() -> None:
    snapshot = make_snapshot(
        make_responsibility("r1", allowed_implementations=("ImplA",)),
        make_responsibility("r2", allowed_implementations=("ImplB",)),
    )
    runtime = _make_runtime(active_implementations=("ImplA",))
    verify_catalog_runtime_alignment(snapshot, runtime)


def test_implementation_owned_by_two_responsibilities_raises_ambiguous_error() -> None:
    """An impl in allowed_implementations of two responsibilities is ambiguous."""
    snapshot = make_snapshot(
        make_responsibility("r1", allowed_implementations=("SharedImpl",)),
        make_responsibility("r2", allowed_implementations=("SharedImpl",)),
    )
    runtime = _make_runtime(active_implementations=("SharedImpl",))
    with pytest.raises(AmbiguousImplementationOwnershipError):
        verify_catalog_runtime_alignment(snapshot, runtime)


def test_implementation_not_in_any_allowed_implementations_raises_undeclared_wiring() -> None:
    snapshot = make_snapshot(
        make_responsibility("r1", allowed_implementations=("KnownImpl",)),
    )
    runtime = _make_runtime(active_implementations=("UnknownImpl",))
    with pytest.raises(UndeclaredWiringPathError):
        verify_catalog_runtime_alignment(snapshot, runtime)


def test_implementation_allowed_but_not_active_in_catalog_raises_undeclared_wiring() -> None:
    """impl is in allowed_implementations but does not match active_implementation."""
    responsibility = ResponsibilityDefinition(
        responsibility_id="r1",
        canonical_name="r1",
        owner_layer="domain",
        is_public=False,
        official_port=None,
        public_entrypoints=(),
        allowed_components=(),
        allowed_implementations=("AllowedButNotActive", "ActiveImpl"),
        active_implementation="ActiveImpl",
        lifecycle_state="active",
        allowed_replacements=(),
        forbidden_direct_instantiation=(),
    )
    snapshot = CatalogSnapshot(responsibilities=(responsibility,))
    # AllowedButNotActive is allowed but is not the active_implementation.
    runtime = _make_runtime(active_implementations=("AllowedButNotActive",))
    with pytest.raises(UndeclaredWiringPathError):
        verify_catalog_runtime_alignment(snapshot, runtime)


# ---------------------------------------------------------------------------
# Scenario 2 — Live public responsibilities must not silently omit entrypoints
# ---------------------------------------------------------------------------

def test_live_public_responsibility_with_missing_entrypoint_raises() -> None:
    """When a public responsibility's component is active, all its entrypoints must appear."""
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            public_entrypoints=("src.api.search", "src.api.health"),
            allowed_components=("SearchEngine",),
            allowed_implementations=("ImplA",),
        ),
    )
    # SearchEngine is active but only one entrypoint is in the runtime snapshot.
    runtime = _make_runtime(
        active_components=("SearchEngine",),
        active_implementations=("ImplA",),
        public_entrypoints=("src.api.search",),  # src.api.health is missing
    )
    with pytest.raises(MissingDeclaredEntrypointError):
        verify_catalog_runtime_alignment(snapshot, runtime)


def test_inactive_responsibility_entrypoints_are_not_required() -> None:
    """A public responsibility with no live components must not demand its entrypoints."""
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("ImplA",),
        ),
    )
    # No components are active → entrypoints not expected.
    runtime = _make_runtime(public_entrypoints=())
    verify_catalog_runtime_alignment(snapshot, runtime)


def test_component_drift_does_not_silently_hide_missing_entrypoints() -> None:
    """If two responsibilities share a component, both sets of entrypoints must appear."""
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            public_entrypoints=("src.api.search",),
            allowed_components=("SharedEngine",),
            allowed_implementations=("ImplA",),
        ),
        make_responsibility(
            "r2",
            public_entrypoints=("src.api.ingest",),
            allowed_components=("SharedEngine",),
            allowed_implementations=("ImplB",),
        ),
    )
    # SharedEngine is live → both r1 and r2 are live → both entrypoints required.
    # Only src.api.search provided → src.api.ingest is missing.
    runtime = _make_runtime(
        active_components=("SharedEngine",),
        active_implementations=("ImplA",),
        public_entrypoints=("src.api.search",),
    )
    with pytest.raises(MissingDeclaredEntrypointError):
        verify_catalog_runtime_alignment(snapshot, runtime)


# ---------------------------------------------------------------------------
# Scenario 3 — More than one active implementation per responsibility must fail
# ---------------------------------------------------------------------------

def test_two_active_implementations_same_responsibility_raises() -> None:
    """Two runtime implementations owned by the same responsibility must fail."""
    responsibility = ResponsibilityDefinition(
        responsibility_id="r1",
        canonical_name="r1",
        owner_layer="domain",
        is_public=False,
        official_port=None,
        public_entrypoints=(),
        allowed_components=(),
        allowed_implementations=("ImplA", "ImplB"),
        active_implementation="ImplA",
        lifecycle_state="active",
        allowed_replacements=(),
        forbidden_direct_instantiation=(),
    )
    snapshot = CatalogSnapshot(responsibilities=(responsibility,))
    # Both ImplA and ImplB belong to r1 → second one triggers the single-active check.
    runtime = _make_runtime(active_implementations=("ImplA", "ImplB"))
    with pytest.raises(UndeclaredWiringPathError):
        verify_catalog_runtime_alignment(snapshot, runtime)


# ---------------------------------------------------------------------------
# Scenario 4 — Lifecycle scope: verifier does not re-enforce lifecycle blocking
# ---------------------------------------------------------------------------

def test_deprecated_responsibility_with_no_active_component_passes_verifier() -> None:
    """Verifier does not block deprecated responsibilities that have no live component.

    Lifecycle blocking (deprecated/legacy) is enforced by
    runtime_contract.validate_lifecycle_runtime_alignment, not here.
    This test documents that the wiring verifier does not duplicate that check.
    """
    snapshot = make_snapshot(
        make_responsibility(
            "r_deprecated",
            public_entrypoints=("src.api.old",),
            allowed_components=("OldEngine",),
            allowed_implementations=("OldImpl",),
            lifecycle_state="deprecated",
        ),
    )
    # No components active → verifier does not demand entrypoints for deprecated resp.
    runtime = _make_runtime()
    verify_catalog_runtime_alignment(snapshot, runtime)


# ---------------------------------------------------------------------------
# Other regression checks
# ---------------------------------------------------------------------------

def test_undeclared_runtime_component_raises() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_components=("KnownEngine",)))
    runtime = _make_runtime(active_components=("UnknownEngine",))
    with pytest.raises(UndeclaredRuntimeComponentError):
        verify_catalog_runtime_alignment(snapshot, runtime)


def test_undeclared_runtime_entrypoint_raises() -> None:
    snapshot = make_snapshot(
        make_responsibility("r1", public_entrypoints=("src.api.known",)),
    )
    runtime = _make_runtime(public_entrypoints=("src.api.unknown",))
    with pytest.raises(UndeclaredRuntimeEntrypointError):
        verify_catalog_runtime_alignment(snapshot, runtime)


def test_collect_declared_public_entrypoints_returns_only_public() -> None:
    snapshot = make_snapshot(
        make_responsibility("r_pub", public_entrypoints=("src.api.public",)),
        make_responsibility("r_priv"),  # is_public=False, no entrypoints
    )
    result = collect_declared_public_entrypoints(snapshot)
    assert result == {"src.api.public"}
