"""Schema constants for blueprint_mode opt-in validation."""

from __future__ import annotations

BLUEPRINT_MODE_KEY = "blueprint_mode"
BLUEPRINT_MODE_ENABLED_KEY = "enabled"
BLUEPRINT_MODE_OPERATIONS_KEY = "operations"

OPERATION_ID_KEY = "operation_id"
OPERATION_CALLABLE_KEY = "callable"
OPERATION_OUTPUT_CONTRACT_KEY = "output_contract"
OPERATION_INPUT_CONTRACT_KEY = "input_contract"
OPERATION_ALLOWED_ERRORS_KEY = "allowed_errors"
OPERATION_SIDE_EFFECTS_KEY = "side_effects"

SIDE_EFFECTS_FORBIDDEN_KEY = "forbidden"
SIDE_EFFECTS_ALLOWED_KEY = "allowed"
