"""Catalog validator: asserts internal consistency of classic and extended snapshots."""

from bpfw.catalog.models import (
    CatalogSchemaError,
    CatalogSnapshot,
    DuplicateEntrypointError,
    DuplicateResponsibilityError,
    ExtendedCatalogSnapshot,
)

VALID_LIFECYCLE_STATES: frozenset[str] = frozenset(
    {"active", "experimental", "deprecated", "legacy", "internal"}
)


def assert_unique_responsibility_ids(snapshot: CatalogSnapshot) -> None:
    seen: set[str] = set()
    for responsibility in snapshot.responsibilities:
        if responsibility.responsibility_id in seen:
            raise DuplicateResponsibilityError(
                f"Duplicate responsibility_id: '{responsibility.responsibility_id}'"
            )
        seen.add(responsibility.responsibility_id)


def assert_unique_public_entrypoints(snapshot: CatalogSnapshot) -> None:
    seen: dict[str, str] = {}
    for responsibility in snapshot.responsibilities:
        for entrypoint in responsibility.public_entrypoints:
            if entrypoint in seen:
                raise DuplicateEntrypointError(
                    f"Entrypoint '{entrypoint}' is claimed by both "
                    f"'{seen[entrypoint]}' and '{responsibility.responsibility_id}'"
                )
            seen[entrypoint] = responsibility.responsibility_id


def assert_required_fields_are_present(snapshot: CatalogSnapshot) -> None:
    for responsibility in snapshot.responsibilities:
        responsibility_id = responsibility.responsibility_id
        if not responsibility_id:
            raise CatalogSchemaError(
                f"ResponsibilityDefinition has an empty responsibility_id: {responsibility}"
            )
        if not responsibility.canonical_name:
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}' has an empty canonical_name"
            )
        if not responsibility.owner_layer:
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}' has an empty owner_layer"
            )
        if not responsibility.active_implementation:
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}' is missing active_implementation"
            )
        if responsibility.lifecycle_state not in VALID_LIFECYCLE_STATES:
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}' has invalid lifecycle_state "
                f"'{responsibility.lifecycle_state}'. "
                f"Allowed: {sorted(VALID_LIFECYCLE_STATES)}"
            )
        if responsibility.active_implementation not in responsibility.allowed_implementations:
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}': active_implementation "
                f"'{responsibility.active_implementation}' is not in allowed_implementations"
            )
        if responsibility.active_implementation in responsibility.allowed_replacements:
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}': active_implementation "
                f"'{responsibility.active_implementation}' must not appear in allowed_replacements"
            )
        if responsibility.is_public and not responsibility.public_entrypoints:
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}' is declared public but has no public_entrypoints"
            )


def assert_catalog_internal_consistency(snapshot: CatalogSnapshot) -> None:
    if not snapshot.responsibilities:
        raise CatalogSchemaError("CatalogSnapshot contains no responsibilities")
    for responsibility in snapshot.responsibilities:
        responsibility_id = responsibility.responsibility_id
        if not isinstance(responsibility.public_entrypoints, tuple):
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}': public_entrypoints must be a tuple"
            )
        if not isinstance(responsibility.allowed_components, tuple):
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}': allowed_components must be a tuple"
            )
        if not isinstance(responsibility.allowed_implementations, tuple):
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}': allowed_implementations must be a tuple"
            )
        if not isinstance(responsibility.forbidden_direct_instantiation, tuple):
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}': forbidden_direct_instantiation must be a tuple"
            )
        if not isinstance(responsibility.allowed_replacements, tuple):
            raise CatalogSchemaError(
                f"Responsibility '{responsibility_id}': allowed_replacements must be a tuple"
            )


def validate_catalog_snapshot(snapshot: CatalogSnapshot) -> None:
    assert_catalog_internal_consistency(snapshot)
    assert_required_fields_are_present(snapshot)
    assert_unique_responsibility_ids(snapshot)
    assert_unique_public_entrypoints(snapshot)


def _assert_unique_ids(values: tuple[object, ...], attr_name: str, label: str) -> None:
    seen: set[str] = set()
    for value in values:
        identifier = str(getattr(value, attr_name))
        if identifier in seen:
            raise CatalogSchemaError(f"Duplicate {label}: '{identifier}'")
        seen.add(identifier)


def assert_unique_policy_ids(snapshot: ExtendedCatalogSnapshot) -> None:
    _assert_unique_ids(snapshot.policies, "policy_id", "policy_id")


def assert_unique_contract_ids(snapshot: ExtendedCatalogSnapshot) -> None:
    _assert_unique_ids(snapshot.contracts, "contract_id", "contract_id")


def assert_unique_type_ids(snapshot: ExtendedCatalogSnapshot) -> None:
    _assert_unique_ids(snapshot.types, "type_id", "type_id")


def assert_unique_operation_ids(snapshot: ExtendedCatalogSnapshot) -> None:
    _assert_unique_ids(snapshot.operations, "operation_id", "operation_id")


def assert_unique_binding_ids(snapshot: ExtendedCatalogSnapshot) -> None:
    _assert_unique_ids(snapshot.bindings, "binding_id", "binding_id")


def assert_unique_interaction_ids(snapshot: ExtendedCatalogSnapshot) -> None:
    _assert_unique_ids(snapshot.interactions, "interaction_id", "interaction_id")


def assert_contracts_reference_existing_responsibilities(snapshot: ExtendedCatalogSnapshot) -> None:
    responsibility_ids = {responsibility.responsibility_id for responsibility in snapshot.responsibilities}
    for contract in snapshot.contracts:
        if contract.owner_responsibility not in responsibility_ids:
            raise CatalogSchemaError(
                f"Contract '{contract.contract_id}' references unknown responsibility "
                f"'{contract.owner_responsibility}'"
            )


def assert_operations_reference_existing_contracts(snapshot: ExtendedCatalogSnapshot) -> None:
    contract_ids = {contract.contract_id for contract in snapshot.contracts}
    for operation in snapshot.operations:
        if operation.contract_id not in contract_ids:
            raise CatalogSchemaError(
                f"Operation '{operation.operation_id}' references unknown contract "
                f"'{operation.contract_id}'"
            )


def assert_bindings_reference_existing_responsibilities_and_contracts(
    snapshot: ExtendedCatalogSnapshot,
) -> None:
    responsibility_ids = {responsibility.responsibility_id for responsibility in snapshot.responsibilities}
    contract_ids = {contract.contract_id for contract in snapshot.contracts}

    for binding in snapshot.bindings:
        if binding.responsibility_id not in responsibility_ids:
            raise CatalogSchemaError(
                f"Binding '{binding.binding_id}' references unknown responsibility "
                f"'{binding.responsibility_id}'"
            )
        if binding.contract_id not in contract_ids:
            raise CatalogSchemaError(
                f"Binding '{binding.binding_id}' references unknown contract '{binding.contract_id}'"
            )


def assert_interactions_reference_existing_contracts_operations_and_types(
    snapshot: ExtendedCatalogSnapshot,
) -> None:
    contract_ids = {contract.contract_id for contract in snapshot.contracts}
    operation_ids = {operation.operation_id for operation in snapshot.operations}
    type_ids = {type_definition.type_id for type_definition in snapshot.types}

    for interaction in snapshot.interactions:
        if interaction.entry_contract not in contract_ids:
            raise CatalogSchemaError(
                f"Interaction '{interaction.interaction_id}' references unknown contract "
                f"'{interaction.entry_contract}'"
            )
        if interaction.entry_operation not in operation_ids:
            raise CatalogSchemaError(
                f"Interaction '{interaction.interaction_id}' references unknown operation "
                f"'{interaction.entry_operation}'"
            )
        if interaction.output_type and interaction.output_type not in type_ids:
            raise CatalogSchemaError(
                f"Interaction '{interaction.interaction_id}' references unknown output type "
                f"'{interaction.output_type}'"
            )
        for step in interaction.steps:
            if step.uses_contract not in contract_ids:
                raise CatalogSchemaError(
                    f"Interaction '{interaction.interaction_id}' step '{step.step_id}' "
                    f"references unknown contract '{step.uses_contract}'"
                )
            if step.uses_operation not in operation_ids:
                raise CatalogSchemaError(
                    f"Interaction '{interaction.interaction_id}' step '{step.step_id}' "
                    f"references unknown operation '{step.uses_operation}'"
                )
            if step.produces_type and step.produces_type not in type_ids:
                raise CatalogSchemaError(
                    f"Interaction '{interaction.interaction_id}' step '{step.step_id}' "
                    f"references unknown type '{step.produces_type}'"
                )


def assert_operation_types_exist(snapshot: ExtendedCatalogSnapshot) -> None:
    type_ids = {type_definition.type_id for type_definition in snapshot.types}
    builtin_type_ids = {"string", "integer", "number", "boolean", "object", "array", "null"}
    all_known_type_ids = type_ids | builtin_type_ids

    for operation in snapshot.operations:
        if operation.input_type and operation.input_type not in all_known_type_ids:
            raise CatalogSchemaError(
                f"Operation '{operation.operation_id}' references unknown input type '{operation.input_type}'"
            )
        if operation.output_type and operation.output_type not in all_known_type_ids:
            raise CatalogSchemaError(
                f"Operation '{operation.operation_id}' references unknown output type '{operation.output_type}'"
            )
        for argument in operation.arguments:
            if argument.type_id not in all_known_type_ids:
                raise CatalogSchemaError(
                    f"Operation '{operation.operation_id}' argument '{argument.name}' "
                    f"references unknown type '{argument.type_id}'"
                )
        for result in operation.results:
            if result.type_id not in all_known_type_ids:
                raise CatalogSchemaError(
                    f"Operation '{operation.operation_id}' result '{result.result_id}' "
                    f"references unknown type '{result.type_id}'"
                )


def assert_blueprint_policies_exist_when_referenced(snapshot: ExtendedCatalogSnapshot) -> None:
    policy_ids = {policy.policy_id for policy in snapshot.policies}
    for contract in snapshot.contracts:
        if contract.blueprint_policy and contract.blueprint_policy not in policy_ids:
            raise CatalogSchemaError(
                f"Contract '{contract.contract_id}' references unknown blueprint policy "
                f"'{contract.blueprint_policy}'"
            )


def assert_contract_operation_links_are_consistent(snapshot: ExtendedCatalogSnapshot) -> None:
    operation_ids_by_contract: dict[str, set[str]] = {}
    for operation in snapshot.operations:
        operation_ids_by_contract.setdefault(operation.contract_id, set()).add(operation.operation_id)

    for contract in snapshot.contracts:
        declared_operations = set(contract.operations)
        existing_operations = operation_ids_by_contract.get(contract.contract_id, set())
        missing_operations = declared_operations - existing_operations
        if missing_operations:
            raise CatalogSchemaError(
                f"Contract '{contract.contract_id}' references missing operations: "
                f"{sorted(missing_operations)}"
            )


def assert_active_bindings_match_responsibility_active_implementation(
    snapshot: ExtendedCatalogSnapshot,
) -> None:
    active_implementation_by_responsibility = {
        responsibility.responsibility_id: responsibility.active_implementation
        for responsibility in snapshot.responsibilities
    }

    for binding in snapshot.bindings:
        if binding.status != "active":
            continue
        expected_implementation = active_implementation_by_responsibility.get(binding.responsibility_id)
        if expected_implementation is None:
            continue
        if binding.implementation != expected_implementation:
            raise CatalogSchemaError(
                f"Active binding '{binding.binding_id}' implementation '{binding.implementation}' "
                f"does not match active_implementation '{expected_implementation}' for "
                f"responsibility '{binding.responsibility_id}'"
            )


def validate_blueprint_constraints(snapshot: ExtendedCatalogSnapshot) -> None:
    contracts_by_id = {contract.contract_id: contract for contract in snapshot.contracts}
    policies_by_id = {policy.policy_id: policy for policy in snapshot.policies}
    operations_by_contract: dict[str, list[object]] = {}

    for operation in snapshot.operations:
        operations_by_contract.setdefault(operation.contract_id, []).append(operation)

    for contract in snapshot.contracts:
        if not contract.blueprint_policy:
            continue
        policy = policies_by_id.get(contract.blueprint_policy)
        if policy is None or not policy.enabled:
            continue

        contract_operations = operations_by_contract.get(contract.contract_id, [])

        if policy.require_declared_operations and not contract.operations:
            raise CatalogSchemaError(
                f"Blueprint policy for contract '{contract.contract_id}' requires declared operations"
            )

        if not contract_operations:
            raise CatalogSchemaError(
                f"Contract '{contract.contract_id}' has blueprint enabled but no operation definitions"
            )

        for operation in contract_operations:
            if policy.require_declared_outputs and not (
                operation.output_type or operation.results
            ):
                raise CatalogSchemaError(
                    f"Operation '{operation.operation_id}' must declare output_type or results"
                )

            if policy.require_declared_inputs and not (
                operation.input_type or operation.arguments
            ):
                raise CatalogSchemaError(
                    f"Operation '{operation.operation_id}' must declare input_type or arguments"
                )

            if policy.forbid_undeclared_results and not operation.results:
                raise CatalogSchemaError(
                    f"Operation '{operation.operation_id}' must declare explicit results"
                )

    for contract in snapshot.contracts:
        if not contract.blueprint_policy:
            continue
        policy = policies_by_id.get(contract.blueprint_policy)
        if policy is None or not policy.enabled or not policy.forbid_undeclared_dependencies:
            continue

        allowed_contract_ids = {contract.contract_id}
        for interaction in snapshot.interactions:
            if interaction.entry_contract != contract.contract_id:
                continue
            for step in interaction.steps:
                if step.uses_contract not in allowed_contract_ids:
                    raise CatalogSchemaError(
                        f"Interaction '{interaction.interaction_id}' step '{step.step_id}' uses "
                        f"undeclared contract '{step.uses_contract}' under forbid_undeclared_dependencies"
                    )


def validate_extended_catalog_snapshot(snapshot: ExtendedCatalogSnapshot) -> None:
    validate_catalog_snapshot(CatalogSnapshot(responsibilities=snapshot.responsibilities))

    assert_unique_policy_ids(snapshot)
    assert_unique_contract_ids(snapshot)
    assert_unique_type_ids(snapshot)
    assert_unique_operation_ids(snapshot)
    assert_unique_binding_ids(snapshot)
    assert_unique_interaction_ids(snapshot)

    assert_contracts_reference_existing_responsibilities(snapshot)
    assert_operations_reference_existing_contracts(snapshot)
    assert_bindings_reference_existing_responsibilities_and_contracts(snapshot)
    assert_interactions_reference_existing_contracts_operations_and_types(snapshot)
    assert_operation_types_exist(snapshot)
    assert_blueprint_policies_exist_when_referenced(snapshot)
    assert_contract_operation_links_are_consistent(snapshot)
    assert_active_bindings_match_responsibility_active_implementation(snapshot)

    validate_blueprint_constraints(snapshot)
