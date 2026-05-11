"""Main controller for Planner integration."""

from pathlib import Path
from typing import Optional

from bpfw.integrations.editor.screen import clear_screen, read_input
from bpfw.integrations.planner_impl.assembler import BlueprintAssembler, BlueprintYamlWriter
from bpfw.integrations.planner_impl.defaults import AddBoxInput, BoxFactory
from bpfw.integrations.planner_impl.loader import BlueprintStateLoader
from bpfw.integrations.planner_impl.modals import AddBoxModal, ConnectionInput, ConnectionModal
from bpfw.integrations.planner_impl.renderer import WorkspaceRenderer
from bpfw.integrations.planner_impl.validator import PlanValidator


class PlannerController:
    """Orchestrate the complete planner session."""
    
    def __init__(self, project_root: Path) -> None:
        """Initialize the planner controller.
        
        Args:
            project_root: Root directory of the project.
        """
        self.project_root = project_root
        self.state = BlueprintStateLoader.load(project_root)
        self.renderer = WorkspaceRenderer()
        self.validator = PlanValidator()
        self.active_panel = 0  # 0=Structure, 1=Flow, 2=Config
    
    def run(self) -> int:
        """Run the interactive planner session.
        
        Returns:
            Exit code (0 for success, 1 for error).
        """
        # Show initial message
        self._show_welcome_message()
        
        # Main loop
        while True:
            # Render workspace and print it
            rendered = self.renderer.render(self.state)
            print(rendered)
            
            # Read command
            command = read_input("Command> ").strip().lower()
            
            # Handle navigation first
            if command == "j" or command == "down":
                self._navigate_down()
            elif command == "k" or command == "up":
                self._navigate_up()
            elif command == "tab":
                self._cycle_panels()
            # Handle other commands
            elif command == "q" or command == "quit":
                if self.state.dirty:
                    choice = read_input("You have unsaved changes. Save before quitting? [y/N] ").strip().lower()
                    if choice == "y":
                        self._handle_save()
                return 0
            elif command == "a" or command == "add":
                self._handle_add_box()
            elif command == "c" or command == "connect":
                self._handle_connect_boxes()
            elif command == "f":
                self._cycle_source_filter()
            elif command == "g":
                self._cycle_confidence_filter()
            elif command == "x":
                self._accept_suggested_connection()
            elif command == "z":
                self._reject_suggested_connection()
            elif command == "e" or command == "edit" or command == "enter":
                self._handle_configure_box()
            elif command == "p" or command == "project":
                self._handle_project_config()
            elif command == "r" or command == "review":
                self._handle_review()
            elif command == "y" or command == "yaml":
                self._handle_yaml_preview()
            elif command == "s" or command == "save":
                self._handle_save()
            elif command == "h" or command == "help":
                self._show_help()
            else:
                # Check for numeric selection (select box by index)
                if command.isdigit():
                    self._select_box_by_index(int(command) - 1)
                else:
                    print(f"Unknown command: {command}")
                    read_input("Press Enter to continue...")
    
    def _show_welcome_message(self) -> None:
        """Show welcome message based on source mode."""
        clear_screen()
        
        if self.state.source_mode == "new_plan":
            print("No blueprint.yaml found.")
            print("Starting new system plan...")
            print()
        else:
            count = len(self.state.boxes)
            domains = len({box.domain for box in self.state.boxes})
            experimental = sum(1 for box in self.state.boxes if box.lifecycle == "experimental")
            
            print("Loaded blueprint:")
            print(f"  - {count} responsibilities")
            print(f"  - {domains} domains")
            if experimental > 0:
                print(f"  - {experimental} experimental")
            print()
        
        read_input("Press Enter to continue...")
    
    def _handle_add_box(self) -> None:
        """Handle adding a new box."""
        modal = AddBoxModal()
        input_data = modal.collect()
        
        if input_data:
            try:
                box = BoxFactory.create_box(input_data, self.state)
                self.state.boxes.append(box)
                self.state.selected_box_id = box.id
                self.state.dirty = True
                print(f"\nCreated box: {box.name} ({box.id})")
            except ValueError as e:
                print(f"\nError creating box: {e}")
                read_input("Press Enter to continue...")
    
    def _handle_connect_boxes(self) -> None:
        """Handle connecting boxes."""
        if len(self.state.boxes) < 2:
            print("\nNeed at least 2 boxes to connect.")
            read_input("Press Enter to continue...")
            return
        
        modal = ConnectionModal(self.state.boxes)
        input_data = modal.collect()
        
        if input_data:
            # Validate connection
            if input_data.source_box_id == input_data.target_box_id:
                print("\nCannot connect a box to itself.")
                read_input("Press Enter to continue...")
                return
            
            # Check for duplicate connection
            for conn in self.state.connections:
                if (conn.source_box_id == input_data.source_box_id and
                    conn.target_box_id == input_data.target_box_id and
                    conn.relationship == input_data.relationship):
                    print("\nConnection already exists.")
                    read_input("Press Enter to continue...")
                    return
            
            # Add connection
            from bpfw.integrations.planner_impl.models import PlannerConnection
            connection = PlannerConnection(
                source_box_id=input_data.source_box_id,
                target_box_id=input_data.target_box_id,
                relationship=input_data.relationship,
                source_kind="blueprint",
                confidence="high",
                evidence=["manual:connect"],
                status="accepted",
                notes=input_data.notes,
            )
            self.state.connections.append(connection)
            self.state.dirty = True
            print("\nConnection created successfully.")
            read_input("Press Enter to continue...")

    def _cycle_source_filter(self) -> None:
        """Cycle flow source filter."""
        options = ["all", "blueprint", "inferred"]
        current_index = options.index(self.state.flow_source_filter)
        next_index = (current_index + 1) % len(options)
        self.state.flow_source_filter = options[next_index]

    def _cycle_confidence_filter(self) -> None:
        """Cycle flow confidence filter."""
        options = ["all", "high", "medium", "low"]
        current_index = options.index(self.state.flow_confidence_filter)
        next_index = (current_index + 1) % len(options)
        self.state.flow_confidence_filter = options[next_index]

    def _accept_suggested_connection(self) -> None:
        """Accept one suggested connection."""
        candidate_index = self._find_suggested_connection_index()
        if candidate_index is None:
            print("\nNo suggested connection available.")
            read_input("Press Enter to continue...")
            return
        connection = self.state.connections[candidate_index]
        connection.status = "accepted"
        self.state.selected_connection_id = candidate_index
        self.state.dirty = True
        print("\nSuggested connection accepted.")
        read_input("Press Enter to continue...")

    def _reject_suggested_connection(self) -> None:
        """Reject one suggested connection by removing it from state."""
        candidate_index = self._find_suggested_connection_index()
        if candidate_index is None:
            print("\nNo suggested connection available.")
            read_input("Press Enter to continue...")
            return
        del self.state.connections[candidate_index]
        self.state.selected_connection_id = None
        self.state.dirty = True
        print("\nSuggested connection rejected.")
        read_input("Press Enter to continue...")

    def _find_suggested_connection_index(self) -> Optional[int]:
        """Find a suggested connection index, prioritizing current selection."""
        selected_index = self.state.selected_connection_id
        if selected_index is not None and 0 <= selected_index < len(self.state.connections):
            selected = self.state.connections[selected_index]
            if selected.status == "suggested":
                return selected_index
        for index, connection in enumerate(self.state.connections):
            if connection.status == "suggested":
                return index
        return None
    
    def _handle_configure_box(self) -> None:
        """Handle configuring selected box."""
        if not self.state.selected_box_id:
            print("\nNo box selected. Use j/k to select a box.")
            read_input("Press Enter to continue...")
            return
        
        selected_box = None
        for box in self.state.boxes:
            if box.id == self.state.selected_box_id:
                selected_box = box
                break
        
        if not selected_box:
            print("\nSelected box not found.")
            read_input("Press Enter to continue...")
            return
        
        # Show configuration menu
        while True:
            clear_screen()
            print(f"╭──────────── Configure: {selected_box.name} ─────────────╮")
            print(f"│ id: {selected_box.id:<50}│")
            print(f"│ name: {selected_box.name:<47}│")
            print(f"│ intent: {selected_box.intent[:47]:<47}│")
            print(f"│ domain: {selected_box.domain:<46}│")
            print(f"│ lifecycle: {selected_box.lifecycle:<44}│")
            print(f"│ path: {selected_box.path or '(not set)':<48}│")
            print(f"│ symbol: {selected_box.symbol or '(not set)':<46}│")
            print(f"│ symbol_type: {selected_box.symbol_type:<42}│")
            print("│                                                       │")
            print("│ [1] Edit name          [2] Edit domain                 │")
            print("│ [3] Edit intent         [4] Edit lifecycle              │")
            print("│ [5] Edit path          [6] Edit symbol                 │")
            print("│ [7] Edit symbol_type   [8] Edit notes                 │")
            print("│                                                       │")
            print("│ [esc] Back                                           │")
            print("╰───────────────────────────────────────────────────────╯")
            
            choice = read_input("Choice> ").strip().lower()
            
            if choice in ["q", "esc", "back"]:
                break
            
            updates = {}
            
            if choice == "1":
                new_value = read_input("New name> ").strip()
                if new_value:
                    updates["name"] = new_value
            elif choice == "2":
                new_value = read_input("New domain> ").strip()
                if new_value:
                    updates["domain"] = new_value
            elif choice == "3":
                new_value = read_input("New intent> ").strip()
                if new_value:
                    updates["intent"] = new_value
            elif choice == "4":
                print("Available lifecycles:", ", ".join(self.state.project_config.allowed_lifecycles))
                new_value = read_input("New lifecycle> ").strip()
                if new_value:
                    updates["lifecycle"] = new_value
            elif choice == "5":
                new_value = read_input("New path> ").strip()
                updates["path"] = new_value if new_value else None
            elif choice == "6":
                new_value = read_input("New symbol> ").strip()
                updates["symbol"] = new_value if new_value else None
            elif choice == "7":
                print("Available types: class, function, module")
                new_value = read_input("New symbol_type> ").strip()
                if new_value:
                    updates["symbol_type"] = new_value
            elif choice == "8":
                new_value = read_input("New notes (empty to clear)> ").strip()
                updates["notes"] = new_value if new_value else None
            
            if updates:
                updated_box = BoxFactory.update_box(selected_box, updates)
                
                # Replace box in list
                for idx, box in enumerate(self.state.boxes):
                    if box.id == selected_box.id:
                        self.state.boxes[idx] = updated_box
                        selected_box = updated_box
                        self.state.selected_box_id = updated_box.id
                        break
                
                self.state.dirty = True
                print("\nBox updated successfully.")
                read_input("Press Enter to continue...")
    
    def _handle_project_config(self) -> None:
        """Handle project configuration."""
        config = self.state.project_config
        
        clear_screen()
        print("╭──────────── Project Config ─────────────╮")
        print(f"│ Project                                    │")
        print(f"│ id: {config.project_id:<38}│")
        print(f"│ name: {config.project_name:<36}│")
        print(f"│ root: {config.root:<38}│")
        print(f"│ language: {config.language:<34}│")
        print(f"│ source_roots: {', '.join(config.source_roots):<29}│")
        print(f"│ ignored_paths: {', '.join(config.ignored_paths[:3]):<27}│")
        print("│                                            │")
        print("│ Policy                                     │")
        print(f"│ mode: {config.policy_mode:<40}│")
        print(f"│ single_active_per_intent: {str(config.single_active_per_intent):<28}│")
        print("│                                            │")
        print("│ [esc] Back                                 │")
        print("╰────────────────────────────────────────────────╯")
        print("\nProject configuration is read-only in this version.")
        read_input("Press Enter to continue...")
    
    def _handle_review(self) -> None:
        """Handle plan review."""
        # Validate the plan
        validation = self.validator.validate(self.state)
        
        clear_screen()
        print("╭──────────── Plan Review ─────────────╮")
        print(f"│ Project: {self.state.project_config.project_name:<33}│")
        print(f"│ Boxes: {len(self.state.boxes):<37}│")
        print(f"│ Domains: {len({box.domain for box in self.state.boxes}):<33}│")
        print(f"│ Connections: {len(self.state.connections):<31}│")
        print("│                                          │")
        print(f"│ Status: {validation.summary:<35}│")
        print("│                                          │")
        
        if validation.has_errors:
            print("│ Errors:                                   │")
            for error in validation.errors[:5]:  # Show first 5 errors
                print(f"│   - {error.message:<33}│")
            if len(validation.errors) > 5:
                print(f"│   ... and {len(validation.errors) - 5} more{' ' * 28}│")
            print("│                                          │")
        
        if validation.has_warnings:
            print("│ Warnings:                                 │")
            for warning in validation.warnings[:5]:  # Show first 5 warnings
                print(f"│   - {warning.message:<33}│")
            if len(validation.warnings) > 5:
                print(f"│   ... and {len(validation.warnings) - 5} more{' ' * 28}│")
            print("│                                          │")
        
        if validation.allowed:
            print("│ The plan is ready to generate blueprint.yaml.│")
            print("│                                          │")
            print("│ After save, bpfw verify will block until   │")
            print("│ the planned code exists.                   │")
            print("│                                          │")
            print("│ [s] Save blueprint.yaml  [esc] Back      │")
        else:
            print("│ The plan has errors. Fix them before saving.│")
            print("│                                          │")
            print("│ [esc] Back                               │")
        
        print("╰────────────────────────────────────────────────╯")
        
        if validation.allowed:
            choice = read_input("Choice> ").strip().lower()
            if choice == "s":
                self._handle_save()
        else:
            read_input("Press Enter to continue...")
    
    def _handle_yaml_preview(self) -> None:
        """Handle YAML preview."""
        blueprint_data = BlueprintAssembler.assemble(self.state)
        
        try:
            import yaml
        except ImportError:
            print("\nPyYAML is required for YAML preview.")
            read_input("Press Enter to continue...")
            return
        
        clear_screen()
        print("╭──────────── YAML Preview ─────────────╮")
        print("│                                    │")
        print("│ (Press q to exit preview)          │")
        print("│                                    │")
        print("╰────────────────────────────────────────╯")
        
        # Show YAML content
        yaml_str = yaml.dump(blueprint_data, sort_keys=False, allow_unicode=True)
        print(yaml_str)
        print("\n--- End of YAML preview ---")
        read_input("Press Enter to continue...")
    
    def _handle_save(self) -> None:
        """Handle saving the blueprint."""
        # Validate before saving
        validation = self.validator.validate(self.state)
        
        if not validation.allowed:
            print(f"\nCannot save: {validation.summary}")
            for error in validation.errors:
                print(f"  - {error.message}")
            read_input("Press Enter to continue...")
            return
        
        # Assemble and write
        blueprint_data = BlueprintAssembler.assemble(self.state)
        BlueprintYamlWriter.write(self.state.blueprint_path, blueprint_data)
        
        self.state.dirty = False
        
        print(f"\nSaved blueprint to: {self.state.blueprint_path}")
        print("\nNext:")
        print("  1. Ask AI to implement the declared responsibilities.")
        print("  2. Run bpfw verify.")
        print("  3. Fix missing code until blueprint and reality match.")
        read_input("Press Enter to continue...")
    
    def _navigate_down(self) -> None:
        """Navigate to next box using j or down."""
        if not self.state.boxes:
            return
        
        if not self.state.selected_box_id:
            # Select first box
            self.state.selected_box_id = self.state.boxes[0].id
            return
        
        # Find current index and select next
        current_idx = None
        for idx, box in enumerate(self.state.boxes):
            if box.id == self.state.selected_box_id:
                current_idx = idx
                break
        
        if current_idx is not None and current_idx < len(self.state.boxes) - 1:
            self.state.selected_box_id = self.state.boxes[current_idx + 1].id
    
    def _navigate_up(self) -> None:
        """Navigate to previous box using k or up."""
        if not self.state.boxes:
            return
        
        if not self.state.selected_box_id:
            # Select first box
            self.state.selected_box_id = self.state.boxes[0].id
            return
        
        # Find current index and select previous
        current_idx = None
        for idx, box in enumerate(self.state.boxes):
            if box.id == self.state.selected_box_id:
                current_idx = idx
                break
        
        if current_idx is not None and current_idx > 0:
            self.state.selected_box_id = self.state.boxes[current_idx - 1].id
    
    def _cycle_panels(self) -> None:
        """Cycle through panels using TAB: Structure -> Flow -> Config."""
        self.active_panel = (self.active_panel + 1) % 3
    
    def _select_box_by_index(self, index: int) -> None:
        """Select a box by its index in the list."""
        if 0 <= index < len(self.state.boxes):
            self.state.selected_box_id = self.state.boxes[index].id
        else:
            print(f"\nInvalid box index: {index + 1}")
            read_input("Press Enter to continue...")
    
    def _show_help(self) -> None:
        """Show help information."""
        clear_screen()
        print("╭──────────── Help ─────────────╮")
        print("│                               │")
        print("│ Commands:                     │")
        print("│   [a]     Add box           │")
        print("│   [c]     Connect boxes     │")
        print("│   [e]     Configure box     │")
        print("│   [tab]   Cycle panels     │")
        print("│   [p]     Project config    │")
        print("│   [r]     Review plan       │")
        print("│   [y]     YAML preview      │")
        print("│   [s]     Save blueprint    │")
        print("│   [q]     Quit             │")
        print("│   [h]     Help             │")
        print("│                               │")
        print("│ Navigation:                   │")
        print("│   [j/k]   Up/Down boxes     │")
        print("│   [1-9]   Select by index   │")
        print("│   [tab]   Structure->Flow   │")
        print("│           ->Config            │")
        print("│                               │")
        print("╰───────────────────────────────╯")
        read_input("Press Enter to continue...")
