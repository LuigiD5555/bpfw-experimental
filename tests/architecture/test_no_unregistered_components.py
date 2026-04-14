"""Architecture enforcement: no unregistered (undeclared) active components."""

import pytest

from bpfw.catalog.runtime_contract import (
    UndeclaredActiveComponentError,
    validate_runtime_contract,
)
from tests.architecture.conftest import make_responsibility, make_snapshot


def test_declared_component_passes() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_components=("ComponentA",)))
    validate_runtime_contract(snapshot, {"active_components": ["ComponentA"]})


def test_undeclared_component_raises() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_components=("ComponentA",)))
    with pytest.raises(UndeclaredActiveComponentError):
        validate_runtime_contract(snapshot, {"active_components": ["UnknownComponent"]})


def test_component_declared_in_other_responsibility_passes() -> None:
    snapshot = make_snapshot(
        make_responsibility("r1", allowed_components=("ComponentA",)),
        make_responsibility("r2", allowed_components=("ComponentB",)),
    )
    validate_runtime_contract(snapshot, {"active_components": ["ComponentA", "ComponentB"]})


def test_empty_active_components_passes() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_components=("ComponentA",)))
    validate_runtime_contract(snapshot, {"active_components": []})


def test_no_active_components_key_passes() -> None:
    snapshot = make_snapshot(make_responsibility("r1", allowed_components=("ComponentA",)))
    validate_runtime_contract(snapshot, {})
