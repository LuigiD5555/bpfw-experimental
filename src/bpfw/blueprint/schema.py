"""Schema constants and canonical paths for BPFW MVP Catalog Mode."""

CANONICAL_BLUEPRINT_FILE = "bpfw/blueprint.yaml"
LEGACY_BLUEPRINT_FILE = "blueprint.yaml"

REQUIRED_ROOT_FIELDS = (
    "version",
    "responsibilities",
)

REQUIRED_RESPONSIBILITY_FIELDS = (
    "responsibility_id",
    "canonical_name",
    "owner_layer",
    "lifecycle_state",
    "allowed_files",
    "allowed_implementations",
    "active_implementation",
)

REQUIRED_IMPLEMENTATION_FIELDS = (
    "implementation_id",
    "class_name",
    "file",
    "lifecycle_state",
)

REQUIRED_LOCKED_RESOURCE_FIELDS = (
    "resource_id",
    "path",
    "mutability",
    "owner",
)

BLUEPRINT_FILE_NAME = CANONICAL_BLUEPRINT_FILE
