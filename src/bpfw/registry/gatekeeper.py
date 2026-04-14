"""Framework-level gatekeeper for catalog-backed active component state."""

import threading

from bpfw.catalog.models import CatalogSnapshot
from bpfw.registry.errors import (
    DuplicateActiveImplementationError,
    ForbiddenImplementationError,
    InactiveLifecycleError,
    UnregisteredComponentError,
)

_gatekeeper_lock = threading.RLock()
_active_components: dict[str, str] = {}
_rejected_components: dict[str, str] = {}
_ACTIVE_LIFECYCLE_STATE = "active"


def _resolve_lifecycle_state(
    component_name: str,
    implementation_name: str,
    catalog_snapshot: CatalogSnapshot,
) -> str:
    for responsibility in catalog_snapshot.responsibilities:
        if (
            component_name in responsibility.allowed_components
            and implementation_name in responsibility.allowed_implementations
        ):
            return responsibility.lifecycle_state
    return "unknown"


def validate_component_registration(component_name: str, catalog_snapshot: CatalogSnapshot) -> None:
    all_components: set[str] = set()
    for responsibility in catalog_snapshot.responsibilities:
        all_components.update(responsibility.allowed_components)
    if component_name not in all_components:
        raise UnregisteredComponentError(
            f"Component '{component_name}' is not declared in the catalog."
        )


def validate_implementation_registration(
    implementation_name: str,
    catalog_snapshot: CatalogSnapshot,
) -> None:
    all_implementations: set[str] = set()
    for responsibility in catalog_snapshot.responsibilities:
        all_implementations.update(responsibility.allowed_implementations)
    if implementation_name not in all_implementations:
        raise ForbiddenImplementationError(
            f"Implementation '{implementation_name}' is not listed as allowed in the catalog."
        )


def assert_single_active_implementation(
    component_name: str,
    implementation_name: str,
    active_pairs: dict[str, str],
) -> None:
    existing = active_pairs.get(component_name)
    if existing is not None and existing != implementation_name:
        raise DuplicateActiveImplementationError(
            f"Component '{component_name}' already has active implementation '{existing}'; "
            f"cannot activate '{implementation_name}'."
        )


def register_component(
    component_name: str,
    implementation_name: str,
    catalog_snapshot: CatalogSnapshot,
) -> None:
    if not component_name or not component_name.strip():
        raise ValueError("component_name must be non-empty")
    if not implementation_name or not implementation_name.strip():
        raise ValueError("implementation_name must be non-empty")

    validate_component_registration(component_name, catalog_snapshot)
    validate_implementation_registration(implementation_name, catalog_snapshot)

    lifecycle_state = _resolve_lifecycle_state(component_name, implementation_name, catalog_snapshot)
    if lifecycle_state != _ACTIVE_LIFECYCLE_STATE:
        raise InactiveLifecycleError(
            f"Cannot activate component '{component_name}' with implementation "
            f"'{implementation_name}': lifecycle_state is '{lifecycle_state}', "
            f"expected '{_ACTIVE_LIFECYCLE_STATE}'."
        )

    with _gatekeeper_lock:
        assert_single_active_implementation(component_name, implementation_name, _active_components)
        _active_components[component_name] = implementation_name
        _rejected_components.pop(component_name, None)


def reject_component(component_name: str, reason: str) -> None:
    if not component_name or not component_name.strip():
        raise ValueError("component_name must be non-empty")
    if not reason or not reason.strip():
        raise ValueError("reason must be non-empty")
    with _gatekeeper_lock:
        _rejected_components[component_name] = reason
        _active_components.pop(component_name, None)


def build_registry_snapshot() -> dict[str, object]:
    with _gatekeeper_lock:
        return {
            "active": dict(_active_components),
            "rejected": dict(_rejected_components),
        }


def clear_registry_state() -> None:
    with _gatekeeper_lock:
        _active_components.clear()
        _rejected_components.clear()

