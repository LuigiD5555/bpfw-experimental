"""Schema constants for minimum executable Blueprint model."""

from __future__ import annotations

REQUIRED_ROOT_FIELDS: tuple[str, ...] = (
    "version",
    "responsibilities",
)

REQUIRED_RESPONSIBILITY_FIELDS: tuple[str, ...] = (
    "responsibility_id",
    "canonical_name",
    "owner_layer",
    "lifecycle_state",
    "allowed_files",
    "allowed_implementations",
    "active_implementation",
)

REQUIRED_IMPLEMENTATION_FIELDS: tuple[str, ...] = (
    "implementation_id",
    "class_name",
    "file",
    "lifecycle_state",
)

REQUIRED_LOCKED_RESOURCE_FIELDS: tuple[str, ...] = (
    "resource_id",
    "path",
    "mutability",
    "owner",
)

BLUEPRINT_FILE_NAME = "blueprint.yaml"
