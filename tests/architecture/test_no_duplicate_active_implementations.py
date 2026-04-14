"""Architecture enforcement: no duplicate active implementations per responsibility."""

import pytest

from bpfw.catalog.runtime_contract import (
    DuplicateActiveImplementationError,
    validate_runtime_contract,
)
from tests.architecture.conftest import make_responsibility, make_snapshot


def test_single_implementation_passes() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_implementations=("ImplA",)))
    validate_runtime_contract(snapshot, {"active_implementations": ["ImplA"]})


def test_duplicate_implementation_raises() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_implementations=("ImplA",)))
    with pytest.raises(DuplicateActiveImplementationError):
        validate_runtime_contract(snapshot, {"active_implementations": ["ImplA", "ImplA"]})


def test_different_implementations_different_responsibilities_passes() -> None:
    """Two responsibilities each with a distinct active implementation do not conflict."""
    snapshot = make_snapshot(
        make_responsibility("r1", allowed_implementations=("ImplA",)),
        make_responsibility("r2", allowed_implementations=("ImplB",)),
    )
    validate_runtime_contract(snapshot, {"active_implementations": ["ImplA", "ImplB"]})


def test_duplicate_shared_across_two_responsibilities_raises() -> None:
    """An implementation declared by two responsibilities, repeated in runtime, triggers duplicate check."""
    snapshot = make_snapshot(
        make_responsibility("r1", allowed_implementations=("SharedImpl",)),
        make_responsibility("r2", allowed_implementations=("SharedImpl",)),
    )
    with pytest.raises(DuplicateActiveImplementationError):
        validate_runtime_contract(snapshot, {"active_implementations": ["SharedImpl", "SharedImpl"]})


def test_empty_active_implementations_passes() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_implementations=("ImplA",)))
    validate_runtime_contract(snapshot, {"active_implementations": []})
