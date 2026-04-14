from bpfw.catalog.models import CatalogSchemaError


REQUIRED_RESPONSIBILITY_KEYS: set[str] = {
    "responsibility_id",
    "canonical_name",
    "owner_layer",
    "is_public",
    "official_port",
    "public_entrypoints",
    "allowed_components",
    "allowed_implementations",
    "active_implementation",
    "lifecycle_state",
    "allowed_replacements",
    "forbidden_direct_instantiation",
}

REQUIRED_POLICY_KEYS: set[str] = {
    "policy_id",
    "enabled",
    "strictness",
    "require_declared_operations",
    "require_declared_inputs",
    "require_declared_outputs",
    "forbid_undeclared_results",
    "forbid_undeclared_dependencies",
}

REQUIRED_CONTRACT_KEYS: set[str] = {
    "contract_id",
    "kind",
    "owner_responsibility",
    "visibility",
    "operations",
    "blueprint_policy",
}

REQUIRED_TYPE_KEYS: set[str] = {
    "type_id",
    "kind",
    "version",
    "fields",
    "capabilities",
}

REQUIRED_OPERATION_KEYS: set[str] = {
    "operation_id",
    "contract_id",
    "mode",
    "arguments",
    "input",
    "output",
    "results",
    "raises",
    "side_effects",
    "preconditions",
    "postconditions",
}

REQUIRED_BINDING_KEYS: set[str] = {
    "binding_id",
    "responsibility_id",
    "contract_id",
    "implementation",
    "status",
    "composition_root",
}

REQUIRED_INTERACTION_KEYS: set[str] = {
    "interaction_id",
    "entry_contract",
    "entry_operation",
    "output",
    "steps",
}


def _assert_required_keys(payload: dict[str, object], required_keys: set[str], payload_name: str) -> None:
    missing = required_keys - payload.keys()
    if missing:
        raise CatalogSchemaError(
            f"{payload_name} payload is missing required keys: {sorted(missing)}"
        )


def validate_raw_responsibility_payload(payload: dict[str, object]) -> None:
    _assert_required_keys(payload, REQUIRED_RESPONSIBILITY_KEYS, "Responsibility")

    active_implementation = payload.get("active_implementation")
    if not active_implementation:
        raise CatalogSchemaError("active_implementation is required and cannot be empty.")

    lifecycle_state = payload.get("lifecycle_state")
    allowed_lifecycle_states = {"active", "experimental", "deprecated", "legacy", "internal"}
    if lifecycle_state not in allowed_lifecycle_states:
        raise CatalogSchemaError(
            f"lifecycle_state '{lifecycle_state}' is not valid. "
            f"Allowed values: {sorted(allowed_lifecycle_states)}"
        )


def validate_raw_policy_payload(payload: dict[str, object]) -> None:
    _assert_required_keys(payload, REQUIRED_POLICY_KEYS, "Policy")

    strictness = payload.get("strictness")
    allowed_strictness = {"low", "medium", "high"}
    if strictness not in allowed_strictness:
        raise CatalogSchemaError(
            f"strictness '{strictness}' is not valid. Allowed values: {sorted(allowed_strictness)}"
        )


def validate_raw_contract_payload(payload: dict[str, object]) -> None:
    _assert_required_keys(payload, REQUIRED_CONTRACT_KEYS, "Contract")

    visibility = payload.get("visibility")
    allowed_visibility = {"public", "internal", "private"}
    if visibility not in allowed_visibility:
        raise CatalogSchemaError(
            f"visibility '{visibility}' is not valid. Allowed values: {sorted(allowed_visibility)}"
        )
    if not isinstance(payload.get("operations"), list):
        raise CatalogSchemaError("operations must be a list")


def validate_raw_type_payload(payload: dict[str, object]) -> None:
    _assert_required_keys(payload, REQUIRED_TYPE_KEYS, "Type")

    kind = payload.get("kind")
    allowed_type_kinds = {"object", "opaque", "enum", "list", "map", "union"}
    if kind not in allowed_type_kinds:
        raise CatalogSchemaError(
            f"kind '{kind}' is not valid. Allowed values: {sorted(allowed_type_kinds)}"
        )

    fields = payload.get("fields")
    if not isinstance(fields, list):
        raise CatalogSchemaError("fields must be a list")


def validate_raw_operation_payload(payload: dict[str, object]) -> None:
    _assert_required_keys(payload, REQUIRED_OPERATION_KEYS, "Operation")

    mode = payload.get("mode")
    allowed_modes = {"normal", "blueprint_optional", "blueprint_required"}
    if mode not in allowed_modes:
        raise CatalogSchemaError(
            f"mode '{mode}' is not valid. Allowed values: {sorted(allowed_modes)}"
        )

    arguments = payload.get("arguments")
    if not isinstance(arguments, list):
        raise CatalogSchemaError("arguments must be a list")

    results = payload.get("results")
    if not isinstance(results, dict):
        raise CatalogSchemaError("results must be a mapping")

    input_value = payload.get("input")
    output_value = payload.get("output")
    if input_value is not None and not isinstance(input_value, str):
        raise CatalogSchemaError("input must be a string or null")
    if output_value is not None and not isinstance(output_value, str):
        raise CatalogSchemaError("output must be a string or null")

    has_output = bool(output_value)
    has_results = bool(results)
    if not has_output and not has_results:
        raise CatalogSchemaError("at least one of output or results must be declared")


def validate_raw_binding_payload(payload: dict[str, object]) -> None:
    _assert_required_keys(payload, REQUIRED_BINDING_KEYS, "Binding")

    status = payload.get("status")
    allowed_statuses = {"active", "experimental", "deprecated", "legacy", "internal"}
    if status not in allowed_statuses:
        raise CatalogSchemaError(
            f"status '{status}' is not valid. Allowed values: {sorted(allowed_statuses)}"
        )


def validate_raw_interaction_payload(payload: dict[str, object]) -> None:
    _assert_required_keys(payload, REQUIRED_INTERACTION_KEYS, "Interaction")

    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise CatalogSchemaError("steps must be a non-empty list")


def _validate_documents(
    documents: list[dict[str, object]],
    validator_function: object,
    label: str,
) -> None:
    for index, document in enumerate(documents):
        try:
            validator_function(document)  # type: ignore[misc]
        except CatalogSchemaError as error:
            raise CatalogSchemaError(
                f"{label} document at index {index} failed validation: {error}"
            ) from error


def validate_raw_catalog_documents(documents: list[dict[str, object]]) -> None:
    _validate_documents(documents, validate_raw_responsibility_payload, "Responsibility")


def validate_raw_policy_documents(documents: list[dict[str, object]]) -> None:
    _validate_documents(documents, validate_raw_policy_payload, "Policy")


def validate_raw_contract_documents(documents: list[dict[str, object]]) -> None:
    _validate_documents(documents, validate_raw_contract_payload, "Contract")


def validate_raw_type_documents(documents: list[dict[str, object]]) -> None:
    _validate_documents(documents, validate_raw_type_payload, "Type")


def validate_raw_operation_documents(documents: list[dict[str, object]]) -> None:
    _validate_documents(documents, validate_raw_operation_payload, "Operation")


def validate_raw_binding_documents(documents: list[dict[str, object]]) -> None:
    _validate_documents(documents, validate_raw_binding_payload, "Binding")


def validate_raw_interaction_documents(documents: list[dict[str, object]]) -> None:
    _validate_documents(documents, validate_raw_interaction_payload, "Interaction")
