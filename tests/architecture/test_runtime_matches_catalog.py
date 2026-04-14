"""Architecture enforcement: runtime state must align with catalog snapshot end-to-end."""

import pytest

from bpfw.catalog.runtime_contract import (
    DuplicateActiveImplementationError,
    UndeclaredActiveComponentError,
    UndeclaredActiveImplementationError,
    UndeclaredPublicEntrypointError,
    validate_runtime_contract,
)
from tests.architecture.conftest import make_responsibility, make_snapshot


def test_fully_aligned_runtime_passes() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("ElasticSearchImpl",),
        ),
    )
    validate_runtime_contract(
        snapshot,
        {
            "active_components": ["SearchEngine"],
            "active_implementations": ["ElasticSearchImpl"],
            "public_entrypoints": ["src.api.search"],
        },
    )


def test_undeclared_component_breaks_alignment() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_components=("SearchEngine",)))
    with pytest.raises(UndeclaredActiveComponentError):
        validate_runtime_contract(snapshot, {"active_components": ["UnknownEngine"]})


def test_undeclared_implementation_breaks_alignment() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_implementations=("KnownImpl",)))
    with pytest.raises(UndeclaredActiveImplementationError):
        validate_runtime_contract(snapshot, {"active_implementations": ["UnknownImpl"]})


def test_undeclared_entrypoint_breaks_alignment() -> None:
    snapshot = make_snapshot(make_responsibility("r1", public_entrypoints=("src.api.known",)))
    with pytest.raises(UndeclaredPublicEntrypointError):
        validate_runtime_contract(snapshot, {"public_entrypoints": ["src.api.unknown"]})


def test_duplicate_implementation_breaks_alignment() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_implementations=("ImplA",)))
    with pytest.raises(DuplicateActiveImplementationError):
        validate_runtime_contract(snapshot, {"active_implementations": ["ImplA", "ImplA"]})


def test_empty_runtime_state_passes() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("ElasticSearchImpl",),
        ),
    )
    validate_runtime_contract(snapshot, {})


def test_invalid_state_type_raises_type_error() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_components=("ComponentA",)))
    with pytest.raises(TypeError):
        validate_runtime_contract(
            snapshot,
            {"active_components": "ComponentA"},  # type: ignore[dict-item]
        )
