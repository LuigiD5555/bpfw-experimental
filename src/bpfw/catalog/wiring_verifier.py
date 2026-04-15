"""Wiring verifier: closes alignment between catalog declarations, runtime state, and wiring paths.

Complements runtime_contract.py (runtime → catalog direction) by enforcing the
catalog → runtime direction: every declared public entrypoint must be present at
runtime, every declared active_implementation must match the runtime observation,
and no undeclared lateral wiring path may pass silently.

Implementation ownership is resolved per-responsibility via allowed_implementations,
not via a flat active_implementation index. This prevents ambiguity when the same
implementation name appears in more than one responsibility's allowed_implementations.
"""

from bpfw.catalog.models import CatalogSnapshot
from bpfw.catalog.runtime_snapshot import RuntimeSnapshot


class UndeclaredRuntimeComponentError(Exception):
    """Raised when a runtime active component is not declared in any responsibility."""


class MissingDeclaredEntrypointError(Exception):
    """Raised when a declared public entrypoint is absent from the runtime snapshot."""


class UndeclaredRuntimeEntrypointError(Exception):
    """Raised when a runtime public entrypoint is not declared in the catalog."""


class UndeclaredWiringPathError(Exception):
    """Raised when a runtime active_implementation does not match the catalog active_implementation
    for its owning responsibility (lateral wiring path not declared)."""


class AmbiguousImplementationOwnershipError(Exception):
    """Raised when a runtime implementation is declared by more than one responsibility."""


def collect_declared_public_entrypoints(catalog_snapshot: CatalogSnapshot) -> set[str]:
    """Return all public_entrypoints declared across public responsibilities in the catalog."""
    entrypoints: set[str] = set()
    for responsibility in catalog_snapshot.responsibilities:
        if responsibility.is_public:
            entrypoints.update(responsibility.public_entrypoints)
    return entrypoints


def _collect_declared_components(catalog_snapshot: CatalogSnapshot) -> set[str]:
    declared: set[str] = set()
    for responsibility in catalog_snapshot.responsibilities:
        declared.update(responsibility.allowed_components)
    return declared


def _build_allowed_implementation_owners(
    catalog_snapshot: CatalogSnapshot,
) -> dict[str, list[str]]:
    """Return mapping: allowed_implementation → [responsibility_id, ...].

    Built from allowed_implementations (not active_implementation), so every
    permitted implementation is indexed, not only the currently active one.
    A value list longer than one means the implementation appears in multiple
    responsibilities — ambiguous ownership.
    """
    owners: dict[str, list[str]] = {}
    for responsibility in catalog_snapshot.responsibilities:
        for impl in responsibility.allowed_implementations:
            owners.setdefault(impl, []).append(responsibility.responsibility_id)
    return owners


def _verify_implementation_ownership(
    catalog_snapshot: CatalogSnapshot,
    runtime_snapshot: RuntimeSnapshot,
) -> None:
    """Verify each runtime active_implementation against per-responsibility ownership.

    Raises:
        UndeclaredWiringPathError: implementation not declared in any responsibility's
            allowed_implementations.
        AmbiguousImplementationOwnershipError: implementation declared in more than
            one responsibility's allowed_implementations.
        UndeclaredWiringPathError: implementation is allowed but does not match the
            owning responsibility's active_implementation (lateral wiring path).
    """
    ownership_index = _build_allowed_implementation_owners(catalog_snapshot)
    active_impl_by_responsibility: dict[str, str] = {
        responsibility.responsibility_id: responsibility.active_implementation
        for responsibility in catalog_snapshot.responsibilities
        if responsibility.active_implementation
    }

    seen_responsibilities: set[str] = set()

    for impl in runtime_snapshot.active_implementations:
        owning_ids = ownership_index.get(impl)

        if not owning_ids:
            raise UndeclaredWiringPathError(
                f"Runtime active implementation '{impl}' is not declared in any"
                " responsibility's allowed_implementations."
                " Undeclared lateral wiring path detected."
            )

        if len(owning_ids) > 1:
            raise AmbiguousImplementationOwnershipError(
                f"Runtime active implementation '{impl}' is declared by more than one"
                f" responsibility: {sorted(owning_ids)}."
                " Ownership is ambiguous; declare it in exactly one responsibility."
            )

        responsibility_id = owning_ids[0]

        if responsibility_id in seen_responsibilities:
            raise UndeclaredWiringPathError(
                f"Responsibility '{responsibility_id}' has more than one runtime"
                f" active implementation. Only one may be active at a time."
            )
        seen_responsibilities.add(responsibility_id)

        declared_active = active_impl_by_responsibility.get(responsibility_id, "")
        if impl != declared_active:
            raise UndeclaredWiringPathError(
                f"Runtime active implementation '{impl}' belongs to responsibility"
                f" '{responsibility_id}' but does not match its declared"
                f" active_implementation '{declared_active}'."
                " Undeclared lateral wiring path detected."
            )


def verify_catalog_runtime_alignment(
    catalog_snapshot: CatalogSnapshot,
    runtime_snapshot: RuntimeSnapshot,
) -> None:
    """Verify full bidirectional alignment between catalog declarations and runtime state.

    Checks (in order):

    1. Every runtime active_component is declared in at least one responsibility's
       allowed_components (UndeclaredRuntimeComponentError).

    2. Every declared public entrypoint from a public responsibility whose
       allowed_components are live in the runtime is present in the runtime snapshot
       (MissingDeclaredEntrypointError). Responsibilities with no live component are
       not checked — they represent a pre-bootstrap state.

    3. Every runtime public entrypoint is declared in the catalog
       (UndeclaredRuntimeEntrypointError).

    4. Every runtime active_implementation is owned unambiguously by exactly one
       responsibility (AmbiguousImplementationOwnershipError), belongs to its
       allowed_implementations (UndeclaredWiringPathError), no two implementations
       map to the same responsibility (UndeclaredWiringPathError), and matches that
       responsibility's active_implementation (UndeclaredWiringPathError).

    Lifecycle scope note: this verifier does not enforce lifecycle_state. Lifecycle gating
    (blocking activation for experimental, deprecated, and legacy states, including
    ambiguous multi-owner ownership) is handled by
    runtime_contract.validate_lifecycle_runtime_alignment.

    Raises:
        UndeclaredRuntimeComponentError
        MissingDeclaredEntrypointError
        UndeclaredRuntimeEntrypointError
        AmbiguousImplementationOwnershipError
        UndeclaredWiringPathError
    """
    declared_components = _collect_declared_components(catalog_snapshot)
    for component in runtime_snapshot.active_components:
        if component not in declared_components:
            raise UndeclaredRuntimeComponentError(
                f"Runtime active component '{component}' is not declared in the catalog."
            )

    runtime_components: set[str] = set(runtime_snapshot.active_components)
    runtime_entrypoints: set[str] = set(runtime_snapshot.public_entrypoints)

    # Only enforce entrypoint presence for responsibilities whose allowed_components
    # are live in the runtime. A responsibility with no live component is not yet
    # activated and its entrypoints are not expected to appear in the snapshot.
    live_declared_entrypoints: set[str] = set()
    for responsibility in catalog_snapshot.responsibilities:
        if not responsibility.is_public:
            continue
        if runtime_components.intersection(responsibility.allowed_components):
            live_declared_entrypoints.update(responsibility.public_entrypoints)

    for entrypoint in sorted(live_declared_entrypoints):
        if entrypoint not in runtime_entrypoints:
            raise MissingDeclaredEntrypointError(
                f"Declared public entrypoint '{entrypoint}' is missing from the runtime snapshot."
            )

    all_declared_entrypoints = collect_declared_public_entrypoints(catalog_snapshot)
    for entrypoint in runtime_snapshot.public_entrypoints:
        if entrypoint not in all_declared_entrypoints:
            raise UndeclaredRuntimeEntrypointError(
                f"Runtime public entrypoint '{entrypoint}' is not declared in the catalog."
            )

    _verify_implementation_ownership(catalog_snapshot, runtime_snapshot)
