"""Tests for runtime contract validation."""

import pytest

from bpfw.catalog.models import CatalogSnapshot, ResponsibilityDefinition
from bpfw.catalog.runtime_contract import (
    OwnerLayerRuntimeAlignmentError,
    UndeclaredActiveComponentError,
    UndeclaredPublicEntrypointError,
    validate_runtime_contract,
)


def _make_snapshot(
    responsibility_id: str = "resp.test",
    canonical_name: str = "Test Responsibility",
    public_entrypoints: tuple[str, ...] = ("entry_a",),
    allowed_components: tuple[str, ...] = ("component_a",),
    allowed_implementations: tuple[str, ...] = ("impl_a",),
    owner_layer: str = "domain",
) -> CatalogSnapshot:
    responsibility = ResponsibilityDefinition(
        responsibility_id=responsibility_id,
        canonical_name=canonical_name,
        owner_layer=owner_layer,
        is_public=bool(public_entrypoints),
        official_port=None,
        public_entrypoints=public_entrypoints,
        allowed_components=allowed_components,
        allowed_implementations=allowed_implementations,
        active_implementation=allowed_implementations[0] if allowed_implementations else "",
        lifecycle_state="active",
        allowed_replacements=(),
        forbidden_direct_instantiation=(),
    )
    return CatalogSnapshot(responsibilities=(responsibility,))


def test_runtime_contract_accepts_empty_declared_state() -> None:
    snapshot = _make_snapshot()
    validate_runtime_contract(snapshot, {})


def test_runtime_contract_rejects_undeclared_component() -> None:
    snapshot = _make_snapshot()
    with pytest.raises(UndeclaredActiveComponentError):
        validate_runtime_contract(snapshot, {"active_components": ["undeclared_component"]})


def test_runtime_contract_rejects_undeclared_entrypoint() -> None:
    snapshot = _make_snapshot()
    with pytest.raises(UndeclaredPublicEntrypointError):
        validate_runtime_contract(snapshot, {"public_entrypoints": ["undeclared_entry"]})


def test_owner_layer_variation_application() -> None:
    snapshot = _make_snapshot(
        owner_layer="application",
        allowed_implementations=("src.application.services.QueryService",),
    )
    validate_runtime_contract(
        snapshot,
        {"active_implementations": ["src.application.services.QueryService"]},
    )


def test_owner_layer_variation_infrastructure() -> None:
    snapshot = _make_snapshot(
        owner_layer="infrastructure",
        allowed_implementations=("src.infrastructure.persistence.VectorStore",),
    )
    validate_runtime_contract(
        snapshot,
        {"active_implementations": ["src.infrastructure.persistence.VectorStore"]},
    )


def test_owner_layer_mismatch_fails() -> None:
    snapshot = _make_snapshot(
        owner_layer="domain",
        allowed_implementations=("src.application.services.QueryService",),
    )
    with pytest.raises(OwnerLayerRuntimeAlignmentError):
        validate_runtime_contract(
            snapshot,
            {"active_implementations": ["src.application.services.QueryService"]},
        )
