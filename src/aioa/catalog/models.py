from dataclasses import dataclass


class CatalogSchemaError(Exception):
    """Raised when a catalog payload fails schema validation."""


class DuplicateResponsibilityError(CatalogSchemaError):
    """Raised when two responsibilities share the same responsibility_id."""


class DuplicateEntrypointError(CatalogSchemaError):
    """Raised when two responsibilities share a public entrypoint."""


@dataclass(frozen=True)
class ResponsibilityDefinition:
    responsibility_id: str
    canonical_name: str
    owner_layer: str
    is_public: bool
    official_port: str | None
    public_entrypoints: tuple[str, ...]
    allowed_components: tuple[str, ...]
    allowed_implementations: tuple[str, ...]
    active_implementation: str
    lifecycle_state: str
    allowed_replacements: tuple[str, ...]
    forbidden_direct_instantiation: tuple[str, ...]
    blueprint_enabled: bool = False


@dataclass(frozen=True)
class CatalogSnapshot:
    responsibilities: tuple[ResponsibilityDefinition, ...]


@dataclass(frozen=True)
class BlueprintPolicyDefinition:
    policy_id: str
    enabled: bool
    strictness: str
    require_declared_operations: bool
    require_declared_inputs: bool
    require_declared_outputs: bool
    forbid_undeclared_results: bool
    forbid_undeclared_dependencies: bool


@dataclass(frozen=True)
class ContractDefinition:
    contract_id: str
    kind: str
    owner_responsibility: str
    visibility: str
    operations: tuple[str, ...]
    blueprint_policy: str | None


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    type_id: str
    required: bool
    default_value: object | None


@dataclass(frozen=True)
class TypeDefinition:
    type_id: str
    kind: str
    version: int
    fields: tuple[FieldDefinition, ...]
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class ArgumentDefinition:
    name: str
    type_id: str
    required: bool
    default_value: object | None


@dataclass(frozen=True)
class OperationResultDefinition:
    result_id: str
    type_id: str


@dataclass(frozen=True)
class OperationDefinition:
    operation_id: str
    contract_id: str
    mode: str
    arguments: tuple[ArgumentDefinition, ...]
    input_type: str | None
    output_type: str | None
    results: tuple[OperationResultDefinition, ...]
    raises: tuple[str, ...]
    side_effects: tuple[str, ...]
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]


@dataclass(frozen=True)
class BindingDefinition:
    binding_id: str
    responsibility_id: str
    contract_id: str
    implementation: str
    status: str
    composition_root: str


@dataclass(frozen=True)
class InteractionStepDefinition:
    step_id: str
    uses_contract: str
    uses_operation: str
    produces_type: str | None


@dataclass(frozen=True)
class InteractionDefinition:
    interaction_id: str
    entry_contract: str
    entry_operation: str
    output_type: str | None
    steps: tuple[InteractionStepDefinition, ...]


@dataclass(frozen=True)
class ExtendedCatalogSnapshot:
    responsibilities: tuple[ResponsibilityDefinition, ...]
    policies: tuple[BlueprintPolicyDefinition, ...]
    contracts: tuple[ContractDefinition, ...]
    types: tuple[TypeDefinition, ...]
    operations: tuple[OperationDefinition, ...]
    bindings: tuple[BindingDefinition, ...]
    interactions: tuple[InteractionDefinition, ...]
