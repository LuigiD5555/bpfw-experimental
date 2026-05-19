"""Workflow tests for command-driven planner UX."""

from pathlib import Path

import bpfw.integrations.planner.controller as controller_module
import bpfw.integrations.planner.renderer as renderer_module
from bpfw.core.errors import BlueprintLockedError
from bpfw.integrations.planner.controller import PlannerController
from bpfw.integrations.planner.models import PlannerBox, PlannerConnection, PlannerProjectConfig, PlannerState


class _AlwaysAllowedValidation:
    allowed = True
    errors: list = []


class _AlwaysAllowedValidator:
    def validate(self, state: PlannerState) -> _AlwaysAllowedValidation:
        return _AlwaysAllowedValidation()


def _build_state(boxes: list[PlannerBox], connections: list[PlannerConnection] | None = None) -> PlannerState:
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
    controller = PlannerController.__new__(PlannerController)
    controller.project_root = Path(".")
    controller.state = state
    controller.should_exit = False
    controller.modal_data = {}
    controller.modal_cursor = 0
    controller.validator = _AlwaysAllowedValidator()
    return controller


def test_workspace_command_selects_block_by_number() -> None:
    first = PlannerBox(name="PdfReader", domain="ingestion", purpose="read", symbol_type="class")
    second = PlannerBox(name="OcrExtractor", domain="ingestion", purpose="extract", symbol_type="class")
    state = _build_state(boxes=[first, second])
    controller = _build_controller(state)

    controller._handle_workspace_key("2")

    ordered_boxes = sorted(state.boxes, key=lambda box: (box.domain, box.name))
    assert controller.state.selected_box_id == ordered_boxes[1].id


def test_welcome_enter_moves_to_workspace() -> None:
    state = _build_state(boxes=[])
    state.screen = "welcome"
    controller = _build_controller(state)

    controller._handle_welcome_key("")

    assert controller.state.screen == "workspace"


def test_workspace_connect_command_opens_connect_screen() -> None:
    first = PlannerBox(name="PdfReader", domain="ingestion", purpose="read", symbol_type="class")
    second = PlannerBox(name="OcrExtractor", domain="ingestion", purpose="extract", symbol_type="class")
    state = _build_state(boxes=[first, second])
    controller = _build_controller(state)

    controller._handle_workspace_key("c")

    assert controller.state.screen == "connect_target"


def test_connect_flow_uses_numeric_prompts(monkeypatch) -> None:
    first = PlannerBox(name="PdfReader", domain="ingestion", purpose="read", symbol_type="class")
    second = PlannerBox(name="OcrExtractor", domain="ingestion", purpose="extract", symbol_type="class")
    state = _build_state(boxes=[first, second])
    controller = _build_controller(state)

    responses = iter(["2"])
    monkeypatch.setattr(controller_module, "read_line", lambda _prompt="": next(responses))

    controller._handle_connect_target_key("1")
    controller._handle_connect_meaning_key("1")

    assert controller.state.screen == "connect_feedback"
    assert len(controller.state.connections) == 1
    assert controller.state.connections[0].relationship == "produces_input_for"


def test_add_block_flow_uses_sequential_prompts(monkeypatch) -> None:
    state = _build_state(boxes=[])
    controller = _build_controller(state)
    controller.state.screen = "add_block"

    responses = iter(["ingestion", "Parse text", "1"])
    monkeypatch.setattr(controller_module, "read_line", lambda _prompt="": next(responses))

    controller._handle_add_block_key("InvoiceParser")

    assert controller.state.screen == "workspace"
    assert len(controller.state.boxes) == 1
    assert controller.state.boxes[0].name == "InvoiceParser"


def test_render_add_block_modal_shows_current_step(monkeypatch, capsys) -> None:
    monkeypatch.setattr(renderer_module, "refresh_screen", lambda: None)
    monkeypatch.setattr(renderer_module, "get_terminal_width", lambda: 120)

    state = _build_state(boxes=[])
    state.screen = "add_block"

    renderer_module.render_add_block_modal(state)
    output = capsys.readouterr().out

    assert "Step 1 of 4" in output
    assert "Enter the block name now." in output
    assert "Next prompts after this:" in output


def test_edit_block_field_updates_value_in_same_flow(monkeypatch) -> None:
    box = PlannerBox(name="Pipeline", domain="framework", purpose="Old purpose", symbol_type="class")
    state = _build_state(boxes=[box])
    controller = _build_controller(state)
    controller.state.screen = "edit_block"

    responses = iter(["1", "New pipeline purpose"])
    monkeypatch.setattr(controller_module, "read_line", lambda _prompt="": next(responses))

    controller._handle_edit_block_key("1")

    assert controller.state.screen == "workspace"
    assert controller.state.boxes[0].purpose == "New pipeline purpose"


def test_workspace_interface_command_asks_for_block() -> None:
    box = PlannerBox(name="Pipeline", domain="framework", purpose="Run pipeline", symbol_type="class")
    state = _build_state(boxes=[box])
    controller = _build_controller(state)

    controller._handle_workspace_key("i")

    assert controller.state.screen == "edit_inputs"
    assert controller.state.selected_box_id is None
    assert controller.modal_data["selecting_interface_block"] is True


def test_interface_block_selection_opens_interface_menu() -> None:
    box = PlannerBox(name="Pipeline", domain="framework", purpose="Run pipeline", symbol_type="class")
    state = _build_state(boxes=[box])
    state.selected_box_id = None
    controller = _build_controller(state)
    controller.modal_data = {"selecting_interface_block": True}

    controller._handle_edit_inputs_key("1")

    assert controller.state.screen == "edit_inputs"
    assert controller.state.selected_box_id == box.id
    assert controller.modal_data == {}


def test_render_edit_interface_shows_inputs_and_output_actions(monkeypatch, capsys) -> None:
    monkeypatch.setattr(renderer_module, "refresh_screen", lambda: None)
    monkeypatch.setattr(renderer_module, "get_terminal_width", lambda: 120)
    box = PlannerBox(name="Pipeline", domain="framework", purpose="Run pipeline", symbol_type="class")
    state = _build_state(boxes=[box])

    renderer_module.render_edit_inputs_modal(state)
    output = capsys.readouterr().out

    assert "Edit Interface: Pipeline" in output
    assert "A block interface is its inputs and output." in output
    assert "[o] Set output" in output


def test_review_b_returns_to_workspace() -> None:
    box = PlannerBox(name="Pipeline", domain="framework", purpose="Run pipeline", symbol_type="class")
    state = _build_state(boxes=[box])
    state.screen = "review"
    controller = _build_controller(state)

    controller._handle_review_key("b")

    assert controller.state.screen == "workspace"


def test_review_p_opens_yaml_preview() -> None:
    box = PlannerBox(name="Pipeline", domain="framework", purpose="Run pipeline", symbol_type="class")
    state = _build_state(boxes=[box])
    state.screen = "review"
    controller = _build_controller(state)

    controller._handle_review_key("p")

    assert controller.state.screen == "yaml_preview"


def test_yaml_preview_f_toggles_full_preview() -> None:
    box = PlannerBox(name="Pipeline", domain="framework", purpose="Run pipeline", symbol_type="class")
    state = _build_state(boxes=[box])
    state.screen = "yaml_preview"
    controller = _build_controller(state)

    controller._handle_yaml_preview_key("f")

    assert controller.modal_data["yaml_preview_full"] is True


def test_render_full_yaml_preview_uses_assembled_blueprint(monkeypatch, capsys) -> None:
    monkeypatch.setattr(renderer_module, "refresh_screen", lambda: None)
    monkeypatch.setattr(renderer_module, "get_terminal_width", lambda: 120)
    box = PlannerBox(name="Pipeline", domain="framework", purpose="Run pipeline", symbol_type="class")
    state = _build_state(boxes=[box])
    state.screen = "yaml_preview"
    state.modal_data = {"yaml_preview_full": True}

    renderer_module.render_yaml_preview_modal(state)
    output = capsys.readouterr().out

    assert "policy:" in output
    assert "blocks:" in output
    assert "[f] Summary YAML" in output


def test_render_connect_target_modal_shows_numeric_list(monkeypatch, capsys) -> None:
    monkeypatch.setattr(renderer_module, "refresh_screen", lambda: None)
    monkeypatch.setattr(renderer_module, "get_terminal_width", lambda: 120)

    source = PlannerBox(name="SourceBox", domain="ingestion", purpose="source", symbol_type="class")
    target = PlannerBox(name="TargetBox", domain="ingestion", purpose="target", symbol_type="class")
    state = _build_state(boxes=[source, target])
    state.screen = "connect_target"

    renderer_module.render_connect_target_modal(state)
    output = capsys.readouterr().out

    assert "Choose source block number" in output
    assert "[1]" in output


def test_save_blueprint_when_locked_opens_blueprint_locked_modal(monkeypatch) -> None:
    box = PlannerBox(name="InvoiceParser", domain="ingestion", purpose="parse", symbol_type="class")
    state = _build_state(boxes=[box])
    controller = _build_controller(state)

    def _raise_locked(*args, **kwargs):
        raise BlueprintLockedError("Blueprint is locked")

    monkeypatch.setattr(controller_module.BlueprintYamlWriter, "write", _raise_locked)

    controller._save_blueprint()

    assert controller.state.screen == "blueprint_locked"
