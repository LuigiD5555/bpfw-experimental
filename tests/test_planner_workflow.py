"""Workflow tests for planner controller and renderer core UX behavior."""

from pathlib import Path

from bpfw.integrations.planner.controller import PlannerController
from bpfw.core.errors import BlueprintLockedError
from bpfw.integrations.planner.models import (
    PlannerBox,
    PlannerConnection,
    PlannerProjectConfig,
    PlannerState,
)
import bpfw.integrations.planner.renderer as renderer_module
import bpfw.integrations.planner.controller as controller_module


class _AlwaysAllowedValidation:
    allowed = True
    errors: list = []


class _AlwaysAllowedValidator:
    def validate(self, state: PlannerState) -> _AlwaysAllowedValidation:
        return _AlwaysAllowedValidation()


def _build_state(boxes: list[PlannerBox], connections: list[PlannerConnection] | None = None) -> PlannerState:
    """Create planner state for workflow tests."""
    if connections is None:
        connections = []
    return PlannerState(
        project_config=PlannerProjectConfig(project_id="test_project", project_name="test_project"),
        boxes=boxes,
        connections=connections,
        selected_box_id=boxes[0].id if boxes else None,
        screen="workspace",
    )


def _build_controller(state: PlannerState) -> PlannerController:
    """Create controller instance without loader side-effects."""
    controller = PlannerController.__new__(PlannerController)
    controller.project_root = Path(".")
    controller.state = state
    controller.should_exit = False
    controller.modal_data = {}
    controller.modal_cursor = 0
    controller.validator = _AlwaysAllowedValidator()
    return controller


def test_space_with_single_block_shows_no_blocks_to_connect() -> None:
    """Pressing space with one block should open no-blocks modal."""
    box = PlannerBox(name="PdfReader", domain="ingestion", intent="Read PDFs", symbol_type="class")
    state = _build_state(boxes=[box])
    controller = _build_controller(state)

    controller._handle_workspace_key("space")

    assert controller.state.screen == "no_blocks_to_connect"


def test_connect_target_initializes_default_target() -> None:
    """Opening connect mode initializes cursor and target_id."""
    source = PlannerBox(name="SourceBox", domain="ingestion", intent="source", symbol_type="class")
    target_z = PlannerBox(name="ZuluTarget", domain="ingestion", intent="z", symbol_type="class")
    target_a = PlannerBox(name="AlphaTarget", domain="ingestion", intent="a", symbol_type="class")
    state = _build_state(boxes=[source, target_z, target_a])
    controller = _build_controller(state)

    controller._handle_workspace_key("space")

    assert controller.state.screen == "connect_target"
    assert controller.modal_cursor == 0
    # Targets are sorted by name; first should be AlphaTarget.
    assert controller.modal_data["target_id"] == target_a.id


def test_connect_target_enter_advances_without_down() -> None:
    """Enter in connect target works immediately with default selection."""
    source = PlannerBox(name="SourceBox", domain="ingestion", intent="source", symbol_type="class")
    target = PlannerBox(name="TargetBox", domain="ingestion", intent="target", symbol_type="class")
    state = _build_state(boxes=[source, target])
    controller = _build_controller(state)
    controller._handle_workspace_key("space")

    controller._handle_connect_target_key("enter")

    assert controller.state.screen == "connect_meaning"
    assert controller.modal_data["relationship_index"] == 0


def test_create_connection_self_routes_to_self_connection() -> None:
    """Self-connection should route to self_connection modal."""
    source = PlannerBox(name="InvoiceParser", domain="ingestion", intent="parse", symbol_type="class")
    state = _build_state(boxes=[source])
    controller = _build_controller(state)
    controller.modal_data = {"target_id": source.id, "relationship_index": 0}

    controller._create_connection()

    assert controller.state.screen == "self_connection"


def test_create_connection_duplicate_routes_to_duplicate_connection() -> None:
    """Duplicate connection should route to duplicate_connection modal."""
    source = PlannerBox(name="PdfReader", domain="ingestion", intent="read", symbol_type="class")
    target = PlannerBox(name="OcrExtractor", domain="ingestion", intent="extract", symbol_type="class")
    existing = PlannerConnection(
        source_box_id=source.id,
        target_box_id=target.id,
        relationship="produces_input_for",
    )
    state = _build_state(boxes=[source, target], connections=[existing])
    controller = _build_controller(state)
    controller.modal_data = {"target_id": target.id, "relationship_index": 0}

    controller._create_connection()

    assert controller.state.screen == "duplicate_connection"
    assert controller.modal_data["existing_connection"] is existing


def test_render_connect_target_modal_shows_selected_marker(monkeypatch, capsys) -> None:
    """Connect target modal shows visual marker for current selection."""
    monkeypatch.setattr(renderer_module, "clear_screen", lambda: None)
    monkeypatch.setattr(renderer_module, "get_terminal_width", lambda: 120)

    source = PlannerBox(name="SourceBox", domain="ingestion", intent="source", symbol_type="class")
    target_a = PlannerBox(name="AlphaTarget", domain="ingestion", intent="a", symbol_type="class")
    target_b = PlannerBox(name="BetaTarget", domain="ingestion", intent="b", symbol_type="class")
    state = _build_state(boxes=[source, target_b, target_a])
    state.screen = "connect_target"
    state.modal_data = {"target_id": target_b.id}

    renderer_module.render_connect_target_modal(state)
    output = capsys.readouterr().out

    assert "> BetaTarget" in output
    assert "  AlphaTarget" in output


def test_render_connect_feedback_modal_uses_dynamic_connection_data(monkeypatch, capsys) -> None:
    """Connected feedback renders source, target and human relationship labels."""
    monkeypatch.setattr(renderer_module, "clear_screen", lambda: None)
    monkeypatch.setattr(renderer_module, "get_terminal_width", lambda: 120)

    source = PlannerBox(name="PdfReader", domain="ingestion", intent="read", symbol_type="class")
    target = PlannerBox(name="OcrExtractor", domain="ingestion", intent="extract", symbol_type="class")
    state = _build_state(boxes=[source, target])
    state.screen = "connect_feedback"
    state.modal_data = {
        "source_id": source.id,
        "target_id": target.id,
        "relationship": "produces_input_for",
    }

    renderer_module.render_connect_feedback_modal(state)
    output = capsys.readouterr().out

    assert "PdfReader" in output
    assert "OcrExtractor" in output
    assert "sends output to" in output


def test_remove_connection_opens_removed_feedback_modal() -> None:
    """Disconnect should show Removed modal with connection summary."""
    source = PlannerBox(name="InvoiceParser", domain="ingestion", intent="parse", symbol_type="class")
    target = PlannerBox(name="InvoiceValidator", domain="validation", intent="validate", symbol_type="class")
    connection = PlannerConnection(
        source_box_id=source.id,
        target_box_id=target.id,
        relationship="produces_input_for",
    )
    state = _build_state(boxes=[source, target], connections=[connection])
    controller = _build_controller(state)

    controller._remove_connection()

    assert controller.state.screen == "removed_connection"
    assert controller.modal_data["source_name"] == "InvoiceParser"
    assert controller.modal_data["target_name"] == "InvoiceValidator"
    assert controller.state.connections == []


def test_edit_domain_opens_domain_changed_modal() -> None:
    """Changing domain should prompt Domain Changed instead of silent path change."""
    box = PlannerBox(
        name="InvoiceParser",
        domain="ingestion",
        intent="parse",
        symbol_type="class",
        path="src/ingestion/invoice_parser.py",
    )
    state = _build_state(boxes=[box])
    controller = _build_controller(state)
    controller.state.screen = "edit_field"
    controller.modal_data = {"field": "domain", "value": "parsing"}

    controller._handle_edit_field_key("enter")

    assert controller.state.screen == "domain_changed"
    assert controller.modal_data["old_domain"] == "ingestion"
    assert controller.modal_data["new_domain"] == "parsing"
    assert controller.modal_data["suggested_path"] == "src/parsing/invoice_parser.py"


def test_edit_path_with_duplicate_opens_path_already_used_modal() -> None:
    """Setting a duplicated path should open Path Already Used modal."""
    first = PlannerBox(
        name="InvoiceParser",
        domain="ingestion",
        intent="parse",
        symbol_type="class",
        path="src/ingestion/invoice_parser.py",
    )
    second = PlannerBox(
        name="SmartInvoiceParser",
        domain="ingestion",
        intent="smart parse",
        symbol_type="class",
        path="src/ingestion/smart_invoice_parser.py",
    )
    state = _build_state(boxes=[second, first])
    controller = _build_controller(state)
    controller.state.selected_box_id = second.id
    controller.state.screen = "edit_field"
    controller.modal_data = {"field": "path", "value": "src/ingestion/invoice_parser.py"}

    controller._handle_edit_field_key("enter")

    assert controller.state.screen == "path_already_used"
    assert controller.modal_data["path"] == "src/ingestion/invoice_parser.py"
    assert controller.modal_data["existing_box"].id == first.id


def test_render_unsaved_changes_uses_details_changed_label(monkeypatch, capsys) -> None:
    """Unsaved modal should use user-facing 'Details changed' label."""
    monkeypatch.setattr(renderer_module, "clear_screen", lambda: None)
    monkeypatch.setattr(renderer_module, "get_terminal_width", lambda: 120)
    box = PlannerBox(name="InvoiceParser", domain="ingestion", intent="parse", symbol_type="class")
    state = _build_state(boxes=[box])
    state.screen = "unsaved_changes"
    state.boxes_added = 2
    state.boxes_edited = 3
    state.connections_added = 1

    renderer_module.render_unsaved_changes_modal(state)
    output = capsys.readouterr().out

    assert "Details changed: 3" in output
    assert "Blocks edited:" not in output


def test_save_blueprint_when_locked_opens_blueprint_locked_modal(monkeypatch) -> None:
    """Saving while blueprint is locked should show dedicated modal."""
    box = PlannerBox(name="InvoiceParser", domain="ingestion", intent="parse", symbol_type="class")
    state = _build_state(boxes=[box])
    controller = _build_controller(state)

    def _raise_locked(*args, **kwargs):
        raise BlueprintLockedError("Blueprint is locked")

    monkeypatch.setattr(controller_module.BlueprintYamlWriter, "write", _raise_locked)

    controller._save_blueprint()

    assert controller.state.screen == "blueprint_locked"


def test_render_welcome_empty_blueprint_mode(monkeypatch, capsys) -> None:
    """Welcome should show explicit messaging for empty blueprint file."""
    monkeypatch.setattr(renderer_module, "clear_screen", lambda: None)
    monkeypatch.setattr(renderer_module, "get_terminal_width", lambda: 120)

    state = PlannerState(
        project_config=PlannerProjectConfig(project_id="invoice_tool", project_name="invoice-tool"),
        source_mode="empty_blueprint",
    )
    renderer_module.render_welcome(state)
    output = capsys.readouterr().out

    assert "exists but has no responsibilities" in output
    assert "start a new system plan" in output


def test_render_invalid_blueprint_modal(monkeypatch, capsys) -> None:
    """Invalid blueprint modal should explain safe exit behavior."""
    monkeypatch.setattr(renderer_module, "clear_screen", lambda: None)
    monkeypatch.setattr(renderer_module, "get_terminal_width", lambda: 120)

    state = PlannerState(
        project_config=PlannerProjectConfig(project_id="invoice_tool", project_name="invoice-tool"),
        source_mode="invalid_blueprint",
    )
    state.modal_data = {"invalid_reason": "Invalid YAML near line 42"}
    renderer_module.render_invalid_blueprint_modal(state)
    output = capsys.readouterr().out

    assert "could not load blueprint.yaml" in output
    assert "Invalid YAML near line 42" in output
    assert "will not overwrite this file" in output


def test_render_pieces_panel_filter_and_overflow() -> None:
    """Pieces panel should include filter prompt and overflow hint."""
    boxes = [
        PlannerBox(name=f"Block{i:02d}", domain="ingestion", intent=f"intent {i}", symbol_type="class")
        for i in range(20)
    ]
    lines = renderer_module.render_pieces_panel_internal(
        boxes=boxes,
        selected_id=boxes[0].id,
        filter_text="",
        filter_mode=False,
    )
    text = "\n".join(lines)

    assert "Filter: _" in text
    assert "Showing " in text
    assert "of 20" in text


def test_navigation_long_sequence_reaches_last_visible_box() -> None:
    """Repeated down key should walk through long visible list."""
    boxes = [
        PlannerBox(name=f"Block{i:02d}", domain="ingestion", intent=f"intent {i}", symbol_type="class")
        for i in range(25)
    ]
    state = _build_state(boxes=boxes)
    controller = _build_controller(state)

    for _ in range(40):
        controller._handle_workspace_key("down")

    assert controller.state.selected_box_id == boxes[-1].id


def test_filter_typing_and_navigation_sequence() -> None:
    """Filter mode should constrain visible list and navigation should stay within it."""
    boxes = [
        PlannerBox(name="PdfReader", domain="ingestion", intent="read", symbol_type="class"),
        PlannerBox(name="OcrExtractor", domain="ingestion", intent="extract", symbol_type="class"),
        PlannerBox(name="InvoiceParser", domain="parsing", intent="parse", symbol_type="class"),
    ]
    state = _build_state(boxes=boxes)
    controller = _build_controller(state)

    controller._handle_workspace_key("/")
    controller._handle_workspace_key("p")
    controller._handle_workspace_key("a")
    controller._handle_workspace_key("r")
    controller._handle_workspace_key("s")
    controller._handle_workspace_key("e")
    controller._handle_workspace_key("enter")

    visible = controller._get_visible_boxes()
    assert len(visible) == 1
    assert visible[0].name == "InvoiceParser"
    assert controller.state.selected_box_id == visible[0].id
