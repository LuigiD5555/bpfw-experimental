"""Catalog loader for classic and blueprint-extended catalog snapshots."""

import yaml

from bpfw.catalog.catalog_paths import (
    list_binding_yaml_files,
    list_catalog_yaml_files,
    list_contract_yaml_files,
    list_interaction_yaml_files,
    list_operation_yaml_files,
    list_policy_yaml_files,
    list_type_yaml_files,
)
from bpfw.catalog.access_control import assert_catalog_unlocked
from bpfw.catalog.models import (
    ArgumentDefinition,
    BindingDefinition,
    BlueprintPolicyDefinition,
    CatalogSnapshot,
    ContractDefinition,
    ExtendedCatalogSnapshot,
    FieldDefinition,
    InteractionDefinition,
    InteractionStepDefinition,
    OperationDefinition,
    OperationResultDefinition,
    ResponsibilityDefinition,
    TypeDefinition,
)
from bpfw.catalog.schema import (
    validate_raw_binding_documents,
    validate_raw_catalog_documents,
    validate_raw_contract_documents,
    validate_raw_interaction_documents,
    validate_raw_operation_documents,
    validate_raw_policy_documents,
    validate_raw_type_documents,
)


def _load_yaml_documents(yaml_files: list[object]) -> list[dict[str, object]]:
    documents: list[dict[str, object]] = []
    for yaml_file in yaml_files:
        with yaml_file.open(encoding="utf-8") as file_handle:  # type: ignore[attr-defined]
            raw = yaml.safe_load(file_handle)
        if raw is None:
            continue
        documents.append(raw)
    return documents


def load_catalog_documents() -> list[dict[str, object]]:
    assert_catalog_unlocked()
    documents = _load_yaml_documents(list_catalog_yaml_files())
    validate_raw_catalog_documents(documents)
    return documents


def load_policy_documents() -> list[dict[str, object]]:
    assert_catalog_unlocked()
    documents = _load_yaml_documents(list_policy_yaml_files())
    validate_raw_policy_documents(documents)
    return documents


def load_contract_documents() -> list[dict[str, object]]:
    assert_catalog_unlocked()
    documents = _load_yaml_documents(list_contract_yaml_files())
    validate_raw_contract_documents(documents)
    return documents


def load_type_documents() -> list[dict[str, object]]:
    assert_catalog_unlocked()
    documents = _load_yaml_documents(list_type_yaml_files())
    validate_raw_type_documents(documents)
    return documents


def load_operation_documents() -> list[dict[str, object]]:
    assert_catalog_unlocked()
    documents = _load_yaml_documents(list_operation_yaml_files())
    validate_raw_operation_documents(documents)
    return documents


def load_binding_documents() -> list[dict[str, object]]:
    assert_catalog_unlocked()
    documents = _load_yaml_documents(list_binding_yaml_files())
    validate_raw_binding_documents(documents)
    return documents


def load_interaction_documents() -> list[dict[str, object]]:
    assert_catalog_unlocked()
    documents = _load_yaml_documents(list_interaction_yaml_files())
    validate_raw_interaction_documents(documents)
    return documents


def load_catalog_snapshot() -> CatalogSnapshot:
    documents = load_catalog_documents()
    responsibilities = tuple(
        ResponsibilityDefinition(
            responsibility_id=str(document["responsibility_id"]),
            canonical_name=str(document["canonical_name"]),
            owner_layer=str(document["owner_layer"]),
            is_public=bool(document["is_public"]),
            official_port=str(document["official_port"]) if document["official_port"] else None,
            public_entrypoints=tuple(document["public_entrypoints"]),  # type: ignore[arg-type]
            allowed_components=tuple(document["allowed_components"]),  # type: ignore[arg-type]
            allowed_implementations=(
                tuple(document["allowed_implementations"])  # type: ignore[arg-type]
            ),
            active_implementation=str(document["active_implementation"]),
            lifecycle_state=str(document["lifecycle_state"]),
            allowed_replacements=tuple(document["allowed_replacements"]),  # type: ignore[arg-type]
            forbidden_direct_instantiation=(
                tuple(document["forbidden_direct_instantiation"])  # type: ignore[arg-type]
            ),
            blueprint_enabled=bool(document.get("blueprint_enabled", False)),
        )
        for document in documents
    )
    return CatalogSnapshot(responsibilities=responsibilities)


def load_policy_definitions() -> tuple[BlueprintPolicyDefinition, ...]:
    return tuple(
        BlueprintPolicyDefinition(
            policy_id=str(document["policy_id"]),
            enabled=bool(document["enabled"]),
            strictness=str(document["strictness"]),
            require_declared_operations=bool(document["require_declared_operations"]),
            require_declared_inputs=bool(document["require_declared_inputs"]),
            require_declared_outputs=bool(document["require_declared_outputs"]),
            forbid_undeclared_results=bool(document["forbid_undeclared_results"]),
            forbid_undeclared_dependencies=bool(document["forbid_undeclared_dependencies"]),
        )
        for document in load_policy_documents()
    )


def load_contract_definitions() -> tuple[ContractDefinition, ...]:
    return tuple(
        ContractDefinition(
            contract_id=str(document["contract_id"]),
            kind=str(document["kind"]),
            owner_responsibility=str(document["owner_responsibility"]),
            visibility=str(document["visibility"]),
            operations=tuple(document["operations"]),  # type: ignore[arg-type]
            blueprint_policy=(
                str(document["blueprint_policy"])
                if document.get("blueprint_policy")
                else None
            ),
        )
        for document in load_contract_documents()
    )


def _load_field_definitions(raw_fields: list[dict[str, object]]) -> tuple[FieldDefinition, ...]:
    return tuple(
        FieldDefinition(
            name=str(field["name"]),
            type_id=str(field["type_id"]),
            required=bool(field["required"]),
            default_value=field.get("default_value"),
        )
        for field in raw_fields
    )


def load_type_definitions() -> tuple[TypeDefinition, ...]:
    return tuple(
        TypeDefinition(
            type_id=str(document["type_id"]),
            kind=str(document["kind"]),
            version=int(document["version"]),
            fields=_load_field_definitions(document["fields"]),  # type: ignore[arg-type]
            capabilities=tuple(document["capabilities"]),  # type: ignore[arg-type]
        )
        for document in load_type_documents()
    )


def _load_argument_definitions(raw_arguments: list[dict[str, object]]) -> tuple[ArgumentDefinition, ...]:
    return tuple(
        ArgumentDefinition(
            name=str(argument["name"]),
            type_id=str(argument["type_id"]),
            required=bool(argument["required"]),
            default_value=argument.get("default_value"),
        )
        for argument in raw_arguments
    )


def _load_result_definitions(raw_results: dict[str, object]) -> tuple[OperationResultDefinition, ...]:
    return tuple(
        OperationResultDefinition(result_id=str(result_id), type_id=str(type_id))
        for result_id, type_id in raw_results.items()
    )


def load_operation_definitions() -> tuple[OperationDefinition, ...]:
    return tuple(
        OperationDefinition(
            operation_id=str(document["operation_id"]),
            contract_id=str(document["contract_id"]),
            mode=str(document["mode"]),
            arguments=_load_argument_definitions(document["arguments"]),  # type: ignore[arg-type]
            input_type=str(document["input"]) if document.get("input") else None,
            output_type=str(document["output"]) if document.get("output") else None,
            results=_load_result_definitions(document["results"]),  # type: ignore[arg-type]
            raises=tuple(document["raises"]),  # type: ignore[arg-type]
            side_effects=tuple(document["side_effects"]),  # type: ignore[arg-type]
            preconditions=tuple(document["preconditions"]),  # type: ignore[arg-type]
            postconditions=tuple(document["postconditions"]),  # type: ignore[arg-type]
        )
        for document in load_operation_documents()
    )


def load_binding_definitions() -> tuple[BindingDefinition, ...]:
    return tuple(
        BindingDefinition(
            binding_id=str(document["binding_id"]),
            responsibility_id=str(document["responsibility_id"]),
            contract_id=str(document["contract_id"]),
            implementation=str(document["implementation"]),
            status=str(document["status"]),
            composition_root=str(document["composition_root"]),
        )
        for document in load_binding_documents()
    )


def _load_interaction_step_definitions(
    raw_steps: list[dict[str, object]],
) -> tuple[InteractionStepDefinition, ...]:
    return tuple(
        InteractionStepDefinition(
            step_id=str(step["step_id"]),
            uses_contract=str(step["uses_contract"]),
            uses_operation=str(step["uses_operation"]),
            produces_type=str(step["produces_type"]) if step.get("produces_type") else None,
        )
        for step in raw_steps
    )


def load_interaction_definitions() -> tuple[InteractionDefinition, ...]:
    return tuple(
        InteractionDefinition(
            interaction_id=str(document["interaction_id"]),
            entry_contract=str(document["entry_contract"]),
            entry_operation=str(document["entry_operation"]),
            output_type=str(document["output"]) if document.get("output") else None,
            steps=_load_interaction_step_definitions(document["steps"]),  # type: ignore[arg-type]
        )
        for document in load_interaction_documents()
    )


def load_extended_catalog_snapshot() -> ExtendedCatalogSnapshot:
    classic_snapshot = load_catalog_snapshot()
    policies = load_policy_definitions()
    contracts = load_contract_definitions()
    types = load_type_definitions()
    operations = load_operation_definitions()
    bindings = load_binding_definitions()
    interactions = load_interaction_definitions()
    return ExtendedCatalogSnapshot(
        responsibilities=classic_snapshot.responsibilities,
        policies=policies,
        contracts=contracts,
        types=types,
        operations=operations,
        bindings=bindings,
        interactions=interactions,
    )
