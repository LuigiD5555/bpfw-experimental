"""Architecture enforcement: runtime public entrypoints must match catalog declarations."""

import pytest

from bpfw.catalog.runtime_contract import (
    UndeclaredPublicEntrypointError,
    validate_runtime_contract,
)
from tests.architecture.conftest import make_responsibility, make_snapshot


def test_declared_entrypoint_passes() -> None:
    snapshot = make_snapshot(make_responsibility("r1", public_entrypoints=("src.api.search",)))
    validate_runtime_contract(snapshot, {"public_entrypoints": ["src.api.search"]})


def test_undeclared_entrypoint_raises() -> None:
    snapshot = make_snapshot(make_responsibility("r1", public_entrypoints=("src.api.search",)))
    with pytest.raises(UndeclaredPublicEntrypointError):
        validate_runtime_contract(snapshot, {"public_entrypoints": ["src.api.undeclared_route"]})


def test_entrypoints_from_multiple_responsibilities_pass() -> None:
    snapshot = make_snapshot(
        make_responsibility("r1", public_entrypoints=("src.api.search",)),
        make_responsibility("r2", public_entrypoints=("src.api.ingest",)),
    )
    validate_runtime_contract(snapshot, {"public_entrypoints": ["src.api.search", "src.api.ingest"]})


def test_empty_entrypoints_passes() -> None:
    snapshot = make_snapshot(make_responsibility("r1", public_entrypoints=("src.api.search",)))
    validate_runtime_contract(snapshot, {"public_entrypoints": []})


def test_subset_of_declared_entrypoints_passes() -> None:
    """Runtime is allowed to expose fewer entrypoints than declared."""
    snapshot = make_snapshot(
        make_responsibility("r1", public_entrypoints=("src.api.search", "src.api.health")),
    )
    validate_runtime_contract(snapshot, {"public_entrypoints": ["src.api.search"]})
