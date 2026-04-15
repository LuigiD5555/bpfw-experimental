"""Tests for lifecycle enforcement in runtime contract alignment.

Verifies that runtime components and implementations belonging to non-active
responsibilities are blocked by validate_lifecycle_runtime_alignment and
validate_runtime_contract.

Blocked lifecycle states: experimental, deprecated, legacy.
Allowed: active.
"""

import pytest

from bpfw.catalog.runtime_contract import (
    AmbiguousLifecycleOwnershipError,
    InactiveLifecycleRuntimeAlignmentError,
    validate_lifecycle_runtime_alignment,
    validate_runtime_contract,
)
from tests.architecture.conftest import make_responsibility, make_snapshot


# ---------------------------------------------------------------------------
# validate_lifecycle_runtime_alignment — component checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lifecycle_state", ["experimental", "deprecated", "legacy"])
def test_inactive_component_blocked_for_each_non_active_state(lifecycle_state: str) -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            allowed_components=("BlockedEngine",),
            lifecycle_state=lifecycle_state,
        ),
    )
    with pytest.raises(InactiveLifecycleRuntimeAlignmentError):
        validate_lifecycle_runtime_alignment(
            snapshot, {"active_components": ["BlockedEngine"]}
        )


def test_active_component_allowed_when_lifecycle_is_active() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            allowed_components=("AllowedEngine",),
            lifecycle_state="active",
        ),
    )
    validate_lifecycle_runtime_alignment(
        snapshot, {"active_components": ["AllowedEngine"]}
    )


# ---------------------------------------------------------------------------
# validate_lifecycle_runtime_alignment — implementation checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lifecycle_state", ["experimental", "deprecated", "legacy"])
def test_inactive_implementation_blocked_for_each_non_active_state(lifecycle_state: str) -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            allowed_implementations=("BlockedImpl",),
            lifecycle_state=lifecycle_state,
        ),
    )
    with pytest.raises(InactiveLifecycleRuntimeAlignmentError):
        validate_lifecycle_runtime_alignment(
            snapshot, {"active_implementations": ["BlockedImpl"]}
        )


def test_active_implementation_allowed_when_lifecycle_is_active() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            allowed_implementations=("AllowedImpl",),
            lifecycle_state="active",
        ),
    )
    validate_lifecycle_runtime_alignment(
        snapshot, {"active_implementations": ["AllowedImpl"]}
    )


# ---------------------------------------------------------------------------
# Empty runtime state never triggers lifecycle errors
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lifecycle_state", ["experimental", "deprecated", "legacy"])
def test_empty_runtime_state_never_triggers_lifecycle_error(lifecycle_state: str) -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            allowed_components=("BlockedEngine",),
            allowed_implementations=("BlockedImpl",),
            lifecycle_state=lifecycle_state,
        ),
    )
    validate_lifecycle_runtime_alignment(snapshot, {})


# ---------------------------------------------------------------------------
# Mixed snapshot: active and non-active responsibilities coexist
# ---------------------------------------------------------------------------

def test_only_non_active_responsibility_component_is_blocked() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r_active",
            allowed_components=("GoodEngine",),
            lifecycle_state="active",
        ),
        make_responsibility(
            "r_deprecated",
            allowed_components=("OldEngine",),
            lifecycle_state="deprecated",
        ),
    )
    # GoodEngine is fine; OldEngine must be rejected.
    validate_lifecycle_runtime_alignment(
        snapshot, {"active_components": ["GoodEngine"]}
    )
    with pytest.raises(InactiveLifecycleRuntimeAlignmentError):
        validate_lifecycle_runtime_alignment(
            snapshot, {"active_components": ["OldEngine"]}
        )


# ---------------------------------------------------------------------------
# validate_runtime_contract integrates lifecycle enforcement
# ---------------------------------------------------------------------------

def test_validate_runtime_contract_rejects_deprecated_component() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            allowed_components=("OldEngine",),
            allowed_implementations=("OldImpl",),
            lifecycle_state="deprecated",
        ),
    )
    with pytest.raises(InactiveLifecycleRuntimeAlignmentError):
        validate_runtime_contract(snapshot, {"active_components": ["OldEngine"]})


def test_validate_runtime_contract_rejects_experimental_implementation() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            allowed_implementations=("ExperimentalImpl",),
            lifecycle_state="experimental",
        ),
    )
    with pytest.raises(InactiveLifecycleRuntimeAlignmentError):
        validate_runtime_contract(snapshot, {"active_implementations": ["ExperimentalImpl"]})


# ---------------------------------------------------------------------------
# Ambiguous lifecycle ownership — components
# ---------------------------------------------------------------------------

def test_validate_lifecycle_runtime_alignment_fails_for_component_owned_by_active_and_deprecated_responsibilities() -> None:
    """A component shared between active and deprecated responsibilities must fail.

    This cannot pass silently regardless of catalog order.
    """
    snapshot = make_snapshot(
        make_responsibility(
            "r_active",
            allowed_components=("SharedEngine",),
            lifecycle_state="active",
        ),
        make_responsibility(
            "r_deprecated",
            allowed_components=("SharedEngine",),
            lifecycle_state="deprecated",
        ),
    )
    with pytest.raises((AmbiguousLifecycleOwnershipError, InactiveLifecycleRuntimeAlignmentError)):
        validate_lifecycle_runtime_alignment(
            snapshot, {"active_components": ["SharedEngine"]}
        )


def test_validate_lifecycle_runtime_alignment_fails_for_component_owned_by_two_conflicting_non_active_responsibilities() -> None:
    """A component shared between experimental and legacy responsibilities must fail."""
    snapshot = make_snapshot(
        make_responsibility(
            "r_experimental",
            allowed_components=("SharedEngine",),
            lifecycle_state="experimental",
        ),
        make_responsibility(
            "r_legacy",
            allowed_components=("SharedEngine",),
            lifecycle_state="legacy",
        ),
    )
    with pytest.raises((AmbiguousLifecycleOwnershipError, InactiveLifecycleRuntimeAlignmentError)):
        validate_lifecycle_runtime_alignment(
            snapshot, {"active_components": ["SharedEngine"]}
        )


def test_validate_lifecycle_runtime_alignment_does_not_depend_on_catalog_order_for_shared_component() -> None:
    """Result must not change when catalog order is reversed (setdefault-style collapse is absent)."""
    snapshot_order_a = make_snapshot(
        make_responsibility(
            "r_active",
            allowed_components=("SharedEngine",),
            lifecycle_state="active",
        ),
        make_responsibility(
            "r_deprecated",
            allowed_components=("SharedEngine",),
            lifecycle_state="deprecated",
        ),
    )
    snapshot_order_b = make_snapshot(
        make_responsibility(
            "r_deprecated",
            allowed_components=("SharedEngine",),
            lifecycle_state="deprecated",
        ),
        make_responsibility(
            "r_active",
            allowed_components=("SharedEngine",),
            lifecycle_state="active",
        ),
    )
    runtime = {"active_components": ["SharedEngine"]}
    # Both orderings must raise — no silent pass due to catalog order.
    with pytest.raises((AmbiguousLifecycleOwnershipError, InactiveLifecycleRuntimeAlignmentError)):
        validate_lifecycle_runtime_alignment(snapshot_order_a, runtime)
    with pytest.raises((AmbiguousLifecycleOwnershipError, InactiveLifecycleRuntimeAlignmentError)):
        validate_lifecycle_runtime_alignment(snapshot_order_b, runtime)


# ---------------------------------------------------------------------------
# Ambiguous lifecycle ownership — implementations
# ---------------------------------------------------------------------------

def test_validate_lifecycle_runtime_alignment_fails_for_implementation_owned_by_active_and_deprecated_responsibilities() -> None:
    """An implementation shared between active and deprecated responsibilities must fail."""
    snapshot = make_snapshot(
        make_responsibility(
            "r_active",
            allowed_implementations=("SharedImpl",),
            lifecycle_state="active",
        ),
        make_responsibility(
            "r_deprecated",
            allowed_implementations=("SharedImpl",),
            lifecycle_state="deprecated",
        ),
    )
    with pytest.raises((AmbiguousLifecycleOwnershipError, InactiveLifecycleRuntimeAlignmentError)):
        validate_lifecycle_runtime_alignment(
            snapshot, {"active_implementations": ["SharedImpl"]}
        )


def test_validate_lifecycle_runtime_alignment_does_not_depend_on_catalog_order_for_shared_implementation() -> None:
    """Result must not change when catalog order is reversed for implementations."""
    snapshot_order_a = make_snapshot(
        make_responsibility(
            "r_active",
            allowed_implementations=("SharedImpl",),
            lifecycle_state="active",
        ),
        make_responsibility(
            "r_deprecated",
            allowed_implementations=("SharedImpl",),
            lifecycle_state="deprecated",
        ),
    )
    snapshot_order_b = make_snapshot(
        make_responsibility(
            "r_deprecated",
            allowed_implementations=("SharedImpl",),
            lifecycle_state="deprecated",
        ),
        make_responsibility(
            "r_active",
            allowed_implementations=("SharedImpl",),
            lifecycle_state="active",
        ),
    )
    runtime = {"active_implementations": ["SharedImpl"]}
    with pytest.raises((AmbiguousLifecycleOwnershipError, InactiveLifecycleRuntimeAlignmentError)):
        validate_lifecycle_runtime_alignment(snapshot_order_a, runtime)
    with pytest.raises((AmbiguousLifecycleOwnershipError, InactiveLifecycleRuntimeAlignmentError)):
        validate_lifecycle_runtime_alignment(snapshot_order_b, runtime)


# ---------------------------------------------------------------------------
# Unambiguous shared component — all owners active → passes
# ---------------------------------------------------------------------------

def test_component_shared_by_two_active_responsibilities_passes() -> None:
    """If all owners are active, a shared component must be allowed."""
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            allowed_components=("SharedEngine",),
            lifecycle_state="active",
        ),
        make_responsibility(
            "r2",
            allowed_components=("SharedEngine",),
            lifecycle_state="active",
        ),
    )
    validate_lifecycle_runtime_alignment(
        snapshot, {"active_components": ["SharedEngine"]}
    )


def test_validate_runtime_contract_accepts_fully_active_state() -> None:
    snapshot = make_snapshot(
        make_responsibility(
            "r1",
            public_entrypoints=("src.api.search",),
            allowed_components=("SearchEngine",),
            allowed_implementations=("ElasticSearchImpl",),
            lifecycle_state="active",
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
