"""UI renderer for Blueprint Planner with Pieces/Assembly/Details layout."""

from pathlib import Path
from typing import Dict, List, Optional

from bpfw.integrations.planner.models import (
    PlannerBox,
    PlannerConnection,
    PlannerState,
    RELATIONSHIP_LABELS,
)
from bpfw.integrations.shared.visual_boxes import render_box
from bpfw.integrations.shared.visual_theme import (
    DEFAULT_THEME,
    compute_panel_width,
    render_commands_box,
    render_header,
)
from bpfw.integrations.editor.screen import get_terminal_width, clear_screen


PLANNER_TITLE = "Blueprint Planner"


def _resolve_uniform_width(terminal_width: int, panels: List[tuple[str, List[str]]]) -> int:
    """Compute one shared panel width for a screen.

    Width is based on the longest title/content among given panels and
    constrained by theme limits (50% min, 95% max of terminal width).
    """
    panel_widths = [
        compute_panel_width(
            content_lines=lines,
            title=title,
            terminal_width=terminal_width,
            theme=DEFAULT_THEME,
        )
        for title, lines in panels
    ]
    if not panel_widths:
        return compute_panel_width(
            content_lines=[],
            title="",
            terminal_width=terminal_width,
            theme=DEFAULT_THEME,
        )
    return max(panel_widths)


def render_planner(state: PlannerState) -> None:
    """Main entry point: render appropriate screen based on state.screen.

    Args:
        state: Current planner state.
    """
    if state.screen == "welcome":
        render_welcome(state)
    elif state.screen == "workspace":
        render_workspace(state)
    elif state.screen == "add_block":
        render_add_block_modal(state)
    elif state.screen == "connect_target":
        render_connect_target_modal(state)
    elif state.screen == "connect_meaning":
        render_connect_meaning_modal(state)
    elif state.screen == "connect_feedback":
        render_connect_feedback_modal(state)
    elif state.screen == "edit_block":
        render_edit_block_modal(state)
    elif state.screen == "edit_inputs":
        render_edit_inputs_modal(state)
    elif state.screen == "edit_output":
        render_edit_output_modal(state)
    elif state.screen == "project_settings":
        render_project_settings_modal(state)
    elif state.screen == "review":
        render_review_modal(state)
    elif state.screen == "yaml_preview":
        render_yaml_preview_modal(state)
    elif state.screen == "saved":
        render_saved_modal(state)
    elif state.screen == "graph_overview":
        render_graph_overview(state)
    elif state.screen == "disconnect":
        render_disconnect_modal(state)
    elif state.screen == "removed_connection":
        render_removed_connection_modal(state)
    elif state.screen == "delete_block":
        render_delete_block_modal(state)
    elif state.screen == "unsaved_changes":
        render_unsaved_changes_modal(state)
    elif state.screen == "broken_connections":
        render_broken_connections_modal(state)
    elif state.screen == "no_blocks_to_connect":
        render_no_blocks_to_connect_modal(state)
    elif state.screen == "duplicate_connection":
        existing_connection = state.modal_data.get("existing_connection")
        if isinstance(existing_connection, PlannerConnection):
            render_duplicate_connection_modal(state, existing_connection)
        else:
            render_workspace(state)
    elif state.screen == "self_connection":
        render_self_connection_modal(state)
    elif state.screen == "cannot_save_empty":
        render_cannot_save_empty_modal(state)
    elif state.screen == "blueprint_locked":
        render_blueprint_locked_modal(state)
    elif state.screen == "invalid_blueprint":
        render_invalid_blueprint_modal(state)
    elif state.screen == "duplicate_name":
        render_workspace(state)
    elif state.screen == "active_intent_conflict":
        render_workspace(state)
    elif state.screen == "path_already_used":
        path = str(state.modal_data.get("path") or "")
        existing_box = state.modal_data.get("existing_box")
        if path and isinstance(existing_box, PlannerBox):
            render_path_already_used_modal(state, path, existing_box)
        else:
            render_workspace(state)
    elif state.screen == "domain_changed":
        old_domain = str(state.modal_data.get("old_domain") or "")
        new_domain = str(state.modal_data.get("new_domain") or "")
        current_path = str(state.modal_data.get("current_path") or "")
        suggested_path = str(state.modal_data.get("suggested_path") or "")
        if old_domain and new_domain and current_path and suggested_path:
            render_domain_changed_modal(state, old_domain, new_domain, current_path, suggested_path)
        else:
            render_workspace(state)
    elif state.screen == "no_connections_warning":
        render_no_connections_warning_modal(state)
    elif state.screen == "experimental_to_active_warning":
        render_workspace(state)
    else:
        render_workspace(state)


# ---------------------------------------------------------------------------
# Welcome Screen
# ---------------------------------------------------------------------------

def render_welcome(state: PlannerState) -> None:
    """Render welcome screen when starting planner.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    if state.source_mode == "new_plan":
        # No blueprint.yaml found
        lines = [
            "No blueprint.yaml found.",
            "",
            "This planner lets you assemble your system as blocks.",
            "Each block becomes one responsibility in blueprint.yaml.",
            "",
            f"Project detected: {state.project_config.project_name}",
            f"Language: {state.project_config.language}",
            f"Source root: {', '.join(state.project_config.source_roots)}",
        ]
        command_lines = [
            "[enter] Start planning",
            "[q] Quit",
        ]
    elif state.source_mode == "empty_blueprint":
        lines = [
            "bpfw/blueprint.yaml exists but has no responsibilities.",
            "",
            "Planner will start a new system plan using this file.",
            "",
            f"Project detected: {state.project_config.project_name}",
            f"Language: {state.project_config.language}",
            f"Source root: {', '.join(state.project_config.source_roots)}",
        ]
        command_lines = [
            "[enter] Continue",
            "[q] Quit",
        ]
    else:
        # Existing blueprint.yaml
        lines = [
            "Loaded existing blueprint.yaml.",
            "",
            f"Blocks: {len(state.boxes)}",
            f"Domains: {len(set(b.domain for b in state.boxes))}",
            f"Connections: {len(state.connections)}",
            "",
            "Continue assembling new planned blocks into the same",
            "blueprint.",
        ]
        command_lines = [
            "[enter] Continue",
            "[q] Quit",
        ]

    width = _resolve_uniform_width(
        terminal_width=terminal_width,
        panels=[(PLANNER_TITLE, []), ("", lines), ("Commands", command_lines)],
    )
    for line in render_header(title=PLANNER_TITLE, width=width, theme=DEFAULT_THEME):
        print(line)
    print()
    for line in render_box(title="", lines=lines, width=width):
        print(line)
    print()
    for line in render_commands_box(lines=command_lines, width=width, theme=DEFAULT_THEME):
        print(line)


# ---------------------------------------------------------------------------
# Workspace (Pieces | Assembly | Details)
# ---------------------------------------------------------------------------

def render_workspace(state: PlannerState) -> None:
    """Render main workspace with Pieces/Assembly/Details panels.

    Args:
        state: Current planner state.
    """
    clear_screen()
    
    # Render stacked panels in a single column
    terminal_width = get_terminal_width()
    
    # Get selected box
    selected_box = None
    for box in state.boxes:
        if box.id == state.selected_box_id:
            selected_box = box
            break
    
    # Get connections for selected box
    incoming = []
    outgoing = []
    if selected_box:
        for conn in state.connections:
            if conn.target_box_id == selected_box.id:
                source_box = next((b for b in state.boxes if b.id == conn.source_box_id), None)
                if source_box:
                    incoming.append((source_box, conn))
            elif conn.source_box_id == selected_box.id:
                target_box = next((b for b in state.boxes if b.id == conn.target_box_id), None)
                if target_box:
                    outgoing.append((target_box, conn))
    
    # Render panel content
    pieces_lines = render_pieces_panel_internal(
        state.boxes,
        state.selected_box_id,
        filter_text=state.pieces_filter,
        filter_mode=state.pieces_filter_mode,
    )
    assembly_lines = render_assembly_panel_internal(selected_box, incoming, outgoing)
    details_lines = render_details_panel_internal(selected_box)
    panel_width = _resolve_uniform_width(
        terminal_width=terminal_width,
        panels=[
            ("Pieces: system blocks", pieces_lines),
            (f"Assembly: {selected_box.name if selected_box else 'select a block'}", assembly_lines),
            ("Details", details_lines),
            ("Commands", ["↑↓ Move   [a] Add block   [space] Connect   [x] Disconnect   [tab] Edit   [s] Save   [p] Project   [q] Quit"]),
        ],
    )

    pieces_panel = list(render_box(title="Pieces: system blocks", lines=pieces_lines, width=panel_width))
    assembly_panel = list(
        render_box(
            title=f"Assembly: {selected_box.name if selected_box else 'select a block'}",
            lines=assembly_lines,
            width=panel_width,
        )
    )
    details_panel = list(render_box(title="Details", lines=details_lines, width=panel_width))

    for line in pieces_panel:
        print(line)
    print()
    for line in assembly_panel:
        print(line)
    print()
    for line in details_panel:
        print(line)
    print()
    command_lines = [
        "↑↓ Move   [a] Add block   [space] Connect   [/] Filter",
        "[x] Disconnect   [tab] Edit   [s] Save",
        "[p] Project   [q] Quit",
    ]
    for line in render_commands_box(lines=command_lines, width=panel_width, theme=DEFAULT_THEME):
        print(line)


def render_pieces_panel_internal(
    boxes: List[PlannerBox],
    selected_id: Optional[str],
    filter_text: str = "",
    filter_mode: bool = False,
) -> List[str]:
    """Render pieces panel content.

    Args:
        boxes: List of boxes to display.
        selected_id: ID of selected box.

    Returns:
        List of lines for the panel.
    """
    if not boxes:
        return [
            "These are the blocks your",
            "system will have.",
            "",
            "No blocks yet.",
            "",
            "Press [a] to add your",
            "first block.",
        ]
    
    filtered_boxes = boxes
    normalized_filter = filter_text.strip().lower()
    if normalized_filter:
        filtered_boxes = [
            box for box in boxes
            if normalized_filter in box.name.lower()
            or normalized_filter in box.domain.lower()
            or normalized_filter in box.intent.lower()
        ]

    if not filtered_boxes:
        filter_prompt = filter_text if filter_text else "_"
        if filter_mode:
            filter_prompt = f"{filter_prompt} (typing)"
        return [
            f"Filter: {filter_prompt}",
            "",
            "No matching blocks.",
            "",
            "Press [/] to edit filter",
            "or [esc] to clear it.",
        ]

    ordered_boxes = sorted(filtered_boxes, key=lambda box: (box.domain, box.name))
    
    filter_prompt = filter_text if filter_text else "_"
    if filter_mode:
        filter_prompt = f"{filter_prompt} (typing)"

    lines = [f"Filter: {filter_prompt}", "Select a block with ↑ ↓"]
    lines.append("")

    max_visible_blocks = 16
    selected_index = next((index for index, box in enumerate(ordered_boxes) if box.id == selected_id), 0)
    start_index = max(0, selected_index - (max_visible_blocks // 2))
    end_index = min(len(ordered_boxes), start_index + max_visible_blocks)
    if end_index - start_index < max_visible_blocks:
        start_index = max(0, end_index - max_visible_blocks)

    visible_boxes = ordered_boxes[start_index:end_index]

    last_domain = None
    for box in visible_boxes:
        if box.domain != last_domain:
            lines.append(box.domain)
            last_domain = box.domain
        marker = ">" if box.id == selected_id else " "
        lines.append(f"{marker} {box.name}")

    hidden_before = start_index
    hidden_after = len(ordered_boxes) - end_index
    if hidden_before > 0 or hidden_after > 0:
        lines.append("")
        lines.append(f"Showing {start_index + 1}-{end_index} of {len(ordered_boxes)}")
        lines.append("Use ↑↓ to scroll, [/] to narrow list.")

    return lines


def render_assembly_panel_internal(
    selected_box: Optional[PlannerBox],
    incoming: List[tuple],
    outgoing: List[tuple],
) -> List[str]:
    """Render assembly panel content.

    Args:
        selected_box: Currently selected box.
        incoming: List of (source_box, connection) tuples.
        outgoing: List of (target_box, connection) tuples.

    Returns:
        List of lines for the panel.
    """
    if not selected_box:
        return [
            "",
            "Nothing selected yet.",
            "",
            "Add a block first, then",
            "connect it to other",
            "blocks with [space].",
        ]
    
    lines = []
    
    if not incoming and not outgoing:
        # No connections
        lines.append("")
        lines.append(f"                [ {selected_box.name} ]")
        lines.append("")
        lines.append("")
        lines.append("This block is not connected yet.")
        lines.append("")
        lines.append("Press [space] to connect it to")
        lines.append("another block.")
        return lines
    
    # Incoming connections
    if incoming:
        lines.append("")
        lines.append("Incoming")
        for source_box, conn in incoming:
            label = RELATIONSHIP_LABELS.get(conn.relationship, conn.relationship)
            lines.append(f"  {source_box.name}")
            lines.append(f"     └─ {label}")
        lines.append("")
    
    # Center the selected box
    lines.append(f"                 [ {selected_box.name} ]")
    lines.append("")
    
    # Outgoing connections
    if outgoing:
        lines.append("Outgoing")
        for i, (target_box, conn) in enumerate(outgoing):
            label = RELATIONSHIP_LABELS.get(conn.relationship, conn.relationship)
            prefix = "├─" if i < len(outgoing) - 1 else "└─"
            lines.append(f"  {prefix} {label} → {target_box.name}")
    
    lines.append("")
    lines.append("Press [space] to add another connection.")
    if outgoing:
        lines.append("Press [x] to remove a connection.")
    
    return lines


def render_details_panel_internal(selected_box: Optional[PlannerBox]) -> List[str]:
    """Render details panel content.

    Args:
        selected_box: Currently selected box.

    Returns:
        List of lines for the panel.
    """
    if not selected_box:
        return [
            "No block selected.",
            "",
            "",
            "Details will show intent,",
            "path, interface and",
            "lifecycle for the",
            "selected block.",
        ]
    
    lines = []
    
    # Purpose
    lines.append(f"Purpose   {selected_box.intent}")
    lines.append(f"Status    {selected_box.lifecycle}")
    lines.append(f"Path      {selected_box.path or 'not set'}")
    
    if selected_box.symbol:
        lines.append(f"Symbol    {selected_box.symbol}")
        lines.append(f"Kind      {selected_box.symbol_type}")
    
    # Interface (compact format)
    if selected_box.interface:
        inputs_str = ", ".join([f"{inp.name}:{inp.type}" for inp in selected_box.interface.inputs])
        if selected_box.interface.output:
            output_str = selected_box.interface.output.type
            lines.append(f"Interface {inputs_str} → {output_str}")
        else:
            lines.append(f"Interface {inputs_str}")
    else:
        lines.append("Interface not configured")
    
    lines.append("")
    lines.append("[tab] Edit details")
    
    return lines


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

def render_add_block_modal(state: PlannerState) -> None:
    """Render add block modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        "A block is one responsibility your system needs.",
        "",
        "Name",
        "> _",
        "",
        "Domain",
        "> _",
        "",
        "Purpose",
        "> _",
        "",
        "Kind",
        "> class",
        "",
        "[enter] Create block",
        "[esc] Cancel",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Add Block", lines)])

    for line in render_box(title="Add Block", lines=lines, width=width):
        print(line)


def render_connect_target_modal(state: PlannerState) -> None:
    """Render connect target selection modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    selected_box = next((b for b in state.boxes if b.id == state.selected_box_id), None)
    
    if not selected_box:
        return
    
    # Get available targets (all boxes except selected), stable ordering.
    targets = sorted([b for b in state.boxes if b.id != state.selected_box_id], key=lambda box: box.name)
    
    lines = [
        "From",
        f"  [ {selected_box.name} ]",
        "",
        "Choose which block receives its output:",
        "",
    ]
    
    selected_target_id = state.modal_data.get("target_id")
    for target in targets:
        marker = ">" if target.id == selected_target_id else " "
        lines.append(f"{marker} {target.name}")
    
    lines.extend([
        "",
        "↑↓ Move   [enter] Select target   [esc] Cancel",
    ])
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Connect Block", lines)])

    for line in render_box(title="Connect Block", lines=lines, width=width):
        print(line)


def render_connect_meaning_modal(state: PlannerState) -> None:
    """Render connection meaning selection modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    source_id = state.selected_box_id
    target_id = state.modal_data.get("target_id")
    source_box = next((box for box in state.boxes if box.id == source_id), None)
    target_box = next((box for box in state.boxes if box.id == target_id), None)

    summary_line = ""
    if source_box and target_box:
        summary_line = f"{source_box.name}  →  {target_box.name}"

    lines = [
        summary_line,
        "",
        "What does this connection mean?",
        "",
        "> sends output to",
        "  uses",
        "  validates",
        "  transforms",
        "  exports to",
        "  replaces",
        "",
        "Recommended: sends output to",
        "",
        "[enter] Accept   [esc] Cancel",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Connection Meaning", lines)])

    for line in render_box(title="Connection Meaning", lines=lines, width=width):
        print(line)


def render_connect_feedback_modal(state: PlannerState) -> None:
    """Render connection feedback modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    source_id = state.modal_data.get("source_id")
    target_id = state.modal_data.get("target_id")
    relationship = state.modal_data.get("relationship")

    source_box = next((box for box in state.boxes if box.id == source_id), None)
    target_box = next((box for box in state.boxes if box.id == target_id), None)
    relationship_label = RELATIONSHIP_LABELS.get(relationship, str(relationship or "connected to"))

    source_name = source_box.name if source_box else str(source_id or "source")
    target_name = target_box.name if target_box else str(target_id or "target")

    lines = [
        source_name,
        f"   │ {relationship_label}",
        "   v",
        target_name,
        "",
        "[enter] Continue",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Connected", lines)])

    for line in render_box(title="Connected", lines=lines, width=width):
        print(line)


def render_edit_block_modal(state: PlannerState) -> None:
    """Render edit block modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    selected_box = next((b for b in state.boxes if b.id == state.selected_box_id), None)
    
    if not selected_box:
        return
    
    lines = [
        "",
        "Identity",
        "[1] Purpose      " + selected_box.intent,
        "[2] Domain       " + selected_box.domain,
        "[3] Status       " + selected_box.lifecycle,
        "",
        "Location",
        "[4] Path         " + (selected_box.path or "not set"),
        "[5] Symbol       " + (selected_box.symbol or "not set"),
        "[6] Kind         " + selected_box.symbol_type,
        "",
        "Interface",
        "[7] Inputs       " + ("configured" if selected_box.interface and selected_box.interface.inputs else "not configured"),
        "[8] Output       " + ("configured" if selected_box.interface and selected_box.interface.output else "not configured"),
        "",
        "[number] Edit field   [enter] Accept   [esc] Cancel",
    ]
    edit_block_title = f"Edit Block: {selected_box.name}"
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[(edit_block_title, lines)])

    for line in render_box(title=edit_block_title, lines=lines, width=width):
        print(line)


def render_edit_inputs_modal(state: PlannerState) -> None:
    """Render edit inputs modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    selected_box = next((b for b in state.boxes if b.id == state.selected_box_id), None)
    
    if not selected_box:
        return
    
    lines = [
        "Inputs are values this block needs to do its job.",
        "",
    ]
    
    if selected_box.interface and selected_box.interface.inputs:
        lines.append("Configured inputs")
        lines.append("")
        for inp in selected_box.interface.inputs:
            required = "required" if inp.required else "optional"
            lines.append(f"> {inp.name}: {inp.type} {required}")
            if inp.description:
                lines.append(f"  {inp.description}")
    else:
        lines.append("No inputs configured.")
    
    lines.extend([
        "",
        "[a] Add input   [e] Edit selected   [d] Delete   [enter] Back",
    ])
    inputs_title = f"Inputs: {selected_box.name}"
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[(inputs_title, lines)])

    for line in render_box(title=inputs_title, lines=lines, width=width):
        print(line)


def render_edit_output_modal(state: PlannerState) -> None:
    """Render edit output modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    selected_box = next((b for b in state.boxes if b.id == state.selected_box_id), None)
    
    if not selected_box:
        return
    
    output_type = selected_box.interface.output.type if selected_box.interface and selected_box.interface.output else ""
    output_desc = selected_box.interface.output.description if selected_box.interface and selected_box.interface.output else ""
    
    lines = [
        "Output is what this block returns or produces.",
        "",
        "Type",
        f"> {output_type}",
        "",
        "Description",
        f"> {output_desc}",
        "",
        "[enter] Save output   [esc] Cancel",
    ]
    output_title = f"Output: {selected_box.name}"
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[(output_title, lines)])

    for line in render_box(title=output_title, lines=lines, width=width):
        print(line)


def render_project_settings_modal(state: PlannerState) -> None:
    """Render project settings modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    config = state.project_config
    
    lines = [
        "These settings apply to the whole blueprint.",
        "Most projects can keep the defaults.",
        "",
        "Project",
        "[1] id            " + config.project_id,
        "[2] name          " + config.project_name,
        "[3] language      " + config.language,
        "[4] source_roots  " + ", ".join(config.source_roots),
        "[5] ignored_paths " + ", ".join(config.ignored_paths[:5]) + ("..." if len(config.ignored_paths) > 5 else ""),
        "",
        "Policy",
        "[6] mode                         " + config.policy_mode,
        "[7] block on drift               " + str(config.defined_blueprint_blocks_on_drift),
        "[8] one active per intent        " + str(config.single_active_per_intent),
        "[9] block undeclared code        " + str(config.undeclared_code_blocks),
        "[10] block missing declared code  " + str(config.missing_declared_code_blocks),
        "",
        "[number] Edit   [r] Reset defaults   [enter] Accept   [esc] Cancel",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Project Settings", lines)])

    for line in render_box(title="Project Settings", lines=lines, width=width):
        print(line)


def render_review_modal(state: PlannerState) -> None:
    """Render plan review modal before saving.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    domains = len(set(b.domain for b in state.boxes))
    boxes_with_interface = sum(1 for b in state.boxes if b.interface)
    
    lines = [
        f"Project: {state.project_config.project_name}",
        f"Blocks: {len(state.boxes)}",
        f"Domains: {domains}",
        f"Connections: {len(state.connections)}",
        f"Interfaces configured: {boxes_with_interface} of {len(state.boxes)}",
        "",
        "Expected after save:",
        "bpfw verify will block until this code exists.",
        "",
        "Missing planned code:",
    ]
    
    # Add boxes that don't have code yet
    for box in sorted(state.boxes, key=lambda b: b.path or ""):
        if box.path:
            lines.append(f"- {box.path} :: {box.symbol or box.name}")
    
    lines.extend([
        "",
        "[s] Save blueprint.yaml",
        "[y] Preview YAML",
        "[esc] Back",
    ])
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Plan Review", lines)])

    for line in render_box(title="Plan Review", lines=lines, width=width):
        print(line)


def render_yaml_preview_modal(state: PlannerState) -> None:
    """Render YAML preview modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        f"version: 1",
        f"project:",
        f"  id: {state.project_config.project_id}",
        f"  name: {state.project_config.project_name}",
        f"  language: {state.project_config.language}",
        f"  source_roots: {state.project_config.source_roots}",
        "",
        f"responsibilities:",
    ]
    
    for box in sorted(state.boxes, key=lambda b: b.id)[:3]:  # Show first 3
        lines.append(f"  - {box.id}")
        lines.append(f"    name: {box.name}")
        lines.append(f"    domain: {box.domain}")
        lines.append(f"    intent: {box.intent}")
        if box.path:
            lines.append(f"    location:")
            lines.append(f"      path: {box.path}")
            lines.append(f"      symbol: {box.symbol or box.name}")
        lines.append("")
    
    if len(state.boxes) > 3:
        lines.append(f"  ... {len(state.boxes) - 3} more blocks")
    
    lines.extend([
        "",
        "[f] Full YAML   [enter] Back",
    ])
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("YAML Preview", lines)])

    for line in render_box(title="YAML Preview", lines=lines, width=width):
        print(line)


def render_saved_modal(state: PlannerState) -> None:
    """Render saved confirmation modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        "blueprint.yaml saved.",
        "",
        "Next step:",
        "Ask your AI tool to implement the planned",
        "blocks without changing blueprint.yaml.",
        "",
        "Then run:",
        "  bpfw verify",
        "",
        "[enter] Back to planner",
        "[q] Quit",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Saved", lines)])

    for line in render_box(title="Saved", lines=lines, width=width):
        print(line)


def render_graph_overview(state: PlannerState) -> None:
    """Render graph overview modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = []
    
    for conn in sorted(state.connections, key=lambda c: c.source_box_id):
        source_box = next((b for b in state.boxes if b.id == conn.source_box_id), None)
        target_box = next((b for b in state.boxes if b.id == conn.target_box_id), None)
        
        if source_box and target_box:
            label = RELATIONSHIP_LABELS.get(conn.relationship, conn.relationship)
            lines.append(f"{source_box.name}")
            lines.append(f"  └─ {label} → {target_box.name}")
            lines.append("")
    
    lines.append("[enter] Back")
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Assembly Overview", lines)])

    for line in render_box(title="Assembly Overview", lines=lines, width=width):
        print(line)


def render_disconnect_modal(state: PlannerState) -> None:
    """Render disconnect connection modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    selected_box = next((b for b in state.boxes if b.id == state.selected_box_id), None)
    
    if not selected_box:
        return
    
    # Get connections for selected box
    incoming = []
    outgoing = []
    for conn in state.connections:
        if conn.target_box_id == selected_box.id:
            source_box = next((b for b in state.boxes if b.id == conn.source_box_id), None)
            if source_box:
                incoming.append((source_box, conn))
        elif conn.source_box_id == selected_box.id:
            target_box = next((b for b in state.boxes if b.id == conn.target_box_id), None)
            if target_box:
                outgoing.append((target_box, conn))
    
    lines = [
        f"Connections for {selected_box.name}",
        "",
    ]
    
    # Incoming connections
    if incoming:
        lines.append("Incoming")
        for i, (source_box, conn) in enumerate(incoming, 1):
            label = RELATIONSHIP_LABELS.get(conn.relationship, conn.relationship)
            lines.append(f"[{i}] {source_box.name} {label} {selected_box.name}")
        lines.append("")
    
    # Outgoing connections
    if outgoing:
        lines.append("Outgoing")
        offset = len(incoming)
        for i, (target_box, conn) in enumerate(outgoing, offset + 1):
            label = RELATIONSHIP_LABELS.get(conn.relationship, conn.relationship)
            lines.append(f"[{i}] {selected_box.name} {label} {target_box.name}")
    
    selected_index = state.modal_cursor + 1
    lines.extend([
        "",
        "Choose connection to remove:",
        f"> {selected_index}",
        "",
        "[enter] Remove   [esc] Cancel",
    ])
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Remove Connection", lines)])

    for line in render_box(title="Remove Connection", lines=lines, width=width):
        print(line)


def render_delete_block_modal(state: PlannerState) -> None:
    """Render delete block confirmation modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    selected_box = next((b for b in state.boxes if b.id == state.selected_box_id), None)
    
    if not selected_box:
        return
    
    # Get connections for selected box
    connections = []
    for conn in state.connections:
        if conn.source_box_id == selected_box.id or conn.target_box_id == selected_box.id:
            connections.append(conn)
    
    lines = [f"{selected_box.name} has connections:"]
    
    if connections:
        lines.append("")
        lines.append("Incoming")
        for conn in connections:
            if conn.target_box_id == selected_box.id:
                source_box = next((b for b in state.boxes if b.id == conn.source_box_id), None)
                if source_box:
                    label = RELATIONSHIP_LABELS.get(conn.relationship, conn.relationship)
                    lines.append(f"- {source_box.name} {label} {selected_box.name}")
        
        lines.append("Outgoing")
        for conn in connections:
            if conn.source_box_id == selected_box.id:
                target_box = next((b for b in state.boxes if b.id == conn.target_box_id), None)
                if target_box:
                    label = RELATIONSHIP_LABELS.get(conn.relationship, conn.relationship)
                    lines.append(f"- {selected_box.name} {label} {target_box.name}")
    else:
        lines.append("")
        lines.append("No connections.")
    
    lines.extend([
        "",
        "Delete this block and its connections?",
        "",
        "[d] Delete block and connections",
        "[esc] Cancel",
    ])
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Delete Block", lines)])

    for line in render_box(title="Delete Block", lines=lines, width=width):
        print(line)


def render_unsaved_changes_modal(state: PlannerState) -> None:
    """Render unsaved changes modal.

    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    # Build change summary
    change_lines = []
    if state.boxes_added > 0:
        change_lines.append(f"Blocks added: {state.boxes_added}")
    if state.boxes_edited > 0:
        change_lines.append(f"Details changed: {state.boxes_edited}")
    if state.boxes_deleted > 0:
        change_lines.append(f"Blocks deleted: {state.boxes_deleted}")
    if state.connections_added > 0:
        change_lines.append(f"Connections added: {state.connections_added}")
    if state.connections_removed > 0:
        change_lines.append(f"Connections removed: {state.connections_removed}")
    
    if not change_lines:
        change_lines.append("No unsaved changes.")
    
    lines = [
        "You have unsaved planner changes.",
        "",
    ] + change_lines + [
        "",
        "[s] Save and quit",
        "[q] Quit without saving",
        "[esc] Back",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Unsaved Changes", lines)])

    for line in render_box(title="Unsaved Changes", lines=lines, width=width):
        print(line)


def render_removed_connection_modal(state: PlannerState) -> None:
    """Render confirmation after removing a connection."""
    clear_screen()
    terminal_width = get_terminal_width()

    source_name = str(state.modal_data.get("source_name") or "source")
    target_name = str(state.modal_data.get("target_name") or "target")

    lines = [
        "Removed connection:",
        f"{source_name} → {target_name}",
        "",
        "[enter] Continue",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Removed", lines)])

    for line in render_box(title="Removed", lines=lines, width=width):
        print(line)


def render_broken_connections_modal(state: PlannerState) -> None:
    """Render broken connections warning modal.
    
    Args:
        state: Current planner state with broken connections.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        "Some connections point to blocks that",
        "no longer exist.",
        "",
    ]
    
    if not state.broken_connections:
        lines.append("No broken connections found.")
    else:
        lines.append("Broken connections:")
        for conn in state.broken_connections:
            source_label = conn.source_box_id or "unknown"
            target_label = conn.target_box_id or "unknown"
            relationship_label = RELATIONSHIP_LABELS.get(conn.relationship, conn.relationship)
            lines.append(f"- {source_label} {relationship_label} {target_label}")
    
    lines.extend([
        "",
        "[r] Remove broken connections",
        "[k] Keep and review later",
        "[q] Quit",
    ])
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Broken Assembly", lines)])

    for line in render_box(title="Broken Assembly", lines=lines, width=width):
        print(line)


def render_no_blocks_to_connect_modal(state: PlannerState) -> None:
    """Render modal when there are no other blocks to connect to.
    
    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    selected_box = next((b for b in state.boxes if b.id == state.selected_box_id), None)
    box_name = selected_box.name if selected_box else "This block"

    lines = [
        f"{box_name} cannot be connected yet.",
        "",
        "There are no other blocks in the plan.",
        "",
        "Add another block first with [a].",
        "",
        "[a] Add block",
        "[enter] Back",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Connect Block", lines)])

    for line in render_box(title="Connect Block", lines=lines, width=width):
        print(line)


def render_duplicate_connection_modal(state: PlannerState, existing_conn: PlannerConnection) -> None:
    """Render modal when trying to create a duplicate connection.
    
    Args:
        state: Current planner state.
        existing_conn: The existing duplicate connection.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    source_box = next((b for b in state.boxes if b.id == existing_conn.source_box_id), None)
    target_box = next((b for b in state.boxes if b.id == existing_conn.target_box_id), None)
    
    source_name = source_box.name if source_box else existing_conn.source_box_id
    target_name = target_box.name if target_box else existing_conn.target_box_id
    relationship_label = RELATIONSHIP_LABELS.get(existing_conn.relationship, existing_conn.relationship)

    lines = [
        "This connection already exists:",
        "",
        f"{source_name}",
        f"   │ {relationship_label}",
        f"   v",
        f"{target_name}",
        "",
        "[enter] Back",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Already Connected", lines)])

    for line in render_box(title="Already Connected", lines=lines, width=width):
        print(line)


def render_self_connection_modal(state: PlannerState) -> None:
    """Render modal when trying to connect a block to itself.
    
    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        "A block cannot connect to itself.",
        "",
        "Select a different target block.",
        "",
        "[enter] Choose another target",
        "[esc] Cancel",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Invalid Connection", lines)])

    for line in render_box(title="Invalid Connection", lines=lines, width=width):
        print(line)


def render_cannot_save_empty_modal(state: PlannerState) -> None:
    """Render modal when trying to save without any blocks.
    
    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        "There are no blocks in this plan.",
        "",
        "Add at least one block before saving",
        "blueprint.yaml.",
        "",
        "[a] Add block",
        "[enter] Back",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Nothing To Save", lines)])

    for line in render_box(title="Nothing To Save", lines=lines, width=width):
        print(line)


def render_duplicate_name_modal(state: PlannerState, existing_box: PlannerBox, suggested_names: List[str]) -> None:
    """Render modal when trying to create duplicate block name.
    
    Args:
        state: Current planner state.
        existing_box: Existing box with duplicate name.
        suggested_names: List of suggested alternative names.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        f"A block named {existing_box.name} already exists in {existing_box.domain}.",
        "",
        "Suggested names:",
    ]
    
    for i, name in enumerate(suggested_names[:3]):
        marker = ">" if i == 0 else " "
        lines.append(f"{marker} {name}")
    
    lines.extend([
        "",
        "[enter] Use selected suggestion",
        "[e] Edit name",
        "[esc] Cancel",
    ])
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Duplicate Name", lines)])

    for line in render_box(title="Duplicate Name", lines=lines, width=width):
        print(line)


def render_active_intent_conflict_modal(state: PlannerState, existing_box: PlannerBox, new_intent: str) -> None:
    """Render modal when creating block with duplicate active intent.
    
    Args:
        state: Current planner state.
        existing_box: Existing active box with same intent.
        new_intent: The conflicting intent/purpose.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        "Another active block already has this purpose:",
        "",
        "Existing",
        f"- {existing_box.name}",
        f"  {existing_box.intent}",
        "",
        "New",
        f"- (your new block)",
        f"  {new_intent}",
        "",
        "BPFW allows only one active block per intent.",
        "",
        "Choose what this new block is:",
        "> experimental",
        "  legacy",
        "  deprecated",
        "  edit purpose",
        "",
        "[enter] Apply",
        "[esc] Cancel",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Active Intent Conflict", lines)])

    for line in render_box(title="Active Intent Conflict", lines=lines, width=width):
        print(line)


def render_path_already_used_modal(state: PlannerState, path: str, existing_box: PlannerBox) -> None:
    """Render modal when path is already used by another block.
    
    Args:
        state: Current planner state.
        path: The duplicate path.
        existing_box: Existing box using this path.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    # Generate suggested alternative path
    import re
    base_name = Path(path).stem
    suggested_path = str(Path(path).parent / f"{base_name}_v2{Path(path).suffix}")

    lines = [
        "This path is already assigned to another block:",
        "",
        path,
        "",
        f"Used by: {existing_box.name}",
        f"New block: (your new block)",
        "",
        "Suggested path:",
        f"{suggested_path}",
        "",
        "[enter] Use suggestion",
        "[e] Edit path",
        "[esc] Cancel",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Path Already Used", lines)])

    for line in render_box(title="Path Already Used", lines=lines, width=width):
        print(line)


def render_domain_changed_modal(state: PlannerState, old_domain: str, new_domain: str, current_path: str, suggested_path: str) -> None:
    """Render modal when domain changes and path may be inconsistent.
    
    Args:
        state: Current planner state.
        old_domain: Previous domain.
        new_domain: New domain.
        current_path: Current path.
        suggested_path: Suggested new path.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        f"Domain changed: {old_domain} → {new_domain}",
        "",
        "Current path:",
        f"{current_path}",
        "",
        "Suggested new path:",
        f"{suggested_path}",
        "",
        "Update path too?",
        "",
        "[enter] Yes, use suggested path",
        "[k] Keep current path",
        "[e] Edit manually",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Domain Changed", lines)])

    for line in render_box(title="Domain Changed", lines=lines, width=width):
        print(line)


def render_no_connections_warning_modal(state: PlannerState) -> None:
    """Render warning when saving without connections.
    
    Args:
        state: Current planner state.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    blocks_count = len(state.boxes)

    lines = [
        "Warning",
        "",
        f"This plan has {blocks_count} blocks but no assembly connections.",
        "",
        "That is allowed, but AI will only know what exists,",
        "not how pieces work together.",
        "",
        "[c] Connect blocks",
        "[s] Save anyway",
        "[esc] Back",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Plan Review", lines)])

    for line in render_box(title="Plan Review", lines=lines, width=width):
        print(line)


def render_experimental_to_active_warning_modal(state: PlannerState, experimental_box: PlannerBox, active_box: PlannerBox) -> None:
    """Render warning when connecting experimental block to active.
    
    Args:
        state: Current planner state.
        experimental_box: The experimental block being connected.
        active_box: The active block being connected to.
    """
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        "You are connecting an experimental block to an",
        "active block.",
        "",
        "Experimental",
        f"- {experimental_box.name}",
        "",
        "Active",
        f"- {active_box.name}",
        "",
        "This is allowed, but verify may treat the",
        "implementation as part of the planned system.",
        "",
        "[enter] Continue",
        "[esc] Cancel",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Lifecycle Warning", lines)])

    for line in render_box(title="Lifecycle Warning", lines=lines, width=width):
        print(line)


def render_blueprint_locked_modal(state: PlannerState) -> None:
    """Render modal when blueprint is locked and cannot be saved."""
    clear_screen()
    terminal_width = get_terminal_width()

    lines = [
        "blueprint.yaml is locked.",
        "",
        "Planner can continue editing the draft,",
        "but it cannot write the file until you",
        "unlock authority.",
        "",
        "Run:",
        "  bpfw unlock",
        "",
        "[enter] Keep editing",
        "[q] Quit",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Blueprint Locked", lines)])

    for line in render_box(title="Blueprint Locked", lines=lines, width=width):
        print(line)


def render_invalid_blueprint_modal(state: PlannerState) -> None:
    """Render modal when blueprint.yaml cannot be parsed."""
    clear_screen()
    terminal_width = get_terminal_width()

    reason = str(state.modal_data.get("invalid_reason") or "invalid YAML")
    compact_reason = reason.splitlines()[0]

    lines = [
        "Planner could not load blueprint.yaml.",
        "",
        f"Reason: {compact_reason}",
        "",
        "Planner will not overwrite this file.",
        "Fix the YAML or restore a valid",
        "blueprint first.",
        "",
        "[enter] Exit",
    ]
    width = _resolve_uniform_width(terminal_width=terminal_width, panels=[("Invalid blueprint.yaml", lines)])

    for line in render_box(title="Invalid blueprint.yaml", lines=lines, width=width):
        print(line)
