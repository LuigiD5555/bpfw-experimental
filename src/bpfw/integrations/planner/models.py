"""Data models for the Planner integration."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Human-readable labels for relationship types
RELATIONSHIP_LABELS = {
    "produces_input_for": "sends output to",
    "calls": "uses",
    "validates": "validates",
    "transforms": "transforms",
    "exports": "exports to",
    "replaces": "replaces",
    "uses": "uses",
    "depends_on": "depends on",
}

# Reverse mapping from label to internal relationship
RELATIONSHIP_FROM_LABEL = {v: k for k, v in RELATIONSHIP_LABELS.items()}

# List of valid relationship types (internal names)
VALID_RELATIONSHIPS = list(RELATIONSHIP_LABELS.keys())


@dataclass
class PlannerSecurityConfig:
    """Security configuration for the project."""
    
    no_secrets_in_blueprint: bool = True
    public_safe_mode: bool = True
    detected_detail_level: str = "minimal"


@dataclass
class PlannerProjectConfig:
    """Global project configuration."""
    
    project_id: str
    project_name: str
    root: str = "."
    language: str = "python"
    source_roots: List[str] = field(default_factory=lambda: ["src"])
    ignored_paths: List[str] = field(default_factory=lambda: [
        ".git", ".venv", "venv", "__pycache__", "node_modules", "tests", "migrations"
    ])
    policy_mode: str = "catalog"
    empty_blueprint_allows_execution: bool = True
    defined_blueprint_blocks_on_drift: bool = True
    allowed_lifecycles: List[str] = field(default_factory=lambda: [
        "active", "experimental", "legacy", "deprecated"
    ])
    single_active_per_intent: bool = True
    undeclared_code_blocks: bool = True
    missing_declared_code_blocks: bool = True
    security: PlannerSecurityConfig = field(default_factory=PlannerSecurityConfig)


@dataclass
class PlannerInterfaceInput:
    """Input parameter for a responsibility interface."""
    
    name: str
    type: Optional[str] = None
    default: Any = None
    required: bool = True
    description: Optional[str] = None


@dataclass
class PlannerInterfaceOutput:
    """Output specification for a responsibility interface."""
    
    type: Optional[str] = None
    description: Optional[str] = None


@dataclass
class PlannerInterface:
    """Interface specification for a responsibility."""
    
    inputs: List[PlannerInterfaceInput] = field(default_factory=list)
    output: Optional[PlannerInterfaceOutput] = None


@dataclass
class PlannerBox:
    """Black box representing a system responsibility."""
    
    name: str
    domain: str
    intent: str
    symbol_type: str
    lifecycle: str = "active"
    path: Optional[str] = None
    symbol: Optional[str] = None
    interface: Optional[PlannerInterface] = None
    notes: Optional[str] = None
    
    # Derived fields (computed, not set by user)
    id: str = field(init=False)
    module: Optional[str] = field(init=False)
    qualified_name: Optional[str] = field(init=False)
    duplicate_group: Optional[str] = field(init=False)
    
    def __post_init__(self) -> None:
        """Compute derived fields after initialization."""
        from bpfw.integrations.planner.utils import (
            generate_box_id,
            generate_module_from_path,
            generate_qualified_name,
            normalize_intent_for_duplicate_group,
        )
        
        self.id = generate_box_id(self.domain, self.name)
        
        if self.path:
            self.module = generate_module_from_path(self.path)
        else:
            self.module = None
        
        if self.symbol and self.module:
            self.qualified_name = generate_qualified_name(self.module, self.symbol)
        else:
            self.qualified_name = None
        
        self.duplicate_group = normalize_intent_for_duplicate_group(self.intent)


@dataclass
class PlannerConnection:
    """Connection between two responsibilities."""
    
    source_box_id: str
    target_box_id: str
    relationship: str
    source_kind: str = "blueprint"
    confidence: str = "high"
    evidence: List[str] = field(default_factory=list)
    status: str = "accepted"
    notes: Optional[str] = None


@dataclass
class PlannerState:
    """Complete state of the planner session."""
    
    project_config: PlannerProjectConfig
    boxes: List[PlannerBox] = field(default_factory=list)
    connections: List[PlannerConnection] = field(default_factory=list)
    selected_box_id: Optional[str] = None
    selected_connection_id: Optional[int] = None
    flow_source_filter: str = "all"
    flow_confidence_filter: str = "all"
    dirty: bool = False
    blueprint_path: Path = field(default_factory=lambda: Path("bpfw/blueprint.yaml"))
    source_mode: str = "new_plan"
    
    # Screen state for UI navigation
    screen: str = "welcome"
    
    # Change tracking for unsaved changes dialog
    boxes_added: int = 0
    boxes_edited: int = 0
    boxes_deleted: int = 0
    connections_added: int = 0
    connections_removed: int = 0
    
    # Broken connections (orphan references in YAML)
    broken_connections: List[PlannerConnection] = field(default_factory=list)
