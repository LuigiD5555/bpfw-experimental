"""Tests for RC00X runtime-contract mapping and IMPL001 existence checks."""

from types import SimpleNamespace

from tests.architecture.conftest import make_responsibility, make_snapshot
from bpfw.architecture.checker import (
    _check_implementation_existence,
    _check_runtime_contract_alignment,
)


def test_rc001_detects_undeclared_components() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "resp.search",
            allowed_components=("DeclaredComponent",),
            allowed_implementations=("DeclaredImplementation",),
        )
    )
    runtime_snapshot = SimpleNamespace(
        active_components=("UndeclaredComponent",),
        active_implementations=("DeclaredImplementation",),
        public_entrypoints=(),
        active_providers=(),
    )

    violations = _check_runtime_contract_alignment(snapshot, runtime_snapshot)

    assert len(violations) == 1
    assert violations[0].rule_id == "RC001"
    assert violations[0].category == "runtime_contract_violation"


def test_rc002_detects_duplicate_active_implementations() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "resp.search",
            allowed_implementations=("DeclaredImplementation",),
        )
    )
    runtime_snapshot = SimpleNamespace(
        active_components=(),
        active_implementations=("DeclaredImplementation", "DeclaredImplementation"),
        public_entrypoints=(),
        active_providers=(),
    )

    violations = _check_runtime_contract_alignment(snapshot, runtime_snapshot)

    assert len(violations) == 1
    assert violations[0].rule_id == "RC002"
    assert "appears more than once" in violations[0].message


def test_impl001_detects_nonexistent_module() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "resp.invalid_module",
            allowed_implementations=("src.nonexistent.module.MissingClass",),
        )
    )

    violations = _check_implementation_existence(snapshot)

    assert len(violations) == 1
    assert violations[0].rule_id == "IMPL001"
    assert "module 'src.nonexistent.module'" in violations[0].message


def test_impl001_detects_nonexistent_class() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "resp.invalid_class",
            allowed_implementations=("bpfw.catalog.models.MissingClass",),
        )
    )

    violations = _check_implementation_existence(snapshot)

    assert len(violations) == 1
    assert violations[0].rule_id == "IMPL001"
    assert "MissingClass" in violations[0].message


def test_impl001_passes_for_valid_implementations() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "resp.valid",
            allowed_implementations=("bpfw.catalog.models.CatalogSnapshot",),
        )
    )

    violations = _check_implementation_existence(snapshot)

    assert violations == []
