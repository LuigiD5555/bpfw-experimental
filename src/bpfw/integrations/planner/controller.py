"""Main controller for Planner integration using state machine pattern."""

from pathlib import Path
from typing import Optional

from bpfw.integrations.editor.screen import read_key, read_input, read_line
from bpfw.integrations.planner.assembler import BlueprintAssembler, BlueprintYamlWriter
from bpfw.integrations.planner.defaults import AddBoxInput, BoxFactory
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
from bpfw.integrations.planner.validator import PlanValidator


class PlannerController:
    """Orchestrate complete planner session using state machine pattern."""
    
    def __init__(self, project_root: Path) -> None:
        """Initialize planner controller.
        
        Args:
            project_root: Root directory of project.
        """
        self.project_root = project_root
        self.state = BlueprintStateLoader.load(project_root)
        self.validator = PlanValidator()
        self.should_exit = False
        
        # Modal state
        self.modal_data = {}  # Store temporary data for modals
        self.modal_cursor = 0  # For selection within modals
        
        # Check for broken connections on load
        if self.state.broken_connections:
            self.state.screen = "broken_connections"
        
    def run(self) -> int:
        """Run interactive planner session.
        
        Returns:
            Exit code (0 for success, 1 for error).
        """
        try:
            while True:
                # Render current screen based on state.screen
                render_planner(self.state)
                
                # Read single key
                key = read_key()
                
                # Handle key based on current screen
                if self.state.screen == "welcome":
                    self._handle_welcome_key(key)
                elif self.state.screen == "workspace":
                    self._handle_workspace_key(key)
                elif self.state.screen == "add_block":
                    self._handle_add_block_key(key)
                elif self.state.screen == "connect_target":
                    self._handle_connect_target_key(key)
                elif self.state.screen == "connect_meaning":
                    self._handle_connect_meaning_key(key)
                elif self.state.screen == "connect_feedback":
                    self._handle_connect_feedback_key(key)
                elif self.state.screen == "edit_block":
                    self._handle_edit_block_key(key)
                elif self.state.screen == "edit_field":
                    self._handle_edit_field_key(key)
                elif self.state.screen == "edit_inputs":
                    self._handle_edit_inputs_key(key)
                elif self.state.screen == "edit_input":
                    self._handle_edit_input_key(key)
                elif self.state.screen == "edit_output":
                    self._handle_edit_output_key(key)
                elif self.state.screen == "project_settings":
                    self._handle_project_settings_key(key)
                elif self.state.screen == "review":
                    self._handle_review_key(key)
                elif self.state.screen == "yaml_preview":
                    self._handle_yaml_preview_key(key)
                elif self.state.screen == "saved":
                    self._handle_saved_key(key)
                elif self.state.screen == "graph_overview":
                    self._handle_graph_overview_key(key)
                elif self.state.screen == "disconnect":
                    self._handle_disconnect_key(key)
                elif self.state.screen == "delete_block":
                    self._handle_delete_block_key(key)
                elif self.state.screen == "unsaved_changes":
                    self._handle_unsaved_changes_key(key)
                elif self.state.screen == "broken_connections":
                    self._handle_broken_connections_key(key)
                elif self.state.screen == "no_blocks_to_connect":
                    self._handle_no_blocks_to_connect_key(key)
                elif self.state.screen == "duplicate_connection":
                    self._handle_duplicate_connection_key(key)
                elif self.state.screen == "self_connection":
                    self._handle_self_connection_key(key)
                elif self.state.screen == "cannot_save_empty":
                    self._handle_cannot_save_empty_key(key)
                
                # Check for quit request from handlers
                if self.should_exit:
                    return 0
                    
        except KeyboardInterrupt:
            return 0
        except EOFError:
            return 0
    
    # ---------------------------------------------------------------------------
    # Welcome Screen Handler
    # ---------------------------------------------------------------------------
    
    def _handle_welcome_key(self, key: str) -> None:
        """Handle key input on welcome screen.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'enter':
            self.state.screen = "workspace"
        elif key == 'q':
            self.should_exit = True
    
    # ---------------------------------------------------------------------------
    # Workspace Handler
    # ---------------------------------------------------------------------------
    
    def _handle_workspace_key(self, key: str) -> None:
        """Handle key input on workspace screen.
        
        Args:
            key: Key pressed by user.
        """
        # Navigation
        if key == 'up':
            self._navigate_up()
        elif key == 'down':
            self._navigate_down()
        
        # Actions
        elif key == 'a':
            # Add block
            self.state.screen = "add_block"
            self.modal_data = {
                'name': '',
                'domain': '',
                'intent': '',
                'kind': 'class',
                'field_index': 0,
            }
            self.modal_cursor = 0
        elif key == 'space' and self.state.selected_box_id:
            # Connect blocks
            if len(self.state.boxes) < 2:
                # No other blocks to connect
                pass
            else:
                self.state.screen = "connect_target"
                self.modal_data = {}
                self.modal_cursor = 0
        elif key == 'tab' and self.state.selected_box_id:
            # Edit block
            self.state.screen = "edit_block"
            self.modal_data = {}
            self.modal_cursor = 0
        elif key == 's':
            # Save
            self.state.screen = "review"
        elif key == 'p':
            # Project settings
            self.state.screen = "project_settings"
            self.modal_data = {}
            self.modal_cursor = 0
        elif key == 'x' and self.state.selected_box_id:
            # Disconnect
            self._check_disconnect_available()
        elif key == 'd' and self.state.selected_box_id:
            # Delete block
            self.state.screen = "delete_block"
            self.modal_data = {}
        elif key == 'g':
            # Graph overview
            self.state.screen = "graph_overview"
        elif key == 'q':
            # Quit with unsaved check
            if self.state.dirty:
                self.state.screen = "unsaved_changes"
            else:
                self.should_exit = True
    
    def _navigate_up(self) -> None:
        """Navigate to previous box."""
        if not self.state.boxes:
            return
        
        if not self.state.selected_box_id:
            self.state.selected_box_id = self.state.boxes[0].id
            return
        
        # Find current index and select previous
        for idx, box in enumerate(self.state.boxes):
            if box.id == self.state.selected_box_id:
                if idx > 0:
                    self.state.selected_box_id = self.state.boxes[idx - 1].id
                break
    
    def _navigate_down(self) -> None:
        """Navigate to next box."""
        if not self.state.boxes:
            return
        
        if not self.state.selected_box_id:
            self.state.selected_box_id = self.state.boxes[0].id
            return
        
        # Find current index and select next
        for idx, box in enumerate(self.state.boxes):
            if box.id == self.state.selected_box_id:
                if idx < len(self.state.boxes) - 1:
                    self.state.selected_box_id = self.state.boxes[idx + 1].id
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
        """Handle key input on add block modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape':
            self.state.screen = "workspace"
            self.modal_data = {}
        elif key == 'enter':
            # Try to create block
            try:
                input_data = AddBoxInput(
                    name=self.modal_data.get('name', ''),
                    domain=self.modal_data.get('domain', ''),
                    intent=self.modal_data.get('intent', ''),
                    symbol_type=self.modal_data.get('kind', 'class'),
                    lifecycle=None,
                )
                
                box = BoxFactory.create_box(input_data, self.state)
                self.state.boxes.append(box)
                self.state.selected_box_id = box.id
                self.state.boxes_added += 1
                self.state.dirty = True
                self.state.screen = "workspace"
                self.modal_data = {}
            except ValueError as error:
                self.modal_data['error_message'] = str(error)
        else:
            # Input character for fields
            self._handle_modal_input(key, ['name', 'domain', 'intent', 'kind'])
    
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
        """Handle key input on connect target modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape':
            self.state.screen = "workspace"
            self.modal_data = {}
        elif key == 'enter':
            # Go to meaning selection
            if self.modal_data.get('target_id'):
                self.state.screen = "connect_meaning"
                self.modal_data['relationship_index'] = 0
        elif key == 'up':
            # Move up in target list
            targets = self._get_connect_targets()
            if self.modal_cursor > 0:
                self.modal_cursor -= 1
        elif key == 'down':
            # Move down in target list
            targets = self._get_connect_targets()
            if self.modal_cursor < len(targets) - 1:
                self.modal_cursor += 1
                # Store selected target
                if targets:
                    self.modal_data['target_id'] = targets[self.modal_cursor].id
    
    def _get_connect_targets(self) -> list:
        """Get list of valid target boxes for connection.
        
        Returns:
            List of boxes that can be targets.
        """
        if not self.state.selected_box_id:
            return []
        
        return [b for b in self.state.boxes if b.id != self.state.selected_box_id]
    
    # ---------------------------------------------------------------------------
    # Connect Meaning Modal Handler
    # ---------------------------------------------------------------------------
    
    def _handle_connect_meaning_key(self, key: str) -> None:
        """Handle key input on connect meaning modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape':
            self.state.screen = "connect_target"
        elif key == 'enter':
            # Create connection
            self._create_connection()
        elif key == 'up':
            # Move up in relationship list
            if self.modal_cursor > 0:
                self.modal_cursor -= 1
        elif key == 'down':
            # Move down in relationship list
            if self.modal_cursor < len(VALID_RELATIONSHIPS) - 1:
                self.modal_cursor += 1
                self.modal_data['relationship_index'] = self.modal_cursor
    
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
            return  # Can't connect to self
        
        # Check for duplicate
        for conn in self.state.connections:
            if (conn.source_box_id == source_id and 
                conn.target_box_id == target_id and 
                conn.relationship == relationship):
                return  # Already exists
        
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
        """Handle key input on connect feedback modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'enter' or key == 'escape':
            self.state.screen = "workspace"
            self.modal_data = {}
    
    # ---------------------------------------------------------------------------
    # Edit Block Modal Handler
    # ---------------------------------------------------------------------------
    
    def _handle_edit_block_key(self, key: str) -> None:
        """Handle key input on edit block modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape':
            self.state.screen = "workspace"
            self.modal_data = {}
        elif key == 'enter':
            # Accept changes (nothing edited yet, so just go back)
            self.state.screen = "workspace"
        elif key.isdigit():
            # Edit specific field
            field_num = int(key)
            selected_box = self._get_selected_box()
            
            if selected_box and 1 <= field_num <= 8:
                if field_num == 1:  # Purpose
                    self.state.screen = "edit_field"
                    self.modal_data = {'field': 'intent', 'value': selected_box.intent or ''}
                elif field_num == 2:  # Domain
                    self.state.screen = "edit_field"
                    self.modal_data = {'field': 'domain', 'value': selected_box.domain}
                elif field_num == 3:  # Status
                    self.state.screen = "edit_field"
                    self.modal_data = {'field': 'lifecycle', 'value': selected_box.lifecycle}
                elif field_num == 4:  # Path
                    self.state.screen = "edit_field"
                    self.modal_data = {'field': 'path', 'value': selected_box.path or ''}
                elif field_num == 5:  # Symbol
                    self.state.screen = "edit_field"
                    self.modal_data = {'field': 'symbol', 'value': selected_box.symbol or ''}
                elif field_num == 6:  # Kind
                    self.state.screen = "edit_field"
                    self.modal_data = {'field': 'symbol_type', 'value': selected_box.symbol_type}
                elif field_num == 7:  # Inputs
                    self.state.screen = "edit_inputs"
                    self.modal_data = {}
                    self.modal_cursor = 0
                elif field_num == 8:  # Output
                    self.state.screen = "edit_output"
                    self.modal_data = {}
                    self.modal_cursor = 0
    
    # ---------------------------------------------------------------------------
    # Edit Field Handler (for text fields)
    # ---------------------------------------------------------------------------
    
    def _handle_edit_field_key(self, key: str) -> None:
        """Handle key input when editing a text field.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape':
            self.state.screen = "edit_block"
        elif key == 'enter':
            # Save field value
            field = self.modal_data.get('field')
            value = self.modal_data.get('value', '').strip()
            
            selected_box = self._get_selected_box()
            if selected_box and value:
                updates = {field: value}
                updated_box = BoxFactory.update_box(selected_box, updates)
                
                # Replace box in list
                for idx, box in enumerate(self.state.boxes):
                    if box.id == selected_box.id:
                        self.state.boxes[idx] = updated_box
                        self.state.selected_box_id = updated_box.id
                        break
                
                self.state.boxes_edited += 1
                self.state.dirty = True
            
            self.state.screen = "edit_block"
            self.modal_data = {}
        elif key == 'backspace':
            # Remove last character
            current = self.modal_data.get('value', '')
            self.modal_data['value'] = current[:-1]
        elif len(key) == 1 and (key.isalnum() or key in ['-', '_', ' ']):
            # Add character
            current = self.modal_data.get('value', '')
            self.modal_data['value'] = current + key
    
    # ---------------------------------------------------------------------------
    # Edit Inputs Modal Handler
    # ---------------------------------------------------------------------------
    
    def _handle_edit_inputs_key(self, key: str) -> None:
        """Handle key input on edit inputs modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape' or key == 'enter':
            self.state.screen = "edit_block"
            self.modal_data = {}
        elif key == 'a':
            # Add new input
            self.state.screen = "edit_input"
            self.modal_data = {
                'name': '',
                'type': '',
                'description': '',
                'required': True,
            }
        elif key == 'e' or key == 'd':
            self.modal_data['status_message'] = "Edit/delete inputs not implemented yet."
    
    # ---------------------------------------------------------------------------
    # Edit Single Input Handler
    # ---------------------------------------------------------------------------
    
    def _handle_edit_input_key(self, key: str) -> None:
        """Handle key input when editing a single input.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape':
            self.state.screen = "edit_inputs"
        elif key == 'enter':
            # Save input
            selected_box = self._get_selected_box()
            if selected_box:
                # Create interface if doesn't exist
                if not selected_box.interface:
                    selected_box.interface = PlannerInterface()
                
                # Add input
                required = self.modal_data.get('required', True)
                if isinstance(required, bool):
                    required_value = required
                else:
                    required_value = str(required).lower() in ['true', 'yes', '1']
                
                new_input = PlannerInterfaceInput(
                    name=self.modal_data.get('name', ''),
                    type=self.modal_data.get('type', ''),
                    description=self.modal_data.get('description', ''),
                    required=required_value,
                )
                selected_box.interface.inputs.append(new_input)
                
                self.state.boxes_edited += 1
                self.state.dirty = True
            
            self.state.screen = "edit_inputs"
            self.modal_data = {}
        elif key == 'backspace':
            current = self.modal_data.get('value', '')
            self.modal_data['value'] = current[:-1]
        elif len(key) == 1 and (key.isalnum() or key in ['-', '_', ' ']):
            # Add character
            current = self.modal_data.get('value', '')
            self.modal_data['value'] = current + key
    
    # ---------------------------------------------------------------------------
    # Edit Output Modal Handler
    # ---------------------------------------------------------------------------
    
    def _handle_edit_output_key(self, key: str) -> None:
        """Handle key input on edit output modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape':
            self.state.screen = "edit_block"
        elif key == 'enter':
            # Save output
            selected_box = self._get_selected_box()
            if selected_box:
                # Create interface if doesn't exist
                if not selected_box.interface:
                    selected_box.interface = PlannerInterface()
                
                # Set output
                selected_box.interface.output = PlannerInterfaceOutput(
                    type=self.modal_data.get('type', ''),
                    description=self.modal_data.get('description', ''),
                )
                
                self.state.boxes_edited += 1
                self.state.dirty = True
            
            self.state.screen = "edit_block"
            self.modal_data = {}
        elif key == 'backspace':
            current = self.modal_data.get('value', '')
            self.modal_data['value'] = current[:-1]
        elif len(key) == 1 and (key.isalnum() or key in ['-', '_', ' ']):
            # Add character
            current = self.modal_data.get('value', '')
            self.modal_data['value'] = current + key
    
    # ---------------------------------------------------------------------------
    # Project Settings Modal Handler
    # ---------------------------------------------------------------------------
    
    def _handle_project_settings_key(self, key: str) -> None:
        """Handle key input on project settings modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape' or key == 'enter':
            self.state.screen = "workspace"
            self.modal_data = {}
        elif key.isdigit():
            self.modal_data['status_message'] = "Project settings editing not implemented yet."
    
    # ---------------------------------------------------------------------------
    # Review Modal Handler
    # ---------------------------------------------------------------------------
    
    def _handle_review_key(self, key: str) -> None:
        """Handle key input on review modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape':
            self.state.screen = "workspace"
        elif key == 's':
            # Save blueprint
            self._save_blueprint()
        elif key == 'y':
            # YAML preview
            self.state.screen = "yaml_preview"
    
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
        BlueprintYamlWriter.write(self.state.blueprint_path, blueprint_data)
        
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
        if key == 'escape' or key == 'enter':
            self.state.screen = "review"
        elif key == 'f':
            return
    
    # ---------------------------------------------------------------------------
    # Saved Modal Handler
    # ---------------------------------------------------------------------------
    
    def _handle_saved_key(self, key: str) -> None:
        """Handle key input on saved modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'enter':
            self.state.screen = "workspace"
        elif key == 'q':
            self.should_exit = True
    
    # ---------------------------------------------------------------------------
    # Graph Overview Handler
    # ---------------------------------------------------------------------------
    
    def _handle_graph_overview_key(self, key: str) -> None:
        """Handle key input on graph overview modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape' or key == 'enter':
            self.state.screen = "workspace"
    
    # ---------------------------------------------------------------------------
    # Disconnect Modal Handler
    # ---------------------------------------------------------------------------
    
    def _handle_disconnect_key(self, key: str) -> None:
        """Handle key input on disconnect modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'escape':
            self.state.screen = "workspace"
            self.modal_data = {}
        elif key == 'enter':
            # Remove selected connection
            self._remove_connection()
        elif key == 'up':
            # Move up in connection list
            connections = self._get_box_connections()
            if self.modal_cursor > 0:
                self.modal_cursor -= 1
        elif key == 'down':
            # Move down in connection list
            connections = self._get_box_connections()
            if self.modal_cursor < len(connections) - 1:
                self.modal_cursor += 1
    
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
            
            # Remove from state
            self.state.connections.remove(conn)
            self.state.connections_removed += 1
            self.state.dirty = True
        
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
        if key == 'escape':
            self.state.screen = "workspace"
            self.modal_data = {}
        elif key == 'd':
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
        if key == 'escape':
            self.state.screen = "workspace"
        elif key == 's':
            # Save and quit
            self._save_blueprint()
            # After saving, will exit on next q
        elif key == 'q':
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
        if key == 'r':
            # Remove broken connections
            self.state.broken_connections.clear()
            self.state.screen = "workspace"
        elif key == 'k':
            # Keep and continue
            self.state.screen = "workspace"
        elif key == 'q':
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
    
    # ---------------------------------------------------------------------------
    # Edge Case Handlers
    # ---------------------------------------------------------------------------
    
    def _handle_no_blocks_to_connect_key(self, key: str) -> None:
        """Handle key input when no blocks to connect.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'a':
            # Add block
            self.state.screen = "add_block"
            self.modal_data = {
                'name': '',
                'domain': '',
                'intent': '',
                'kind': 'class',
                'field_index': 0,
            }
            self.modal_cursor = 0
        elif key == 'enter' or key == 'escape':
            self.state.screen = "workspace"
    
    def _handle_duplicate_connection_key(self, key: str) -> None:
        """Handle key input for duplicate connection modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'enter' or key == 'escape':
            self.state.screen = "workspace"
    
    def _handle_self_connection_key(self, key: str) -> None:
        """Handle key input for self-connection modal.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'enter':
            # Go back to target selection
            self.state.screen = "connect_target"
        elif key == 'escape':
            self.state.screen = "workspace"
    
    def _handle_cannot_save_empty_key(self, key: str) -> None:
        """Handle key input when trying to save empty plan.
        
        Args:
            key: Key pressed by user.
        """
        if key == 'a':
            # Add block
            self.state.screen = "add_block"
            self.modal_data = {
                'name': '',
                'domain': '',
                'intent': '',
                'kind': 'class',
                'field_index': 0,
            }
            self.modal_cursor = 0
        elif key == 'enter' or key == 'escape':
            self.state.screen = "workspace"
