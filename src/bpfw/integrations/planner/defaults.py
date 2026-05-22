"""Default builders for Planner integration."""

from dataclasses import dataclass
from typing import List, Optional

from bpfw.core.catalog.symbol_types import VALID_SYMBOL_TYPES
from bpfw.integrations.planner.models import (
    PlannerBox,
    PlannerInterface,
    PlannerProjectConfig,
    PlannerState,
)
from bpfw.integrations.planner.utils import (
    generate_box_path,
    generate_box_symbol,
    get_project_defaults,
    to_snake_case,
)

@dataclass
class AddBoxInput:
    """Input data for adding a new box."""
    
    name: str
    domain: str
    purpose: str
    symbol_type: str
    lifecycle: Optional[str] = None


class PlannerDefaultsBuilder:
    """Generate intelligent defaults for planner elements."""
    
    @staticmethod
    def build_project_defaults(project_root_path) -> PlannerProjectConfig:
        """Build default project configuration.
        
        Args:
            project_root_path: Path to project root.
        
        Returns:
            PlannerProjectConfig with intelligent defaults.
        """
        from pathlib import Path
        
        project_root = Path(project_root_path)
        defaults = get_project_defaults(project_root)
        
        return PlannerProjectConfig(
            project_id=defaults["project_id"],
            project_name=defaults["project_name"],
            root=".",
            language=defaults["language"],
            source_roots=defaults["source_roots"],
        )
    
    @staticmethod
    def build_box_defaults(box_input: AddBoxInput, state: PlannerState) -> PlannerBox:
        """Build a box with generated default values.
        
        Args:
            box_input: User-provided box data.
            state: Current planner state.
        
        Returns:
            PlannerBox with all derived fields populated.
        """
        # Get source root for path generation
        source_root = state.project_config.source_roots[0] if state.project_config.source_roots else "src"
        
        # Generate derived values
        path = generate_box_path(source_root, box_input.domain, box_input.name)
        symbol = generate_box_symbol(box_input.name)
        lifecycle = box_input.lifecycle or "active"
        
        # Create box
        box = PlannerBox(
            name=box_input.name,
            domain=box_input.domain,
            purpose=box_input.purpose,
            symbol_type=box_input.symbol_type,
            lifecycle=lifecycle,
            path=path,
            symbol=symbol,
            interface=None,  # User can add interface later
        )
        
        return box


class BoxFactory:
    """Factory for creating and validating boxes."""
    
    @staticmethod
    def create_box(input_data: AddBoxInput, state: PlannerState) -> PlannerBox:
        """Create a new box with validation.
        
        Args:
            input_data: User-provided box data.
            state: Current planner state.
        
        Returns:
            Validated PlannerBox instance.
        
        Raises:
            ValueError: If validation fails.
        """
        # Validate name
        if not input_data.name or not input_data.name.strip():
            raise ValueError("Box name cannot be empty")
        
        # Validate domain
        if not input_data.domain or not input_data.domain.strip():
            raise ValueError("Box domain cannot be empty")
        
        # Validate purpose
        if not input_data.purpose or not input_data.purpose.strip():
            raise ValueError("Block purpose cannot be empty")
        
        # Validate symbol_type
        if input_data.symbol_type not in VALID_SYMBOL_TYPES:
            raise ValueError(
                f"Invalid kind: {input_data.symbol_type}. Must be one of: {VALID_SYMBOL_TYPES}"
            )
        
        # Validate lifecycle if provided
        if input_data.lifecycle:
            allowed_lifecycles = state.project_config.allowed_lifecycles
            if input_data.lifecycle not in allowed_lifecycles:
                raise ValueError(f"Invalid lifecycle: {input_data.lifecycle}. Must be one of: {allowed_lifecycles}")
        
        # Generate defaults
        box = PlannerDefaultsBuilder.build_box_defaults(input_data, state)
        
        # Ensure ID is unique
        existing_ids = {b.id for b in state.boxes}
        if box.id in existing_ids:
            # Add a suffix to make it unique
            suffix = 2
            new_id = f"{box.id}_{suffix}"
            while new_id in existing_ids:
                suffix += 1
                new_id = f"{box.id}_{suffix}"
            box.id = new_id
        
        return box
    
    @staticmethod
    def update_box(box: PlannerBox, updates: dict) -> PlannerBox:
        """Update an existing box with new values.
        
        Args:
            box: The box to update.
            updates: Dictionary of fields to update.
        
        Returns:
            Updated PlannerBox instance.
        
        Note:
            This creates a new box instance since PlannerBox is a dataclass.
            Derived fields will be recalculated automatically.
        """
        # Create a new box with updated values
        updated_box = PlannerBox(
            name=updates.get("name", box.name),
            domain=updates.get("domain", box.domain),
            purpose=updates.get("purpose", box.purpose),
            symbol_type=updates.get("symbol_type", box.symbol_type),
            lifecycle=updates.get("lifecycle", box.lifecycle),
            path=updates.get("path", box.path),
            symbol=updates.get("symbol", box.symbol),
            interface=updates.get("interface", box.interface),
            notes=updates.get("notes", box.notes),
        )
        
        return updated_box
