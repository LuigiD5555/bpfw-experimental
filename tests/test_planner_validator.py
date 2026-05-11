"""Tests for planner validator."""

from bpfw.integrations.planner.models import (
    PlannerBox,
    PlannerConnection,
    PlannerInterface,
    PlannerInterfaceInput,
    PlannerInterfaceOutput,
    PlannerProjectConfig,
    PlannerState,
)
import bpfw.integrations.planner.validator as validator_module

# Get classes directly from validator module
PlanFinding = validator_module.PlanFinding
PlanValidationResult = validator_module.PlanValidationResult


def test_plan_finding_creation() -> None:
    """Test creating a PlanFinding."""
    finding = PlanFinding(
        level="error",
        message="Test error message",
        box_id="test_box",
    )
    
    assert finding.level == "error"
    assert finding.message == "Test error message"
    assert finding.box_id == "test_box"


def test_plan_validation_result_creation() -> None:
    """Test creating PlanValidationResult."""
    errors = [
        PlanFinding(level="error", message="Error 1"),
        PlanFinding(level="error", message="Error 2"),
    ]
    warnings = [
        PlanFinding(level="warning", message="Warning 1"),
    ]
    
    result = PlanValidationResult(
        allowed=False,
        errors=errors,
        warnings=warnings,
    )
    
    assert result.allowed is False
    assert result.has_errors is True
    assert result.has_warnings is True
    assert len(result.errors) == 2
    assert len(result.warnings) == 1


def test_plan_validation_result_has_errors() -> None:
    """Test has_errors property."""
    result_empty = PlanValidationResult(allowed=True)
    assert result_empty.has_errors is False
    
    result_with_errors = PlanValidationResult(
        allowed=False,
        errors=[PlanFinding(level="error", message="Test")],
    )
    assert result_with_errors.has_errors is True


def test_plan_validation_result_has_warnings() -> None:
    """Test has_warnings property."""
    result_empty = PlanValidationResult(allowed=True)
    assert result_empty.has_warnings is False
    
    result_with_warnings = PlanValidationResult(
        allowed=True,
        warnings=[PlanFinding(level="warning", message="Test")],
    )
    assert result_with_warnings.has_warnings is True


def test_plan_validation_result_summary() -> None:
    """Test summary property."""
    result_valid = PlanValidationResult(allowed=True)
    assert "valid" in result_valid.summary.lower()
    
    result_errors = PlanValidationResult(
        allowed=False,
        errors=[PlanFinding(level="error", message="Error 1")],
    )
    assert "1 error" in result_errors.summary.lower()
    
    result_warnings = PlanValidationResult(
        allowed=True,
        warnings=[PlanFinding(level="warning", message="Warning 1")],
    )
    assert "1 warning" in result_warnings.summary.lower()


def test_plan_validation_result_with_multiple_issues() -> None:
    """Test PlanValidationResult with multiple issues."""
    errors = [
        PlanFinding(level="error", message="Error 1", box_id="box1"),
        PlanFinding(level="error", message="Error 2", box_id="box2"),
        PlanFinding(level="error", message="Error 3", box_id="box3"),
    ]
    warnings = [
        PlanFinding(level="warning", message="Warning 1"),
        PlanFinding(level="warning", message="Warning 2"),
    ]
    
    result = PlanValidationResult(
        allowed=False,
        errors=errors,
        warnings=warnings,
    )
    
    assert result.allowed is False
    assert result.has_errors is True
    assert result.has_warnings is True
    assert len(result.errors) == 3
    assert len(result.warnings) == 2
    assert "3 errors" in result.summary.lower()
    assert "2 warnings" in result.summary.lower()


def test_plan_finding_warning_level() -> None:
    """Test PlanFinding with warning level."""
    finding = PlanFinding(
        level="warning",
        message="Test warning message",
        box_id="test_box",
    )
    
    assert finding.level == "warning"
    assert finding.message == "Test warning message"
    assert finding.box_id == "test_box"


def test_plan_finding_without_box_id() -> None:
    """Test PlanFinding without box_id (optional)."""
    finding = PlanFinding(
        level="error",
        message="General error message",
    )
    
    assert finding.level == "error"
    assert finding.message == "General error message"
    assert finding.box_id is None