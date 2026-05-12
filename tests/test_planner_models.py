"""Tests for planner models."""

from bpfw.integrations.planner.models import (
    PlannerBox,
    PlannerConnection,
    PlannerInterface,
    PlannerInterfaceInput,
    PlannerInterfaceOutput,
    PlannerProjectConfig,
    PlannerState,
    RELATIONSHIP_LABELS,
    VALID_RELATIONSHIPS,
)


def test_planner_box_creation() -> None:
    """Test creating a planner box."""
    box = PlannerBox(
        name="TestBox",
        domain="test_domain",
        purpose="Test purpose",
        lifecycle="active",
        symbol_type="class",
    )
    
    assert box.name == "TestBox"
    assert box.domain == "test_domain"
    assert box.purpose == "Test purpose"
    assert box.lifecycle == "active"
    assert box.symbol_type == "class"
    assert box.path is None
    assert box.symbol is None
    assert box.interface is None


def test_planner_box_with_interface() -> None:
    """Test creating a planner box with interface."""
    interface = PlannerInterface(
        inputs=[
            PlannerInterfaceInput(
                name="input1",
                type="str",
                description="First input",
                required=True,
            )
        ],
        output=PlannerInterfaceOutput(
            type="dict",
            description="Output data",
        ),
    )
    
    box = PlannerBox(
        name="TestBox",
        domain="test_domain",
        purpose="Test purpose",
        lifecycle="active",
        symbol_type="class",
        interface=interface,
    )
    
    assert box.interface is not None
    assert len(box.interface.inputs) == 1
    assert box.interface.inputs[0].name == "input1"
    assert box.interface.inputs[0].required is True
    assert box.interface.output is not None
    assert box.interface.output.type == "dict"


def test_planner_connection_creation() -> None:
    """Test creating a planner connection."""
    conn = PlannerConnection(
        source_box_id="source_id",
        target_box_id="target_id",
        relationship="produces_input_for",
        source_kind="blueprint",
        confidence="high",
        evidence=["manual:connect"],
        status="accepted",
    )
    
    assert conn.source_box_id == "source_id"
    assert conn.target_box_id == "target_id"
    assert conn.relationship == "produces_input_for"
    assert conn.confidence == "high"
    assert conn.status == "accepted"


def test_planner_state_initialization() -> None:
    """Test planner state initialization."""
    config = PlannerProjectConfig(
        project_id="test_project",
        project_name="test_project_name",
    )
    state = PlannerState(project_config=config)
    
    assert state.screen == "welcome"
    assert state.source_mode == "new_plan"
    assert state.boxes == []
    assert state.connections == []
    assert state.broken_connections == []
    assert state.selected_box_id is None
    assert state.dirty is False
    assert state.boxes_added == 0
    assert state.boxes_edited == 0
    assert state.boxes_deleted == 0
    assert state.connections_added == 0
    assert state.connections_removed == 0


def test_relationship_labels_mapping() -> None:
    """Test relationship labels are properly mapped."""
    assert "produces_input_for" in RELATIONSHIP_LABELS
    assert RELATIONSHIP_LABELS["produces_input_for"] == "sends output to"
    assert "calls" in RELATIONSHIP_LABELS
    assert "validates" in RELATIONSHIP_LABELS
    assert "transforms" in RELATIONSHIP_LABELS
    assert "exports" in RELATIONSHIP_LABELS
    assert "replaces" in RELATIONSHIP_LABELS


def test_valid_relationships_list() -> None:
    """Test valid relationships list."""
    assert len(VALID_RELATIONSHIPS) > 0
    assert "produces_input_for" in VALID_RELATIONSHIPS
    assert "calls" in VALID_RELATIONSHIPS
    assert "validates" in VALID_RELATIONSHIPS


def test_planner_interface_input_required_flag() -> None:
    """Test interface input required flag."""
    inp1 = PlannerInterfaceInput(
        name="required_input",
        type="str",
        required=True,
    )
    
    inp2 = PlannerInterfaceInput(
        name="optional_input",
        type="str",
        required=False,
    )
    
    assert inp1.required is True
    assert inp2.required is False
    assert inp1.type == "str"
    assert inp2.type == "str"