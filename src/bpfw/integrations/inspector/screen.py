"""Screen rendering for the inspector integration."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List
import shutil
import textwrap

from bpfw.integrations.inspector.suggestions.purpose.models import PurposeSuggestion
from bpfw.integrations.inspector.base import (
    build_hierarchy_lines,
    build_nested_snippet_lines,
    build_code_lines,
    clean_string,
    display_value,
)
from bpfw.integrations.inspector.commands import CUSTOM_DOMAIN_KEY, DOMAIN_SUGGESTION_KEYS
from bpfw.integrations.inspector.view_modes import resolve_inspector_view_mode_from_flag
from bpfw.integrations.inspector.view_modes.base import InspectorViewMode
from bpfw.integrations.shared.visual_width import display_width, fit_text, measure_lines, pad_text
from bpfw.integrations.shared.visual_boxes import (
    render_box,
    render_two_column_box,
    render_split_box,
)
from bpfw.integrations.shared.visual_theme import (
    DEFAULT_THEME,
    compute_panel_width,
    render_commands_box,
    render_header,
)
from bpfw.integrations.shared.screen_control import refresh_screen

PrintFunc = Callable[[str], None]
MIN_TOTAL_WIDTH = 72
HORIZONTAL_PADDING = 1
DEFAULT_INSPECTOR_HEADER_TITLE = "Blueprint Framework Inspector"


def render_inspector_screen(
    project_root: Path,
    issue_type: str,
    block: Dict[str, Any],
    index: int,
    total: int,
    purpose_suggestions: List[PurposeSuggestion],
    domain_suggestions: List[str],
    header_title: str = DEFAULT_INSPECTOR_HEADER_TITLE,
    print_func: PrintFunc = print,
    show_all: bool = False,
    view_mode: InspectorViewMode | None = None,
) -> None:
    """Render the direct MVP inspector screen."""

    refresh_screen()
    print_func("")
    header_meta = f"{index + 1}/{total} {issue_type} "
    file_path = block.get("code", {}).get("path", "")
    snippet_lines = build_code_lines(project_root, block)[:26]
    nested_lines = build_nested_snippet_lines(block)
    hierarchy_lines = build_hierarchy_lines(block)
    code_lines: List[str] = []
    if file_path:
        code_lines.append(file_path)
    if nested_lines:
        code_lines.append("Children detected. Parent preview is collapsed.")
        code_lines.extend(hierarchy_lines)
    else:
        code_lines.extend(snippet_lines)

    authority_lines = [
        "",
        f"  PURPOSE    {display_value(block.get('purpose'))}",
        f"  DOMAIN     {display_value(block.get('domain'))}",
        f"  NAME       {display_value(block.get('name'))}",
        f"  STATUS     {display_value(block.get('status'))}",
        "",
    ]

    current_lifecycle = clean_string(block.get("status")) or ""
    lifecycle_lines = []
    for lifecycle_value, lifecycle_label in (
        ("active", " [z] active"),
        ("experimental", " [x] experimental"),
        ("legacy", " [c] legacy"),
        ("deprecated", " [v] deprecated"),
    ):
        marker = " *" if lifecycle_value == current_lifecycle else ""
        lifecycle_lines.append(f"{lifecycle_label}{marker}")

    purpose_lines: List[str] = []
    for suggestion_index in range(1, 6):
        suggestion_text = "-"
        if suggestion_index - 1 < len(purpose_suggestions):
            suggestion_text = purpose_suggestions[suggestion_index - 1].text
        purpose_lines.append(f" [{suggestion_index}] {suggestion_text}")
    purpose_lines.append(" [6] write custom purpose")

    domain_lines: List[str] = []
    for domain_index, domain_label in enumerate(DOMAIN_SUGGESTION_KEYS):
        domain_text = "-"
        if domain_index < len(domain_suggestions):
            domain_text = domain_suggestions[domain_index]
        domain_lines.append(f" [{domain_label}] {domain_text}")
    domain_lines.append(f" [{CUSTOM_DOMAIN_KEY}] write custom domain")
    resolved_view_mode = view_mode or resolve_inspector_view_mode_from_flag(show_all=show_all)
    show_extended_panels = resolved_view_mode.should_render_extended_panels()
    command_lines = resolved_view_mode.build_command_lines()
    observation_preview_lines = _build_observation_panel_lines(
        block=block,
        content_width=120,
        max_lines=3,
    )
    interface_preview_lines = _build_interface_panel_lines(
        block=block,
        content_width=120,
        max_lines=6,
    )
    global_inner_width = _compute_layout_width(
        header_meta=header_meta,
        code_lines=code_lines,
        hierarchy_lines=hierarchy_lines if show_extended_panels else [],
        authority_lines=authority_lines,
        lifecycle_lines=lifecycle_lines,
        observation_preview_lines=observation_preview_lines if show_extended_panels else [],
        interface_preview_lines=interface_preview_lines if show_extended_panels else [],
        domain_lines=domain_lines,
        purpose_lines=purpose_lines,
        command_lines=command_lines,
    )

    for header_line in _build_header(title=header_title, meta="", width=global_inner_width):
        print_func(header_line)

    code_panel_lines = list(code_lines)
    if file_path:
        code_panel_lines = [
            _compose_left_right_line(left=f" {file_path}", right=header_meta, width=global_inner_width),
            "─" * global_inner_width,
            *snippet_lines,
        ]
    for line in render_box(title="Code Block", lines=code_panel_lines, width=global_inner_width):
        print_func(line)

    if show_extended_panels:
        for line in render_box(
            title="Hierarchy",
            lines=hierarchy_lines,
            width=global_inner_width,
        ):
            print_func(line)

        interface_lines = _build_interface_panel_lines(
            block=block,
            content_width=global_inner_width,
            max_lines=6,
        )
        for line in render_box(
            title="Interface",
            lines=interface_lines,
            width=global_inner_width,
        ):
            print_func(line)

    for line in render_split_box(
        left_title="Block Status",
        left_lines=authority_lines,
        right_title="Lifecycle",
        right_lines=lifecycle_lines,
        total_width=global_inner_width,
        left_border_fill="═",
        right_border_fill="─",
        preferred_left_ratio=0.6,
    ):
        print_func(line)

    for line in render_two_column_box(
        left_title="Domain suggestions",
        left_lines=domain_lines,
        right_title="Purpose suggestions",
        right_lines=purpose_lines,
        total_width=global_inner_width,
        preferred_left_ratio=0.45,
    ):
        print_func(line)

    if show_extended_panels:
        observation_lines = _build_observation_panel_lines(
            block=block,
            content_width=global_inner_width,
            max_lines=3,
        )
        for line in render_box(
            title="Notes",
            lines=observation_lines,
            width=global_inner_width,
        ):
            print_func(line)

    for line in render_commands_box(
        lines=command_lines,
        width=global_inner_width,
        theme=DEFAULT_THEME,
        wrap_mode="safe_wrap",
    ):
        print_func(line)
    print_func("")


def _build_header(title: str, meta: str, width: int) -> List[str]:
    """Build the inspector title header."""

    if not meta.strip():
        return render_header(title=title, width=width, theme=DEFAULT_THEME, centered=True)
    if display_width(meta) >= width:
        header_line = fit_text(meta, width)
    else:
        left_width = width - display_width(meta) - 1
        header_line = pad_text(title, left_width) + " " + meta
    return render_header(title=header_line, width=width, theme=DEFAULT_THEME, centered=False)


def _build_observation_panel_lines(
    block: Dict[str, Any],
    content_width: int,
    max_lines: int = 3,
) -> list[str]:
    """Build compact observation lines with empty state and truncation."""

    observation_value = clean_string(block.get("notes"))
    if observation_value is None:
        return [" No observations registered · Press [o] to add an observation."]

    note_count_label = "1 note"
    prefix = f"{note_count_label} · "
    wrapped = textwrap.wrap(
        observation_value,
        width=max(8, content_width),
        break_long_words=True,
        break_on_hyphens=False,
    )
    if not wrapped:
        return [" No observations registered · Press [o] to add an observation."]

    lines: list[str] = [f"{prefix}{wrapped[0]}"]
    for extra_line in wrapped[1:max_lines]:
        lines.append(extra_line)
    if len(wrapped) > max_lines:
        lines[-1] = fit_text(lines[-1], max(1, content_width))
    return lines


def _build_interface_panel_lines(
    block: Dict[str, Any],
    content_width: int,
    max_lines: int = 6,
) -> list[str]:
    """Build compact interface lines with empty state."""

    interface = block.get("interface")
    if not isinstance(interface, dict):
        return [" No interface detected · Press [i] to add interface."]

    lines: list[str] = []

    # Build inputs section
    inputs = interface.get("inputs")
    if isinstance(inputs, list) and inputs:
        lines.append(" inputs:")
        for input_data in inputs:
            if not isinstance(input_data, dict):
                continue
            name = input_data.get("name", "?")
            param_type = input_data.get("type")
            default = input_data.get("default")
            required = input_data.get("required", True)

            # Format: name (type) required [default] or name (type) required
            if param_type:
                type_str = f"({param_type})"
            else:
                type_str = ""

            if default is not None:
                default_str = f" = {default}"
            else:
                default_str = ""

            required_str = "required" if required else "optional"

            line = f"   {name} {type_str} {required_str}{default_str}"
            if display_width(line) <= content_width - 2:
                lines.append(line)
            else:
                # Truncate if too long
                truncated = fit_text(line, max(1, content_width - 2))
                lines.append(f"   {truncated}")

            if len(lines) >= max_lines - 1:
                break
    else:
        lines.append(" No inputs defined")

    # Build output section
    output = interface.get("output")
    if isinstance(output, dict):
        output_type = output.get("type")
        if output_type:
            output_line = f" output: ({output_type})"
            lines.append(output_line)
        else:
            lines.append(" output: -")

    if len(lines) == 1 and "No interface detected" in lines[0]:
        return lines

    return lines


def _compose_left_right_line(left: str, right: str, width: int) -> str:
    """Compose one line with left and right text within fixed width."""

    if width <= 0:
        return ""
    if not right.strip():
        return fit_text(left, width)
    right_width = display_width(right)
    if right_width >= width:
        return fit_text(right, width)
    left_budget = max(0, width - right_width - 1)
    left_text = fit_text(left, left_budget)
    padding = " " * max(1, width - display_width(left_text) - right_width)
    return left_text + padding + right


def _compute_layout_width(
    header_meta: str,
    code_lines: list[str],
    hierarchy_lines: list[str],
    authority_lines: list[str],
    lifecycle_lines: list[str],
    observation_preview_lines: list[str],
    interface_preview_lines: list[str],
    domain_lines: list[str],
    purpose_lines: list[str],
    command_lines: list[str],
) -> int:
    """Compute one global inner width for all panels."""

    header_required = display_width("BPFW Inspector") + 1 + display_width(header_meta)
    code_required = measure_lines(code_lines)
    hierarchy_required = measure_lines(hierarchy_lines)
    observations_required = measure_lines(observation_preview_lines)
    interface_required = measure_lines(interface_preview_lines)
    commands_required = measure_lines(command_lines)
    authority_required = max(
        display_width("Block Status") + 3,
        measure_lines(authority_lines),
    )
    lifecycle_required = max(
        display_width("Lifecycle") + 3,
        measure_lines(lifecycle_lines),
    )
    domain_required = max(
        display_width("Domain suggestions") + 3,
        measure_lines(domain_lines),
    )
    purpose_required = max(
        display_width("Purpose suggestions") + 3,
        measure_lines(purpose_lines),
    )
    two_col_required_authority = authority_required + 1 + lifecycle_required
    two_col_required_suggestions = domain_required + 1 + purpose_required
    required_width = max(
        header_required,
        code_required,
        hierarchy_required,
        observations_required,
        interface_required,
        commands_required,
        two_col_required_authority,
        two_col_required_suggestions,
    ) + (HORIZONTAL_PADDING * 2)

    terminal_width = shutil.get_terminal_size(fallback=(100, 30)).columns
    computed = compute_panel_width(
        content_lines=[" " * max(0, required_width)],
        title=DEFAULT_INSPECTOR_HEADER_TITLE,
        terminal_width=terminal_width,
        theme=DEFAULT_THEME,
    )
    return max(20, max(MIN_TOTAL_WIDTH - 2, computed))
