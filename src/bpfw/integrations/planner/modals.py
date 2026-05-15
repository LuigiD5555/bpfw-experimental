"""Modal dialogs for the Planner integration."""

from dataclasses import dataclass
from typing import Optional

from bpfw.catalog.symbol_types import VALID_SYMBOL_TYPES
from bpfw.integrations.editor.screen import read_input, read_line
from bpfw.integrations.planner.defaults import AddBoxInput


@dataclass
class ConnectionInput:
    """Input data for creating a connection."""
    
    source_box_id: str
    target_box_id: str
    relationship: str
    notes: Optional[str] = None


class AddBoxModal:
    """Modal dialog for adding a new box."""
    
    def __init__(self) -> None:
        """Initialize the modal."""
        self._initialized = True
    
    def collect(self) -> Optional[AddBoxInput]:
        """Collect box data from user.
        
        Returns:
            AddBoxInput if user provided data, None if cancelled.
        """
        print("\n╭──────────── Add Box ────────────╮")
        print("│                                 │")
        
        # Collect name
        name = self._collect_field("Name")
        if not name:
            return None
        
        # Collect domain
        domain = self._collect_field("Domain")
        if not domain:
            return None
        
        # Collect purpose
        purpose = self._collect_field("Purpose")
        if not purpose:
            return None
        
        # Collect symbol type
        symbol_type = self._collect_symbol_type()
        if not symbol_type:
            return None
        
        print("│                                 │")
        print("│ [enter] Create  [q] Cancel    │")
        print("╰─────────────────────────────────╯")
        
        choice = input("> ").strip().lower()
        if choice == "q":
            return None
        
        return AddBoxInput(
            name=name,
            domain=domain,
            purpose=purpose,
            symbol_type=symbol_type,
        )
    
    def _collect_field(self, field_name: str) -> Optional[str]:
        """Collect a single field from user.
        
        Args:
            field_name: Name of the field to collect.
        
        Returns:
            Field value or None if cancelled.
        """
        while True:
            print(f"│ {field_name:<32}│")
            value = read_input("> ")
            
            if value.lower() == "q":
                return None
            
            if value.strip():
                return value.strip()
            
            print(f"│ {field_name} cannot be empty.        │")
    
    def _collect_symbol_type(self) -> Optional[str]:
        """Collect symbol type from user.
        
        Returns:
            Symbol type or None if cancelled.
        """
        while True:
            print("│ Type                            │")
            visible_symbol_types = [
                symbol_type for symbol_type in VALID_SYMBOL_TYPES if not symbol_type.startswith("nested_")
            ]
            for index, symbol_type in enumerate(visible_symbol_types, start=1):
                print(f"│   [{index}] {symbol_type:<23}│")
            choice = read_input("> ").strip().lower()
            
            if choice in ["q"]:
                return None
            
            if choice.isdigit() and 1 <= int(choice) <= len(visible_symbol_types):
                return visible_symbol_types[int(choice) - 1]
            if choice in VALID_SYMBOL_TYPES:
                return choice
            
            print("│ Invalid choice. Try again.       │")


class ConnectionModal:
    """Modal dialog for creating connections between boxes."""
    
    VALID_RELATIONSHIPS = [
        "calls",
        "produces_input_for",
        "validates",
        "transforms",
        "exports",
        "replaces",
        "uses",
    ]
    
    def __init__(self, boxes: list) -> None:
        """Initialize the modal.
        
        Args:
            boxes: List of available boxes.
        """
        self.boxes = boxes
        self.box_names = {box.id: box.name for box in boxes}
    
    def collect(self) -> Optional[ConnectionInput]:
        """Collect connection data from user.
        
        Returns:
            ConnectionInput if user provided data, None if cancelled.
        """
        print("\n╭──────────── Connect Blocks ────────────╮")
        print("│                                   │")
        
        # Collect source box
        source_id = self._collect_source_box()
        if not source_id:
            return None
        
        # Collect target box
        target_id = self._collect_target_box(source_id)
        if not target_id:
            return None
        
        # Collect relationship
        relationship = self._collect_relationship()
        if not relationship:
            return None
        
        print("│                                   │")
        print("│ [enter] Connect  [q] Cancel     │")
        print("╰───────────────────────────────────╯")
        
        choice = input("> ").strip().lower()
        if choice == "q":
            return None
        
        return ConnectionInput(
            source_box_id=source_id,
            target_box_id=target_id,
            relationship=relationship,
        )
    
    def _collect_source_box(self) -> Optional[str]:
        """Collect source box from user.
        
        Returns:
            Box ID or None if cancelled.
        """
        print("│ Source box:                      │")
        self._print_box_list()
        
        value = read_input("> ").strip().lower()
        if value in ["q"]:
            return None
        
        # Try to find by index or ID
        return self._find_box_id(value)
    
    def _collect_target_box(self, source_id: str) -> Optional[str]:
        """Collect target box from user.
        
        Args:
            source_id: ID of the source box (to exclude).
        
        Returns:
            Box ID or None if cancelled.
        """
        print("│ Target box:                      │")
        self._print_box_list(exclude_id=source_id)
        
        value = read_input("> ").strip().lower()
        if value in ["q"]:
            return None
        
        # Try to find by index or ID
        return self._find_box_id(value, exclude_id=source_id)
    
    def _collect_relationship(self) -> Optional[str]:
        """Collect relationship type from user.
        
        Returns:
            Relationship type or None if cancelled.
        """
        while True:
            print("│ Relationship:                    │")
            for idx, rel in enumerate(self.VALID_RELATIONSHIPS, 1):
                print(f"│   [{idx}] {rel:<28}│")
            
            value = read_input("> ").strip().lower()
            if value in ["q"]:
                return None
            
            # Check by index
            if value.isdigit():
                idx = int(value) - 1
                if 0 <= idx < len(self.VALID_RELATIONSHIPS):
                    return self.VALID_RELATIONSHIPS[idx]
            
            # Check by name
            if value in self.VALID_RELATIONSHIPS:
                return value
            
            print("│ Invalid relationship.            │")
    
    def _print_box_list(self, exclude_id: Optional[str] = None) -> None:
        """Print list of available boxes.
        
        Args:
            exclude_id: Box ID to exclude from list.
        """
        boxes_to_show = [b for b in self.boxes if b.id != exclude_id]
        
        if not boxes_to_show:
            print("│ (no boxes available)              │")
            return
        
        for idx, box in enumerate(boxes_to_show[:10], 1):  # Limit to 10 for display
            print(f"│   [{idx}] {box.name:<27}│")
        
        if len(boxes_to_show) > 10:
            print(f"│   ... and {len(boxes_to_show) - 10} more              │")
    
    def _find_box_id(self, value: str, exclude_id: Optional[str] = None) -> Optional[str]:
        """Find a box ID by index or ID/name.
        
        Args:
            value: User input value.
            exclude_id: Box ID to exclude.
        
        Returns:
            Box ID or None if not found.
        """
        boxes_to_search = [b for b in self.boxes if b.id != exclude_id]
        
        # Try by index
        if value.isdigit():
            idx = int(value) - 1
            if 0 <= idx < len(boxes_to_search):
                return boxes_to_search[idx].id
        
        # Try by ID
        for box in boxes_to_search:
            if box.id == value:
                return box.id
        
        # Try by name (case-insensitive)
        for box in boxes_to_search:
            if box.name.lower() == value.lower():
                return box.id
        
        print("│ Box not found.                    │")
        return None
