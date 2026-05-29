"""Main controller for Planner integration using state machine pattern."""

from pathlib import Path
from typing import Optional

from bpfw.integrations.editor.screen import read_input, read_line
from bpfw.integrations.planner.assembler import BlueprintAssembler, BlueprintYamlWriter
from bpfw.integrations.planner.defaults import AddBoxInput, BoxFactory, VALID_SYMBOL_TYPES
from bpfw.integrations.planner.loader import BlueprintStateLoader
from bpfw.integrations.planner.models import (
    PlannerBox,
    PlannerConnection,
    PlannerInterface,
    PlannerInterfaceInput,
    PlannerInterfaceOutput,
    PlannerState,
    RELATIONSHIP_LABELS,
    RELATIONSHIP_FROM_LABEL,
    VALID_RELATIONSHIPS,
)
from bpfw.integrations.planner.renderer import render_planner
from bpfw.integrations.planner.utils import generate_box_path
from bpfw.integrations.planner.validator import PlanValidator
from bpfw.integrations.shared.cli_runtime import is_back_command, is_quit_command, run_interactive_loop
from bpfw.core.errors import BlueprintLockedError


class PlannerController:
    """Orchestrate complete planner session using state machine pattern."""

    def __init__(self, project_root: Path) -> None:
        """Initialize planner controller.

        Args:
            project_root: Root directory of project.
        """
        self.project_root = project_root
        self.state = self._load_state_with_fallback(project_root)
        self.validator = PlanValidator()
        self.should_exit = False

        # Modal state
        self.modal_data = {}  # Store temporary data for modals
        self.modal_cursor = 0  # For selection within modals

        # Check for broken connections on load
        if self.state.broken_connections:
            self.state.screen = "broken_connections"

    def _load_state_with_fallback(self, project_root: Path) -> PlannerState:
        """Load state and fall back to user-facing invalid YAML screen on failure."""
        try:
            return BlueprintStateLoader.load(project_root)
        except ValueError as error:
            from bpfw.integrations.planner.defaults import PlannerDefaultsBuilder

            config = PlannerDefaultsBuilder.build_project_defaults(project_root)
            return PlannerState(
                project_config=config,
                blueprint_path=project_root / "bpfw" / "blueprint.yaml",
                source_mode="invalid_blueprint",
                screen="invalid_blueprint",
                modal_data={"invalid_reason": str(error)},
            )

    def run(self) -> int:
        """Run interactive planner session.

        Returns:
            Exit code (0 for success, 1 for error).
        """
        handlers_by_screen = {
            "welcome": self._handle_welcome_key,
            "workspace": self._handle_workspace_key,
            "add_block": self._handle_add_block_key,
            "connect_target": self._handle_connect_target_key,
            "connect_meaning": self._handle_connect_meaning_key,
            "connect_feedback": self._handle_connect_feedback_key,
            "edit_block": self._handle_edit_block_key,
            "edit_field": self._handle_edit_field_key,
            "edit_inputs": self._handle_edit_inputs_key,
            "edit_input": self._handle_edit_input_key,
            "edit_output": self._handle_edit_output_key,
            "project_settings": self._handle_project_settings_key,
            "review": self._handle_review_key,
            "yaml_preview": self._handle_yaml_preview_key,
            "saved": self._handle_saved_key,
            "graph_overview": self._handle_graph_overview_key,
            "disconnect": self._handle_disconnect_key,
            "removed_connection": self._handle_removed_connection_key,
            "delete_block": self._handle_delete_block_key,
            "unsaved_changes": self._handle_unsaved_changes_key,
            "broken_connections": self._handle_broken_connections_key,
            "no_blocks_to_connect": self._handle_no_blocks_to_connect_key,
            "duplicate_connection": self._handle_duplicate_connection_key,
            "self_connection": self._handle_self_connection_key,
            "cannot_save_empty": self._handle_cannot_save_empty_key,
            "path_already_used": self._handle_path_already_used_key,
            "domain_changed": self._handle_domain_changed_key,
            "blueprint_locked": self._handle_blueprint_locked_key,
            "invalid_blueprint": self._handle_invalid_blueprint_key,
        }
        return run_interactive_loop(
            render_step=self._render_current_screen,
            read_command=read_input,
            get_screen=lambda: self.state.screen,
            resolve_prompt=self._prompt_for_current_screen,
            handlers_by_screen=handlers_by_screen,
            should_exit=lambda: self.should_exit,
        )

    def _render_current_screen(self) -> None:
        """Render active screen with synchronized modal state."""
        self.state.modal_data = self.modal_data
        self.state.modal_cursor = self.modal_cursor
        render_planner(self.state)

    def _prompt_for_current_screen(self, screen: str | None = None) -> str:
        """Return contextual input prompt for current planner screen."""
        active_screen = screen or self.state.screen
        if active_screen == "add_block":
            return "> Name (example: InvoiceParser): "
        if active_screen == "connect_target":
            return "> From block: "
        if active_screen == "connect_meaning":
            return "> Meaning: "
        if active_screen == "edit_block":
            return "> Block: "
        if active_screen == "edit_inputs" and self.modal_data.get("selecting_interface_block"):
            return "> Block: "
        return "> "

    # ---------------------------------------------------------------------------
    # Welcome Screen Handler
    # ---------------------------------------------------------------------------

    def _handle_welcome_key(self, key: str) -> None:
        """Handle key input on welcome screen.

        Args:
            key: Key pressed by user.
        """
        command = key.lower()
        if command in {"", "enter", "continue", "start", "c"}:
            self.state.screen = "workspace"
        elif is_quit_command(command):
            self.should_exit = True

    # ---------------------------------------------------------------------------
    # Workspace Handler
    # ---------------------------------------------------------------------------

    def _handle_workspace_key(self, key: str) -> None:
        """Handle key input on workspace screen.

        Args:
            key: Key pressed by user.
        """
        command = key.lower()
        # Actions (command-driven)
        if command == 'a' or command == "add":
            # Add block
            self.state.screen = "add_block"
        elif command == 'c' or command == "connect":
            # Connect blocks
            if len(self.state.boxes) < 2:
                self.state.screen = "no_blocks_to_connect"
            else:
                self.state.screen = "connect_target"
        elif command == 'e' or command == "edit":
            # Edit block
            if self.state.boxes:
                self.state.screen = "edit_block"
                self.modal_data = {}
                self.modal_cursor = 0
        elif command == 'i' or command == "interface":
            if self.state.boxes:
                self.state.selected_box_id = None
                self.state.screen = "edit_inputs"
                self.modal_data = {"selecting_interface_block": True}
        elif command == 's' or command == "save":
            # Save
            self.state.screen = "review"
        elif command == 'r' or command == "review":
            self.state.screen = "review"
        elif command == 'p' or command == "project":
            # Project settings
            self.state.screen = "project_settings"
            self.modal_data = {}
            self.modal_cursor = 0
        elif command == 'x' or command == "disconnect":
            # Disconnect
            if self.state.boxes:
                self._check_disconnect_available()
        elif command == 'd' or command == "delete":
            # Delete block
            if self.state.boxes:
                self.state.screen = "delete_block"
                self.modal_data = {}
        elif command == 'v' or command == 'g' or command == "view":
            # Graph overview
            self.state.screen = "graph_overview"
        elif is_quit_command(command):
            # Quit with unsaved check
            if self.state.dirty:
                self.state.screen = "unsaved_changes"
            else:
                self.should_exit = True
        elif command.isdigit() and self.state.boxes:
            index = int(command) - 1
            ordered_boxes = sorted(self.state.boxes, key=lambda box: (box.domain, box.name))
            if 0 <= index < len(ordered_boxes):
                self.state.selected_box_id = ordered_boxes[index].id

    def _handle_pieces_filter_input(self, key: str) -> None:
        """Handle filter input while workspace filter mode is active."""
        if key == "enter":
            self.state.pieces_filter_mode = False
            return
        if key == "backspace":
            self.state.pieces_filter = self.state.pieces_filter[:-1]
        elif len(key) == 1 and (key.isalnum() or key in ["-", "_", " "]):
            self.state.pieces_filter += key

        visible_boxes = self._get_visible_boxes()
        if visible_boxes and self.state.selected_box_id not in {box.id for box in visible_boxes}:
            self.state.selected_box_id = visible_boxes[0].id

    def _navigate_up(self) -> None:
        """Navigate to previous box."""
        visible_boxes = self._get_visible_boxes()
        if not visible_boxes:
            return

        if not self.state.selected_box_id:
            self.state.selected_box_id = visible_boxes[0].id
            return

        # Find current index and select previous
        for idx, box in enumerate(visible_boxes):
            if box.id == self.state.selected_box_id:
                if idx > 0:
                    self.state.selected_box_id = visible_boxes[idx - 1].id
                break

    def _navigate_down(self) -> None:
        """Navigate to next box."""
        visible_boxes = self._get_visible_boxes()
        if not visible_boxes:
            return

        if not self.state.selected_box_id:
            self.state.selected_box_id = visible_boxes[0].id
            return

        # Find current index and select next
        for idx, box in enumerate(visible_boxes):
            if box.id == self.state.selected_box_id:
                if idx < len(visible_boxes) - 1:
                    self.state.selected_box_id = visible_boxes[idx + 1].id
                break

    def _check_disconnect_available(self) -> None:
        """Check if there are connections to disconnect."""
        if not self.state.selected_box_id:
            return

        # Count connections for selected box
        connections_count = sum(
            1 for conn in self.state.connections
            if conn.source_box_id == self.state.selected_box_id or
               conn.target_box_id == self.state.selected_box_id
        )

        if connections_count > 0:
            self.state.screen = "disconnect"
            self.modal_data = {}
            self.modal_cursor = 0

    # ---------------------------------------------------------------------------
    # Add Block Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_add_block_key(self, key: str) -> None:
        """Handle command-driven add block flow."""
        name = key.strip()
        if not name:
            self.state.screen = "workspace"
            return
        domain = read_line("> Domain (example: ingestion): ").strip()
        purpose = read_line("> Purpose (example: Parse OCR text into invoice data): ").strip()
        visible_symbol_types = [symbol_type for symbol_type in VALID_SYMBOL_TYPES if not symbol_type.startswith("nested_")]
        kind_options = ", ".join(f"{index + 1}={symbol_type}" for index, symbol_type in enumerate(visible_symbol_types))
        kind_choice = read_line(f"> Kind [{kind_options}] (default 1): ").strip().lower()
        if not kind_choice:
            kind = visible_symbol_types[0]
        elif kind_choice.isdigit() and 1 <= int(kind_choice) <= len(visible_symbol_types):
            kind = visible_symbol_types[int(kind_choice) - 1]
        elif kind_choice in VALID_SYMBOL_TYPES:
            kind = kind_choice
        else:
            kind = visible_symbol_types[0]
        try:
            input_data = AddBoxInput(
                name=name,
                domain=domain,
                purpose=purpose,
                symbol_type=kind,
                lifecycle=None,
            )
            box = BoxFactory.create_box(input_data, self.state)
            self.state.boxes.append(box)
            self.state.selected_box_id = box.id
            self.state.boxes_added += 1
            self.state.dirty = True
        except ValueError as error:
            self.modal_data["error_message"] = str(error)
        self.state.screen = "workspace"
        self.modal_data = {}

    def _handle_modal_input(self, key: str, fields: list) -> None:
        """Handle input for modal fields.

        Args:
            key: Key pressed by user.
            fields: List of field names in order.
        """
        if key == 'backspace':
            # Remove last character from current field
            field_index = self.modal_data.get('field_index', 0)
            if isinstance(field_index, int) and 0 <= field_index < len(fields):
                field = fields[field_index]
                current = self.modal_data.get(field, '')
                self.modal_data[field] = current[:-1]
        elif len(key) == 1 and (key.isalnum() or key in ['-', '_', ' ']):
            # Add character to current field
            field_index = self.modal_data.get('field_index', 0)
            if isinstance(field_index, int) and 0 <= field_index < len(fields):
                field = fields[field_index]
                current = self.modal_data.get(field, '')
                self.modal_data[field] = current + key
        elif key == 'tab':
            # Move to next field
            current = self.modal_data.get('field_index', 0)
            if isinstance(current, int):
                self.modal_data['field_index'] = (current + 1) % len(fields)

    # ---------------------------------------------------------------------------
    # Connect Target Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_connect_target_key(self, key: str) -> None:
        """Handle command-driven connection flow (source/target/meaning by number)."""
        ordered_boxes = sorted(self.state.boxes, key=lambda box: box.name)
        source_input = key.strip()
        if not source_input.isdigit():
            self.state.screen = "workspace"
            return
        source_index = int(source_input) - 1
        if source_index < 0 or source_index >= len(ordered_boxes):
            self.state.screen = "workspace"
            return
        source = ordered_boxes[source_index]
        targets = [box for box in ordered_boxes if box.id != source.id]
        if not targets:
            self.state.screen = "no_blocks_to_connect"
            return
        target_input = read_line("To block number: ").strip()
        if not target_input.isdigit():
            self.state.screen = "workspace"
            return
        target_index = int(target_input) - 1
        if target_index < 0 or target_index >= len(ordered_boxes):
            self.state.screen = "workspace"
            return
        target = ordered_boxes[target_index]
        self.state.selected_box_id = source.id
        self.modal_data = {"target_id": target.id, "relationship_index": 0}
        self.state.screen = "connect_meaning"

    def _get_connect_targets(self) -> list:
        """Get list of valid target boxes for connection.

        Returns:
            List of boxes that can be targets.
        """
        if not self.state.selected_box_id:
            return []

        targets = [b for b in self.state.boxes if b.id != self.state.selected_box_id]
        return sorted(targets, key=lambda box: box.name)

    # ---------------------------------------------------------------------------
    # Connect Meaning Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_connect_meaning_key(self, key: str) -> None:
        """Handle command-driven relationship selection."""
        choice = key.strip()
        if not choice:
            choice = read_line("Meaning [1-8]: ").strip()
        if not choice.isdigit():
            self.state.screen = "workspace"
            return
        index = int(choice) - 1
        if index < 0 or index >= len(VALID_RELATIONSHIPS):
            self.state.screen = "workspace"
            return
        self.modal_data["relationship_index"] = index
        self._create_connection()

    def _create_connection(self) -> None:
        """Create a connection based on modal data."""
        source_id = self.state.selected_box_id
        target_id = self.modal_data.get('target_id')
        rel_index = self.modal_data.get('relationship_index', 0)

        if not source_id or not target_id:
            return

        if not isinstance(rel_index, int):
            return

        relationship = VALID_RELATIONSHIPS[rel_index]

        # Validate
        if source_id == target_id:
            self.state.screen = "self_connection"
            return

        # Check for duplicate
        for conn in self.state.connections:
            if (conn.source_box_id == source_id and
                conn.target_box_id == target_id and
                conn.relationship == relationship):
                self.state.screen = "duplicate_connection"
                self.modal_data = {"existing_connection": conn}
                return

        # Create connection
        connection = PlannerConnection(
            source_box_id=source_id,
            target_box_id=target_id,
            relationship=relationship,
            source_kind="blueprint",
            confidence="high",
            evidence=["manual:connect"],
            status="accepted",
        )

        self.state.connections.append(connection)
        self.state.connections_added += 1
        self.state.dirty = True

        # Show feedback
        self.state.screen = "connect_feedback"
        self.modal_data = {
            'source_id': source_id,
            'target_id': target_id,
            'relationship': relationship,
        }

    # ---------------------------------------------------------------------------
    # Connect Feedback Handler
    # ---------------------------------------------------------------------------

    def _handle_connect_feedback_key(self, key: str) -> None:
        """Handle connected feedback and return to board."""
        self.state.screen = "workspace"
        self.modal_data = {}

    # ---------------------------------------------------------------------------
    # Edit Block Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_edit_block_key(self, key: str) -> None:
        """Handle command-driven block selection and field selection."""
        ordered_boxes = sorted(self.state.boxes, key=lambda box: (box.domain, box.name))
        selection = key.strip()
        if not selection.isdigit():
            self.state.screen = "workspace"
            return
        index = int(selection) - 1
        if index < 0 or index >= len(ordered_boxes):
            self.state.screen = "workspace"
            return
        selected_box = ordered_boxes[index]
        self.state.selected_box_id = selected_box.id
        field_choice = read_line("Field [1 purpose,2 domain,3 lifecycle,4 path,5 symbol,6 kind,7 inputs,8 output]: ").strip()
        if not field_choice.isdigit():
            self.state.screen = "workspace"
            return
        field_num = int(field_choice)
        if field_num == 1:
            self.modal_data = {'field': 'purpose', 'value': selected_box.purpose or ''}
            self._handle_edit_field_key("")
        elif field_num == 2:
            self.modal_data = {'field': 'domain', 'value': selected_box.domain}
            self._handle_edit_field_key("")
        elif field_num == 3:
            self.modal_data = {'field': 'lifecycle', 'value': selected_box.lifecycle}
            self._handle_edit_field_key("")
        elif field_num == 4:
            self.modal_data = {'field': 'path', 'value': selected_box.path or ''}
            self._handle_edit_field_key("")
        elif field_num == 5:
            self.modal_data = {'field': 'symbol', 'value': selected_box.symbol or ''}
            self._handle_edit_field_key("")
        elif field_num == 6:
            self.modal_data = {'field': 'symbol_type', 'value': selected_box.symbol_type}
            self._handle_edit_field_key("")
        elif field_num == 7:
            self.state.screen = "edit_inputs"
            self.modal_data = {}
        elif field_num == 8:
            self.state.screen = "edit_output"
            self.modal_data = {}
        else:
            self.state.screen = "workspace"

    # ---------------------------------------------------------------------------
    # Edit Field Handler (for text fields)
    # ---------------------------------------------------------------------------

    def _handle_edit_field_key(self, key: str) -> None:
        """Handle key input when editing a text field.

        Args:
            key: Key pressed by user.
        """
        field = self.modal_data.get('field')
        current_value = str(self.modal_data.get('value', ''))
        entered_value = key.strip() or read_line(f"New value for {field} [{current_value}]: ").strip()
        value = entered_value or current_value
        selected_box = self._get_selected_box()
        if selected_box and value:
            if field == "domain" and value != selected_box.domain:
                current_path = selected_box.path or ""
                source_root = self.state.project_config.source_roots[0] if self.state.project_config.source_roots else "src"
                suggested_path = generate_box_path(source_root, value, selected_box.name)
                if current_path and current_path != suggested_path:
                    self.state.screen = "domain_changed"
                    self.modal_data = {
                        "pending_field": field,
                        "pending_value": value,
                        "old_domain": selected_box.domain,
                        "new_domain": value,
                        "current_path": current_path,
                        "suggested_path": suggested_path,
                    }
                    return

            if field == "path":
                existing_box = self._find_box_by_path(value, exclude_box_id=selected_box.id)
                if existing_box is not None:
                    self.state.screen = "path_already_used"
                    self.modal_data = {
                        "pending_field": field,
                        "pending_value": value,
                        "path": value,
                        "existing_box": existing_box,
                    }
                    return

            updates = {field: value}
            self._apply_box_updates(selected_box, updates)

        self.state.screen = "workspace"
        self.modal_data = {}

    # ---------------------------------------------------------------------------
    # Edit Inputs Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_edit_inputs_key(self, key: str) -> None:
        """Manage a block interface using commands."""
        selected_box = self._get_selected_box()
        if selected_box is None or self.modal_data.get("selecting_interface_block"):
            ordered_boxes = sorted(self.state.boxes, key=lambda box: (box.domain, box.name))
            choice = key.strip()
            if not choice.isdigit():
                self.state.screen = "workspace"
                self.modal_data = {}
                return
            index = int(choice) - 1
            if index < 0 or index >= len(ordered_boxes):
                self.state.screen = "workspace"
                self.modal_data = {}
                return
            selected_box = ordered_boxes[index]
            self.state.selected_box_id = selected_box.id
            self.modal_data = {}
            self.state.screen = "edit_inputs"
            return

        action = key.strip().lower()
        if not action:
            self.state.screen = "workspace"
            self.modal_data = {}
            return
        if action == "a":
            self.state.screen = "edit_input"
            return
        if action in {"o", "s", "set"}:
            self.state.screen = "edit_output"
            return
        if action in {"c", "clear"}:
            if not selected_box.interface:
                selected_box.interface = PlannerInterface()
            selected_box.interface.output = None
            self.state.boxes_edited += 1
            self.state.dirty = True
            self.state.screen = "workspace"
            return
        if action == "e":
            if not selected_box.interface or not selected_box.interface.inputs:
                self.state.screen = "workspace"
                return
            index_text = read_line("Input number to edit: ").strip()
            if not index_text.isdigit():
                self.state.screen = "workspace"
                return
            input_index = int(index_text) - 1
            if input_index < 0 or input_index >= len(selected_box.interface.inputs):
                self.state.screen = "workspace"
                return
            selected_input = selected_box.interface.inputs[input_index]
            name_value = read_line(f"Name [{selected_input.name}]: ").strip() or selected_input.name
            type_value = read_line(f"Type [{selected_input.type or ''}]: ").strip() or selected_input.type
            description_value = read_line(f"Description [{selected_input.description or ''}]: ").strip() or selected_input.description
            required_value = read_line(f"Required [{selected_input.required}] y/n: ").strip().lower()
            if required_value in {"y", "yes", "true", "1"}:
                selected_input.required = True
            elif required_value in {"n", "no", "false", "0"}:
                selected_input.required = False
            selected_input.name = name_value
            selected_input.type = type_value
            selected_input.description = description_value
            self.state.boxes_edited += 1
            self.state.dirty = True
            self.state.screen = "workspace"
            return
        if action == "d":
            if selected_box.interface and selected_box.interface.inputs:
                index_text = read_line("Input number to delete: ").strip()
                if index_text.isdigit():
                    input_index = int(index_text) - 1
                    if 0 <= input_index < len(selected_box.interface.inputs):
                        selected_box.interface.inputs.pop(input_index)
                        self.state.boxes_edited += 1
                        self.state.dirty = True
            self.state.screen = "workspace"
            return
        self.state.screen = "workspace"

    # ---------------------------------------------------------------------------
    # Edit Single Input Handler
    # ---------------------------------------------------------------------------

    def _handle_edit_input_key(self, key: str) -> None:
        """Handle key input when editing a single input.

        Args:
            key: Key pressed by user.
        """
        selected_box = self._get_selected_box()
        if not selected_box:
            self.state.screen = "workspace"
            return
        if not selected_box.interface:
            selected_box.interface = PlannerInterface()

        name_value = key.strip()
        if not name_value:
            self.state.screen = "workspace"
            return
        type_value = read_line("Input type: ").strip()
        description_value = read_line("Description: ").strip()
        required_value = read_line("Required? [y/n] (default y): ").strip().lower()
        required = required_value not in {"n", "no", "false", "0"}
        selected_box.interface.inputs.append(
            PlannerInterfaceInput(
                name=name_value,
                type=type_value,
                description=description_value,
                required=required,
            )
        )
        self.state.boxes_edited += 1
        self.state.dirty = True
        self.state.screen = "workspace"
        self.modal_data = {}

    # ---------------------------------------------------------------------------
    # Edit Output Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_edit_output_key(self, key: str) -> None:
        """Handle key input on edit output modal.

        Args:
            key: Key pressed by user.
        """
        selected_box = self._get_selected_box()
        if selected_box is None:
            self.state.screen = "workspace"
            return
        if not selected_box.interface:
            selected_box.interface = PlannerInterface()

        action = key.strip().lower()
        if not action:
            self.state.screen = "workspace"
            return
        if action == "c":
            selected_box.interface.output = None
            self.state.boxes_edited += 1
            self.state.dirty = True
            self.state.screen = "workspace"
            return
        output_type = read_line("Output type: ").strip()
        output_description = read_line("Output description: ").strip()
        selected_box.interface.output = PlannerInterfaceOutput(
            type=output_type,
            description=output_description,
        )
        self.state.boxes_edited += 1
        self.state.dirty = True
        self.state.screen = "workspace"
        self.modal_data = {}

    # ---------------------------------------------------------------------------
    # Project Settings Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_project_settings_key(self, key: str) -> None:
        """Handle key input on project settings modal.

        Args:
            key: Key pressed by user.
        """
        selection = key.strip()
        if not selection:
            self.state.screen = "workspace"
            self.modal_data = {}
            return
        config = self.state.project_config
        if selection == "1":
            value = read_line(f"Project id [{config.project_id}]: ").strip()
            if value:
                config.project_id = value
                self.state.dirty = True
        elif selection == "2":
            value = read_line(f"Project name [{config.project_name}]: ").strip()
            if value:
                config.project_name = value
                self.state.dirty = True
        elif selection == "3":
            value = read_line(f"Language [{config.language}]: ").strip()
            if value:
                config.language = value
                self.state.dirty = True
        elif selection == "4":
            value = read_line(f"Source roots (comma separated) [{','.join(config.source_roots)}]: ").strip()
            if value:
                config.source_roots = [segment.strip() for segment in value.split(",") if segment.strip()]
                self.state.dirty = True
        elif selection == "5":
            value = read_line("Ignored paths (comma separated): ").strip()
            if value:
                config.ignored_paths = [segment.strip() for segment in value.split(",") if segment.strip()]
                self.state.dirty = True
        elif selection == "6":
            value = read_line(f"Policy mode [{config.policy_mode}]: ").strip()
            if value:
                config.policy_mode = value
                self.state.dirty = True
        elif selection in {"7", "8", "9", "10"}:
            bool_value = read_line("Set value [y/n]: ").strip().lower() in {"y", "yes", "true", "1"}
            if selection == "7":
                config.defined_blueprint_blocks_on_drift = bool_value
            elif selection == "8":
                config.single_active_per_purpose = bool_value
            elif selection == "9":
                config.undeclared_code_blocks = bool_value
            elif selection == "10":
                config.missing_declared_code_blocks = bool_value
            self.state.dirty = True
        self.state.screen = "workspace"

    # ---------------------------------------------------------------------------
    # Review Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_review_key(self, key: str) -> None:
        """Handle key input on review modal.

        Args:
            key: Key pressed by user.
        """
        action = key.strip().lower()
        if action == "s":
            self._save_blueprint()
        elif action == "p":
            self.state.screen = "yaml_preview"
        elif action in {"", "b", "back"}:
            self.state.screen = "workspace"
        else:
            self.state.screen = "workspace"

    def _save_blueprint(self) -> None:
        """Save blueprint to file."""
        # Check for empty plan
        if not self.state.boxes:
            self.state.screen = "cannot_save_empty"
            return

        # Validate first
        validation = self.validator.validate(self.state)

        if not validation.allowed:
            self.modal_data['validation_errors'] = [finding.message for finding in validation.errors]
            return

        # Assemble and write
        blueprint_data = BlueprintAssembler.assemble(self.state)
        try:
            BlueprintYamlWriter.write(self.state.blueprint_path, blueprint_data)
        except BlueprintLockedError:
            self.state.screen = "blueprint_locked"
            return

        self.state.dirty = False
        self.state.screen = "saved"

    # ---------------------------------------------------------------------------
    # YAML Preview Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_yaml_preview_key(self, key: str) -> None:
        """Handle key input on YAML preview modal.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command in {'', 'b', 'enter', 'back'}:
            self.modal_data.pop("yaml_preview_full", None)
            self.state.screen = "review"
        elif command == 'f':
            self.modal_data["yaml_preview_full"] = not bool(self.modal_data.get("yaml_preview_full"))

    # ---------------------------------------------------------------------------
    # Saved Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_saved_key(self, key: str) -> None:
        """Handle key input on saved modal.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command == '' or command == 'enter' or command in {'b', 'back'}:
            self.state.screen = "workspace"
        elif is_quit_command(command):
            self.should_exit = True

    # ---------------------------------------------------------------------------
    # Graph Overview Handler
    # ---------------------------------------------------------------------------

    def _handle_graph_overview_key(self, key: str) -> None:
        """Handle key input on graph overview modal.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command == '' or command in {'b', 'enter', 'back'}:
            self.state.screen = "workspace"

    # ---------------------------------------------------------------------------
    # Disconnect Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_disconnect_key(self, key: str) -> None:
        """Handle key input on disconnect modal.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command in {'', 'back'} or is_back_command(command):
            self.state.screen = "workspace"
            self.modal_data = {}
            return
        choice = command
        if not choice.isdigit():
            self.state.screen = "workspace"
            return
        self.modal_cursor = max(0, int(choice) - 1)
        self._remove_connection()

    def _handle_removed_connection_key(self, key: str) -> None:
        """Handle key input on removed connection confirmation modal."""
        command = key.strip().lower()
        if command in {"", "b", "enter", "back"}:
            self.state.screen = "workspace"
            self.modal_data = {}

    def _get_box_connections(self) -> list:
        """Get connections for selected box.

        Returns:
            List of connections.
        """
        if not self.state.selected_box_id:
            return []

        return [
            conn for conn in self.state.connections
            if conn.source_box_id == self.state.selected_box_id or
               conn.target_box_id == self.state.selected_box_id
        ]

    def _remove_connection(self) -> None:
        """Remove selected connection."""
        connections = self._get_box_connections()

        if self.modal_cursor < len(connections):
            conn = connections[self.modal_cursor]
            source_box = next((box for box in self.state.boxes if box.id == conn.source_box_id), None)
            target_box = next((box for box in self.state.boxes if box.id == conn.target_box_id), None)

            # Remove from state
            self.state.connections.remove(conn)
            self.state.connections_removed += 1
            self.state.dirty = True
            self.state.screen = "removed_connection"
            self.modal_data = {
                "source_name": source_box.name if source_box else conn.source_box_id,
                "target_name": target_box.name if target_box else conn.target_box_id,
            }
            return

        self.state.screen = "workspace"
        self.modal_data = {}

    # ---------------------------------------------------------------------------
    # Delete Block Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_delete_block_key(self, key: str) -> None:
        """Handle key input on delete block modal.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command in {'', 'back'} or is_back_command(command):
            self.state.screen = "workspace"
            self.modal_data = {}
        elif command in {'d', 'delete'}:
            # Delete block and its connections
            self._delete_selected_block()

    def _delete_selected_block(self) -> None:
        """Delete selected block and its connections."""
        if not self.state.selected_box_id:
            return

        # Remove connections
        connections_to_remove = [
            conn for conn in self.state.connections
            if conn.source_box_id == self.state.selected_box_id or
               conn.target_box_id == self.state.selected_box_id
        ]

        for conn in connections_to_remove:
            self.state.connections.remove(conn)
            self.state.connections_removed += 1

        # Remove box
        for idx, box in enumerate(self.state.boxes):
            if box.id == self.state.selected_box_id:
                self.state.boxes.pop(idx)
                self.state.boxes_deleted += 1
                break

        self.state.dirty = True
        self.state.selected_box_id = None
        self.state.screen = "workspace"
        self.modal_data = {}

    # ---------------------------------------------------------------------------
    # Unsaved Changes Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_unsaved_changes_key(self, key: str) -> None:
        """Handle key input on unsaved changes modal.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command in {'', 'b', 'back'}:
            self.state.screen = "workspace"
        elif command == 's':
            # Save and quit
            self._save_blueprint()
            # After saving, will exit on next q
        elif is_quit_command(command):
            # Quit without saving
            self.state.dirty = False  # Skip unsaved check
            self.should_exit = True

    # ---------------------------------------------------------------------------
    # Broken Connections Modal Handler
    # ---------------------------------------------------------------------------

    def _handle_broken_connections_key(self, key: str) -> None:
        """Handle key input on broken connections modal.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command == 'r':
            # Remove broken connections
            self.state.broken_connections.clear()
            self.state.screen = "workspace"
        elif command in {'k', 'back'} or is_back_command(command):
            # Keep and continue
            self.state.screen = "workspace"
        elif is_quit_command(command):
            # Quit
            self.should_exit = True

    # ---------------------------------------------------------------------------
    # Helper Methods
    # ---------------------------------------------------------------------------

    def _get_selected_box(self) -> Optional[PlannerBox]:
        """Get currently selected box.

        Returns:
            Selected box or None if not selected.
        """
        if not self.state.selected_box_id:
            return None

        for box in self.state.boxes:
            if box.id == self.state.selected_box_id:
                return box
        return None

    def _get_visible_boxes(self) -> list[PlannerBox]:
        """Return visible boxes according to active Pieces filter."""
        filter_text = self.state.pieces_filter.strip().lower()
        if not filter_text:
            return list(self.state.boxes)
        return [
            box for box in self.state.boxes
            if filter_text in box.name.lower() or filter_text in box.domain.lower() or filter_text in box.purpose.lower()
        ]

    def _apply_box_updates(self, selected_box: PlannerBox, updates: dict) -> None:
        """Apply updates to selected box and track edit counters."""
        updated_box = BoxFactory.update_box(selected_box, updates)

        for idx, box in enumerate(self.state.boxes):
            if box.id == selected_box.id:
                self.state.boxes[idx] = updated_box
                self.state.selected_box_id = updated_box.id
                break

        self.state.boxes_edited += 1
        self.state.dirty = True

    def _find_box_by_path(self, path: str, exclude_box_id: str) -> Optional[PlannerBox]:
        """Find an existing box using the same path, excluding one box id."""
        for box in self.state.boxes:
            if box.id != exclude_box_id and box.path == path:
                return box
        return None

    # ---------------------------------------------------------------------------
    # Edge Case Handlers
    # ---------------------------------------------------------------------------

    def _handle_no_blocks_to_connect_key(self, key: str) -> None:
        """Handle key input when no blocks to connect.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command == 'a':
            # Add block
            self.state.screen = "add_block"
        elif command in {'', 'enter', 'back'} or is_back_command(command):
            self.state.screen = "workspace"

    def _handle_duplicate_connection_key(self, key: str) -> None:
        """Handle key input for duplicate connection modal.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command in {'', 'enter', 'back'} or is_back_command(command):
            self.state.screen = "workspace"

    def _handle_self_connection_key(self, key: str) -> None:
        """Handle key input for self-connection modal.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command in {'', 'enter'}:
            # Go back to target selection
            self.state.screen = "connect_target"
        elif command in {'back'} or is_back_command(command):
            self.state.screen = "workspace"

    def _handle_cannot_save_empty_key(self, key: str) -> None:
        """Handle key input when trying to save empty plan.

        Args:
            key: Key pressed by user.
        """
        command = key.strip().lower()
        if command == 'a':
            # Add block
            self.state.screen = "add_block"
        elif command in {'', 'enter', 'back'} or is_back_command(command):
            self.state.screen = "workspace"

    def _handle_path_already_used_key(self, key: str) -> None:
        """Handle key input for path already used modal."""
        selected_box = self._get_selected_box()
        if selected_box is None:
            self.state.screen = "workspace"
            self.modal_data = {}
            return

        command = key.strip().lower()
        if command in {"", "enter"}:
            suggested_path = self.modal_data.get("suggested_path")
            if not suggested_path:
                current_path = str(self.modal_data.get("path") or "")
                base_path = Path(current_path)
                suggested_path = str(base_path.parent / f"{base_path.stem}_v2{base_path.suffix}")
            updates = {"path": str(suggested_path)}
            pending_domain = self.modal_data.get("pending_domain")
            if isinstance(pending_domain, str) and pending_domain:
                updates["domain"] = pending_domain
            self._apply_box_updates(selected_box, updates)
            self.state.screen = "edit_block"
            self.modal_data = {}
        elif command == "e":
            current_path = str(self.modal_data.get("path") or "")
            self.state.screen = "edit_field"
            self.modal_data = {"field": "path", "value": current_path}
        elif command in {"b", "back"}:
            self.state.screen = "edit_block"
            self.modal_data = {}

    def _handle_domain_changed_key(self, key: str) -> None:
        """Handle key input for domain changed modal."""
        selected_box = self._get_selected_box()
        if selected_box is None:
            self.state.screen = "workspace"
            self.modal_data = {}
            return

        pending_domain = str(self.modal_data.get("pending_value") or selected_box.domain)
        suggested_path = str(self.modal_data.get("suggested_path") or selected_box.path or "")

        command = key.strip().lower()
        if command in {"", "enter"}:
            existing_box = self._find_box_by_path(suggested_path, exclude_box_id=selected_box.id)
            if existing_box is not None:
                self.state.screen = "path_already_used"
                self.modal_data = {
                    "pending_field": "path",
                    "pending_value": suggested_path,
                    "path": suggested_path,
                    "existing_box": existing_box,
                    "suggested_path": str(Path(suggested_path).with_name(f"{Path(suggested_path).stem}_v2{Path(suggested_path).suffix}")),
                    "pending_domain": pending_domain,
                }
                return

            self._apply_box_updates(selected_box, {"domain": pending_domain, "path": suggested_path})
            self.state.screen = "edit_block"
            self.modal_data = {}
        elif command == "k":
            self._apply_box_updates(selected_box, {"domain": pending_domain})
            self.state.screen = "edit_block"
            self.modal_data = {}
        elif command == "e":
            self._apply_box_updates(selected_box, {"domain": pending_domain})
            self.state.screen = "edit_field"
            self.modal_data = {"field": "path", "value": suggested_path}
        elif command in {"b", "back"}:
            self.state.screen = "edit_block"
            self.modal_data = {}

    def _handle_blueprint_locked_key(self, key: str) -> None:
        """Handle key input for blueprint locked modal."""
        command = key.strip().lower()
        if command in {"", "enter", "b", "back"}:
            self.state.screen = "workspace"
        elif is_quit_command(command):
            self.should_exit = True

    def _handle_invalid_blueprint_key(self, key: str) -> None:
        """Handle key input for invalid blueprint modal."""
        command = key.strip().lower()
        if command in {"", "enter", "b", "back"} or is_quit_command(command):
            self.should_exit = True
