"""Architecture enforcement: every declared public entrypoint in a live responsibility
must be present in the runtime snapshot."""

import pytest

from bpfw.catalog.runtime_snapshot import RuntimeSnapshot
from bpfw.catalog.wiring_verifier import (
    MissingDeclaredEntrypointError,
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


def test_declared_entrypoints_present_when_component_is_live() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.ingest",
            public_entrypoints=("src.api.ingest",),
            allowed_components=("Ingester",),
            allowed_implementations=("DefaultIngester",),
        )
    )
    runtime = _make_runtime(
        active_components=("Ingester",),
        active_implementations=("DefaultIngester",),
        public_entrypoints=("src.api.ingest",),
    )
    # Must not raise
    verify_catalog_runtime_alignment(catalog, runtime)


def test_declared_entrypoint_absent_from_runtime_raises() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.ingest",
            public_entrypoints=("src.api.ingest",),
            allowed_components=("Ingester",),
            allowed_implementations=("DefaultIngester",),
        )
    )
    runtime = _make_runtime(
        active_components=("Ingester",),
        active_implementations=("DefaultIngester",),
        public_entrypoints=(),
    )
    with pytest.raises(MissingDeclaredEntrypointError):
        verify_catalog_runtime_alignment(catalog, runtime)


def test_entrypoint_not_checked_when_responsibility_has_no_live_component() -> None:
    """Entrypoint enforcement is skipped for responsibilities whose components are not live."""
    catalog = make_snapshot(
        make_responsibility(
            "r.ingest",
            public_entrypoints=("src.api.ingest",),
            allowed_components=("Ingester",),
            allowed_implementations=("DefaultIngester",),
        )
    )
    # No active components — entrypoint check is skipped
    runtime = _make_runtime(
        active_components=(),
        active_implementations=(),
        public_entrypoints=(),
    )
    verify_catalog_runtime_alignment(catalog, runtime)


def test_multiple_declared_entrypoints_all_required_when_live() -> None:
    catalog = make_snapshot(
        make_responsibility(
            "r.query",
            public_entrypoints=("src.api.query", "src.cli.query"),
            allowed_components=("QueryEngine",),
            allowed_implementations=("VectorQueryImpl",),
        )
    )
    runtime = _make_runtime(
        active_components=("QueryEngine",),
        active_implementations=("VectorQueryImpl",),
        public_entrypoints=("src.api.query",),  # missing src.cli.query
    )
    with pytest.raises(MissingDeclaredEntrypointError):
        verify_catalog_runtime_alignment(catalog, runtime)
