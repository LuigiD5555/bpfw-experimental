"""Validation components for the Planner integration."""

from dataclasses import dataclass, field
from typing import List, Optional

from bpfw.integrations.planner_impl.models import PlannerState


@dataclass
class PlanFinding:
    """A finding from plan validation."""
    
    level: str  # "error" or "warning"
    message: str
    box_id: Optional[str] = None


@dataclass
class PlanValidationResult:
    """Result of validating a plan."""
    
    allowed: bool
    errors: List[PlanFinding] = field(default_factory=list)
    warnings: List[PlanFinding] = field(default_factory=list)
    
    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0
    
    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0
    
    @property
    def summary(self) -> str:
        """Get a summary of validation results."""
        error_count = len(self.errors)
        warning_count = len(self.warnings)
        
        parts = []
        if error_count > 0:
            parts.append(f"{error_count} error{'s' if error_count != 1 else ''}")
        if warning_count > 0:
            parts.append(f"{warning_count} warning{'s' if warning_count != 1 else ''}")
        
        if not parts:
            return "Plan is valid"
        
        return ", ".join(parts)


class PlanValidator:
    """Validate planner state for consistency."""
    
    @staticmethod
    def validate(state: PlannerState) -> PlanValidationResult:
        """Validate the complete planner state.
        
        Args:
            state: Current planner state.
        
        Returns:
            PlanValidationResult with any errors or warnings.
        """
        errors = []
        warnings = []
        
        # Validate boxes
        box_errors, box_warnings = PlanValidator._validate_boxes(state)
        errors.extend(box_errors)
        warnings.extend(box_warnings)
        
        # Validate connections
        conn_errors, conn_warnings = PlanValidator._validate_connections(state)
        errors.extend(conn_errors)
        warnings.extend(conn_warnings)
        
        # Validate policy compliance
        policy_errors, policy_warnings = PlanValidator._validate_policy(state)
        errors.extend(policy_errors)
        warnings.extend(policy_warnings)
        
        return PlanValidationResult(
            allowed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
    
    @staticmethod
    def _validate_boxes(state: PlannerState) -> tuple[List[PlanFinding], List[PlanFinding]]:
        """Validate all boxes.
        
        Args:
            state: Current planner state.
        
        Returns:
            Tuple of (errors, warnings).
        """
        errors = []
        warnings = []
        box_ids = set()
        
        for box in state.boxes:
            # Check for duplicate IDs
            if box.id in box_ids:
                errors.append(PlanFinding(
                    level="error",
                    message=f"Duplicate box ID: {box.id}",
                    box_id=box.id,
                ))
            box_ids.add(box.id)
            
            # Validate required fields
            if not box.id or not box.id.strip():
                errors.append(PlanFinding(
                    level="error",
                    message=f"Box has no ID",
                    box_id=box.id or "unknown",
                ))
            
            if not box.name or not box.name.strip():
                errors.append(PlanFinding(
                    level="error",
                    message=f"Box has no name",
                    box_id=box.id or "unknown",
                ))
            
            if not box.intent or not box.intent.strip():
                warnings.append(PlanFinding(
                    level="warning",
                    message=f"Box has no intent",
                    box_id=box.id,
                ))
            
            if not box.domain or not box.domain.strip():
                warnings.append(PlanFinding(
                    level="warning",
                    message=f"Box has no domain",
                    box_id=box.id,
                ))
            
            # Validate lifecycle
            if box.lifecycle not in state.project_config.allowed_lifecycles:
                errors.append(PlanFinding(
                    level="error",
                    message=f"Invalid lifecycle '{box.lifecycle}'. Must be one of: {state.project_config.allowed_lifecycles}",
                    box_id=box.id,
                ))
            
            # Validate location
            if not box.path or not box.path.strip():
                warnings.append(PlanFinding(
                    level="warning",
                    message=f"Box has no path",
                    box_id=box.id,
                ))
            
            if not box.symbol or not box.symbol.strip():
                warnings.append(PlanFinding(
                    level="warning",
                    message=f"Box has no symbol",
                    box_id=box.id,
                ))
            
            if not box.symbol_type or not box.symbol_type.strip():
                warnings.append(PlanFinding(
                    level="warning",
                    message=f"Box has no symbol_type",
                    box_id=box.id,
                ))
        
        return errors, warnings
    
    @staticmethod
    def _validate_connections(state: PlannerState) -> tuple[List[PlanFinding], List[PlanFinding]]:
        """Validate all connections.
        
        Args:
            state: Current planner state.
        
        Returns:
            Tuple of (errors, warnings).
        """
        errors = []
        warnings = []
        
        box_ids = {box.id for box in state.boxes}
        
        for idx, conn in enumerate(state.connections):
            # Check source exists
            if conn.source_box_id not in box_ids:
                errors.append(PlanFinding(
                    level="error",
                    message=f"Connection references unknown source box: {conn.source_box_id}",
                ))
            
            # Check target exists
            if conn.target_box_id not in box_ids:
                errors.append(PlanFinding(
                    level="error",
                    message=f"Connection references unknown target box: {conn.target_box_id}",
                ))
            
            # Check for self-connections
            if conn.source_box_id == conn.target_box_id:
                warnings.append(PlanFinding(
                    level="warning",
                    message=f"Connection points to itself: {conn.source_box_id}",
                ))
            
            # Check relationship type
            valid_relationships = [
                "calls",
                "produces_input_for",
                "validates",
                "transforms",
                "exports",
                "replaces",
                "uses",
                "depends_on",
            ]
            if conn.relationship not in valid_relationships:
                warnings.append(PlanFinding(
                    level="warning",
                    message=f"Unknown relationship type: {conn.relationship}. Expected one of: {valid_relationships}",
                ))
        
        return errors, warnings
    
    @staticmethod
    def _validate_policy(state: PlannerState) -> tuple[List[PlanFinding], List[PlanFinding]]:
        """Validate policy compliance.
        
        Args:
            state: Current planner state.
        
        Returns:
            Tuple of (errors, warnings).
        """
        errors = []
        warnings = []
        
        # Check for duplicate active intents
        if state.project_config.single_active_per_intent:
            active_by_intent = {}
            
            for box in state.boxes:
                if box.lifecycle == "active" and box.duplicate_group:
                    if box.duplicate_group not in active_by_intent:
                        active_by_intent[box.duplicate_group] = []
                    active_by_intent[box.duplicate_group].append(box)
            
            for intent, boxes in active_by_intent.items():
                if len(boxes) > 1:
                    box_ids = ", ".join(b.id for b in boxes)
                    errors.append(PlanFinding(
                        level="error",
                        message=f"Multiple active boxes with same intent '{intent}': {box_ids}",
                    ))
        
        return errors, warnings
