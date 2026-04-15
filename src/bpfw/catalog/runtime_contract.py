"""Runtime contract for the catalog: validates active runtime state against the catalog snapshot."""

from collections.abc import Collection
from typing import cast

from bpfw.catalog.models import CatalogSnapshot

_RUNTIME_STATE_KEYS = (
    "active_components",
    "active_implementations",
    "public_entrypoints",
    "active_providers",
)


class UndeclaredActiveComponentError(Exception):
    """Raised when a runtime active component is not declared in the catalog."""


class UndeclaredActiveImplementationError(Exception):
    """Raised when a runtime active implementation is not declared in the catalog."""


class UndeclaredPublicEntrypointError(Exception):
    """Raised when a runtime public entrypoint is not declared in the catalog."""


class DuplicateActiveImplementationError(Exception):
    """Raised when a runtime implementation appears more than once for the same responsibility."""


class InactiveLifecycleRuntimeAlignmentError(Exception):
    """Raised when runtime exposes a component or implementation belonging to a non-active responsibility."""


class AmbiguousLifecycleOwnershipError(Exception):
    """Raised when a runtime component or implementation belongs to more than one responsibility with conflicting lifecycle ownership."""


class OwnerLayerRuntimeAlignmentError(Exception):
    """Raised when a runtime implementation path does not match the owner layer namespace."""


_OWNER_LAYER_PREFIXES: dict[str, str] = {
    "domain": "src.domain.",
    "application": "src.application.",
    "infrastructure": "src.infrastructure.",
    "bootstrap": "src.bootstrap.",
    "public": "src.public.",
}


def normalize_runtime_state(
    runtime_state: dict[str, Collection[object]],
) -> dict[str, set[str]]:
    """Normalize runtime_state values to sets of strings.

    Recognized keys: active_components, active_implementations,
    public_entrypoints, active_providers.
    Missing keys default to an empty set.
    """
    return {
        key: {str(item) for item in runtime_state.get(key) or []}
        for key in _RUNTIME_STATE_KEYS
    }


def _assert_runtime_state_shape(runtime_state: dict[str, object]) -> None:
    """Raise TypeError if any recognized key holds a value other than list, tuple, set, or frozenset."""
    for key in _RUNTIME_STATE_KEYS:
        value = runtime_state.get(key)
        if value is not None and not isinstance(value, (list, tuple, set, frozenset)):
            raise TypeError(
                f"runtime_state['{key}'] must be a list, tuple, or set;"
                f" got {type(value).__name__!r}"
            )


def _build_impl_to_responsibilities(
    catalog_snapshot: CatalogSnapshot,
) -> dict[str, list[str]]:
    """Return a mapping from implementation name to the responsibility IDs that declare it."""
    index: dict[str, list[str]] = {}
    for responsibility in catalog_snapshot.responsibilities:
        for impl in responsibility.allowed_implementations:
            index.setdefault(impl, []).append(responsibility.responsibility_id)
    return index


def collect_declared_active_implementations(catalog_snapshot: CatalogSnapshot) -> set[str]:
    """Return the set of active_implementation values declared across all responsibilities."""
    return {
        responsibility.active_implementation
        for responsibility in catalog_snapshot.responsibilities
        if responsibility.active_implementation
    }


def validate_active_implementation_alignment(
    catalog_snapshot: CatalogSnapshot,
    runtime_state: dict[str, object],
) -> None:
    """Raise UndeclaredActiveImplementationError if any runtime active implementation
    does not match a declared active_implementation in the catalog.

    Raises:
        UndeclaredActiveImplementationError: if a runtime active implementation is not
            declared as an active_implementation in any responsibility.
    """
    declared = collect_declared_active_implementations(catalog_snapshot)
    typed_state = cast(dict[str, Collection[object]], runtime_state)
    raw_implementations: list[str] = [
        str(item) for item in typed_state.get("active_implementations") or []
    ]
    for impl in raw_implementations:
        if impl not in declared:
            raise UndeclaredActiveImplementationError(
                f"Active implementation '{impl}' does not match any declared"
                " active_implementation in the catalog."
            )


_INACTIVE_LIFECYCLE_STATES: frozenset[str] = frozenset(
    {"experimental", "deprecated", "legacy"}
)


def _build_component_lifecycle_owners(
    catalog_snapshot: CatalogSnapshot,
) -> dict[str, list[tuple[str, str]]]:
    """Return mapping: component_name → [(responsibility_id, lifecycle_state), ...].

    Every responsibility that declares the component in allowed_components is
    included. Using a list (not setdefault-collapse) preserves all owners so
    that ambiguous or conflicting lifecycle ownership can be detected explicitly.
    """
    owners: dict[str, list[tuple[str, str]]] = {}
    for responsibility in catalog_snapshot.responsibilities:
        for component in responsibility.allowed_components:
            owners.setdefault(component, []).append(
                (responsibility.responsibility_id, responsibility.lifecycle_state)
            )
    return owners


def _build_implementation_lifecycle_owners(
    catalog_snapshot: CatalogSnapshot,
) -> dict[str, list[tuple[str, str]]]:
    """Return mapping: implementation_name → [(responsibility_id, lifecycle_state), ...].

    Every responsibility that declares the implementation in allowed_implementations
    is included. Using a list preserves all owners for explicit ambiguity detection.
    """
    owners: dict[str, list[tuple[str, str]]] = {}
    for responsibility in catalog_snapshot.responsibilities:
        for impl in responsibility.allowed_implementations:
            owners.setdefault(impl, []).append(
                (responsibility.responsibility_id, responsibility.lifecycle_state)
            )
    return owners


def _validate_component_lifecycle_alignment(
    component: str,
    owners: list[tuple[str, str]],
) -> None:
    """Validate that a runtime active_component is safe to activate.

    Rules (evaluated over the full owner list, independent of catalog order):
    1. If owners have more than one distinct lifecycle_state → AmbiguousLifecycleOwnershipError.
    2. If the single distinct state is non-active → InactiveLifecycleRuntimeAlignmentError.

    Raises:
        AmbiguousLifecycleOwnershipError: owners disagree on lifecycle_state.
        InactiveLifecycleRuntimeAlignmentError: all owners share a non-active lifecycle_state.
    """
    lifecycle_states: set[str] = {lifecycle for _, lifecycle in owners}

    if len(lifecycle_states) > 1:
        owning_ids = sorted(resp_id for resp_id, _ in owners)
        raise AmbiguousLifecycleOwnershipError(
            f"Active component '{component}' is declared by responsibilities"
            f" {owning_ids} with conflicting lifecycle states {sorted(lifecycle_states)}."
            " Ownership is ambiguous; all owners must agree on lifecycle."
        )

    lifecycle = next(iter(lifecycle_states))
    if lifecycle in _INACTIVE_LIFECYCLE_STATES:
        owning_ids = sorted(resp_id for resp_id, _ in owners)
        raise InactiveLifecycleRuntimeAlignmentError(
            f"Active component '{component}' belongs to responsibility {owning_ids}"
            f" with lifecycle_state '{lifecycle}', which does not permit runtime activation."
        )


def _validate_implementation_lifecycle_alignment(
    impl: str,
    owners: list[tuple[str, str]],
) -> None:
    """Validate that a runtime active_implementation is safe to activate.

    Rules (evaluated over the full owner list, independent of catalog order):
    1. If owners have more than one distinct lifecycle_state → AmbiguousLifecycleOwnershipError.
    2. If the single distinct state is non-active → InactiveLifecycleRuntimeAlignmentError.

    Raises:
        AmbiguousLifecycleOwnershipError: owners disagree on lifecycle_state.
        InactiveLifecycleRuntimeAlignmentError: all owners share a non-active lifecycle_state.
    """
    lifecycle_states: set[str] = {lifecycle for _, lifecycle in owners}

    if len(lifecycle_states) > 1:
        owning_ids = sorted(resp_id for resp_id, _ in owners)
        raise AmbiguousLifecycleOwnershipError(
            f"Active implementation '{impl}' is declared by responsibilities"
            f" {owning_ids} with conflicting lifecycle states {sorted(lifecycle_states)}."
            " Ownership is ambiguous; all owners must agree on lifecycle."
        )

    lifecycle = next(iter(lifecycle_states))
    if lifecycle in _INACTIVE_LIFECYCLE_STATES:
        owning_ids = sorted(resp_id for resp_id, _ in owners)
        raise InactiveLifecycleRuntimeAlignmentError(
            f"Active implementation '{impl}' belongs to responsibility {owning_ids}"
            f" with lifecycle_state '{lifecycle}', which does not permit runtime activation."
        )


def validate_lifecycle_runtime_alignment(
    catalog_snapshot: CatalogSnapshot,
    runtime_state: dict[str, object],
) -> None:
    """Raise InactiveLifecycleRuntimeAlignmentError or AmbiguousLifecycleOwnershipError
    if runtime exposes any component or implementation with problematic lifecycle ownership.

    Ownership resolution:
    - Each component/implementation is mapped to ALL responsibilities that declare it
      (via allowed_components / allowed_implementations). The full owner list is evaluated,
      never collapsed by catalog order.

    Blocked states: experimental, deprecated, legacy.

    Ambiguity policy:
    - If a component or implementation is owned by responsibilities with more than one
      distinct lifecycle_state, ownership is ambiguous and AmbiguousLifecycleOwnershipError
      is raised regardless of whether the states include 'active' or not. This prevents
      catalog ordering from silently masking a non-active owner.

    Raises:
        InactiveLifecycleRuntimeAlignmentError: any owner has a non-active lifecycle.
        AmbiguousLifecycleOwnershipError: owners have conflicting lifecycle states.
    """
    component_owners = _build_component_lifecycle_owners(catalog_snapshot)
    impl_owners = _build_implementation_lifecycle_owners(catalog_snapshot)

    typed_state = cast(dict[str, Collection[object]], runtime_state)

    raw_components: list[str] = [
        str(item) for item in typed_state.get("active_components") or []
    ]
    for component in raw_components:
        owners = component_owners.get(component)
        if owners:
            _validate_component_lifecycle_alignment(component, owners)

    raw_implementations: list[str] = [
        str(item) for item in typed_state.get("active_implementations") or []
    ]
    for impl in raw_implementations:
        owners = impl_owners.get(impl)
        if owners:
            _validate_implementation_lifecycle_alignment(impl, owners)


def validate_runtime_contract(
    catalog_snapshot: CatalogSnapshot,
    runtime_state: dict[str, object],
) -> None:
    """Validate that the runtime state is consistent with the catalog snapshot.

    Validation order:
    1. Shape check — all recognized keys must be list, tuple, set, or frozenset.
    2. Active implementation alignment — every runtime active_implementation must match
       a declared active_implementation in the catalog.
    3. Lifecycle alignment — no component or implementation may belong to a non-active
       responsibility; conflicting multi-owner lifecycle raises AmbiguousLifecycleOwnershipError.
    4. Undeclared component check — active_components must be in allowed_components.
    5. Undeclared/duplicate implementation check — active_implementations must be in
       allowed_implementations and must not repeat per responsibility.
    6. Undeclared entrypoint check — public_entrypoints must be declared in the catalog.

    Raises:
        TypeError: any recognized key is not a list, tuple, set, or frozenset.
        UndeclaredActiveImplementationError: an active implementation does not match any
            declared active_implementation, or is not in any allowed_implementations.
        InactiveLifecycleRuntimeAlignmentError: a component or implementation belongs to
            a responsibility with a non-active lifecycle_state.
        AmbiguousLifecycleOwnershipError: a component or implementation is owned by
            responsibilities with conflicting lifecycle states.
        UndeclaredActiveComponentError: an active component is not declared in the catalog.
        DuplicateActiveImplementationError: an implementation appears more than once for
            the same responsibility.
        UndeclaredPublicEntrypointError: a public entrypoint is not declared in the catalog.
    """
    _assert_runtime_state_shape(runtime_state)
    validate_active_implementation_alignment(catalog_snapshot, runtime_state)
    validate_lifecycle_runtime_alignment(catalog_snapshot, runtime_state)

    typed_state = cast(dict[str, Collection[object]], runtime_state)

    # Extract raw active_implementations before normalization to preserve duplicates.
    raw_implementations: list[str] = [
        str(item) for item in typed_state.get("active_implementations") or []
    ]
    responsibility_by_id = {
        responsibility.responsibility_id: responsibility
        for responsibility in catalog_snapshot.responsibilities
    }
    impl_to_responsibilities = _build_impl_to_responsibilities(catalog_snapshot)

    for implementation in raw_implementations:
        if not implementation.startswith("src."):
            continue
        owning_responsibility_ids = impl_to_responsibilities.get(implementation, [])
        for owning_responsibility_id in owning_responsibility_ids:
            owning_responsibility = responsibility_by_id.get(owning_responsibility_id)
            if owning_responsibility is None:
                continue
            expected_prefix = _OWNER_LAYER_PREFIXES.get(owning_responsibility.owner_layer)
            if expected_prefix is None:
                continue
            if not implementation.startswith(expected_prefix):
                raise OwnerLayerRuntimeAlignmentError(
                    f"Active implementation '{implementation}' is owned by responsibility "
                    f"'{owning_responsibility.responsibility_id}' with owner_layer "
                    f"'{owning_responsibility.owner_layer}' but does not match expected "
                    f"namespace prefix '{expected_prefix}'."
                )

    normalized = normalize_runtime_state(typed_state)

    declared_components: set[str] = set()
    declared_implementations: set[str] = set()
    declared_entrypoints: set[str] = set()
    for responsibility in catalog_snapshot.responsibilities:
        declared_components.update(responsibility.allowed_components)
        declared_implementations.update(responsibility.allowed_implementations)
        declared_entrypoints.update(responsibility.public_entrypoints)

    for component in normalized["active_components"]:
        if component not in declared_components:
            raise UndeclaredActiveComponentError(
                f"Active component '{component}' is not declared in the catalog."
            )

    seen_per_responsibility: dict[str, set[str]] = {}
    for impl in raw_implementations:
        if impl not in declared_implementations:
            raise UndeclaredActiveImplementationError(
                f"Active implementation '{impl}' is not declared in the catalog."
            )
        for responsibility_id in impl_to_responsibilities.get(impl, []):
            bucket = seen_per_responsibility.setdefault(responsibility_id, set())
            if impl in bucket:
                raise DuplicateActiveImplementationError(
                    f"Implementation '{impl}' appears more than once"
                    f" for responsibility '{responsibility_id}'."
                )
            bucket.add(impl)

    for entrypoint in normalized["public_entrypoints"]:
        if entrypoint not in declared_entrypoints:
            raise UndeclaredPublicEntrypointError(
                f"Public entrypoint '{entrypoint}' is not declared in the catalog."
            )
