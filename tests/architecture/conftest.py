"""Conftest — adds the repo root to sys.path so src/ and tools/ are importable."""

import sys
from pathlib import Path

# tests/architecture/ -> tests/ -> repo root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bpfw.catalog.models import CatalogSnapshot, ResponsibilityDefinition  # noqa: E402


def make_responsibility(
    responsibility_id: str,
    *,
    public_entrypoints: tuple[str, ...] = (),
    allowed_components: tuple[str, ...] = (),
    allowed_implementations: tuple[str, ...] = ("impl_placeholder",),
    forbidden_direct_instantiation: tuple[str, ...] = (),
    owner_layer: str = "domain",
    lifecycle_state: str = "active",
) -> ResponsibilityDefinition:
    """Build a ResponsibilityDefinition for use in architecture tests."""
    return ResponsibilityDefinition(
        responsibility_id=responsibility_id,
        canonical_name=responsibility_id,
        owner_layer=owner_layer,
        is_public=bool(public_entrypoints),
        official_port=None,
        public_entrypoints=public_entrypoints,
        allowed_components=allowed_components,
        allowed_implementations=allowed_implementations,
        active_implementation=allowed_implementations[0] if allowed_implementations else "",
        lifecycle_state=lifecycle_state,
        allowed_replacements=(),
        forbidden_direct_instantiation=forbidden_direct_instantiation,
    )


def make_snapshot(*responsibilities: ResponsibilityDefinition) -> CatalogSnapshot:
    """Build a CatalogSnapshot from the given responsibilities."""
    return CatalogSnapshot(responsibilities=tuple(responsibilities))
