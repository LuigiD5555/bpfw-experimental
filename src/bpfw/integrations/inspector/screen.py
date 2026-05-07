"""Screen rendering for the inspector integration."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List
import shutil
import textwrap

from bpfw.catalog.intent_suggestions import IntentSuggestion
from bpfw.integrations.inspector_base import (
    build_code_lines,
    clean_string,
    display_value,
)
from bpfw.integrations.shared.visual_width import display_width, fit_text, measure_lines, pad_text
from bpfw.integrations.shared.visual_boxes import (
    _center_text,
    render_box,
    render_two_column_box,
    render_split_box,
)

PrintFunc = Callable[[str], None]
MIN_TOTAL_WIDTH = 72
HORIZONTAL_PADDING = 1


def render_inspector_screen(
    project_root: Path,
    issue_type: str,
    responsibility: Dict[str, Any],
    index: int,
    total: int,
    intent_suggestions: List[IntentSuggestion],
    domain_suggestions: List[str],
    print_func: PrintFunc = print,
) -> None:
    """Render the direct MVP inspector screen."""

    print_func("")
    header_meta = f"{index + 1}/{total} {issue_type} "
    file_path = (responsibility.get("location") or {}).get("path", "")
    snippet_lines = build_code_lines(project_root, responsibility)[:26]
    code_lines: List[str] = []
    if file_path:
        code_lines.append(file_path)
    code_lines.extend(snippet_lines)

    authority_lines = [
        "",
        f"  INTENT     {display_value(responsibility.get('intent'))}",
        f"  DOMAIN     {display_value(responsibility.get('domain'))}",
        f"  NAME       {display_value(responsibility.get('name'))}",
        f"  LIFECYCLE  {display_value(responsibility.get('lifecycle'))}",
        "",
    ]

    current_lifecycle = clean_string(responsibility.get("lifecycle")) or ""
    lifecycle_lines = []
    for lifecycle_value, lifecycle_label in (
        ("active", " [z] active"),
        ("experimental", " [x] experimental"),
        ("legacy", " [c] legacy"),
        ("deprecated", " [v] deprecated"),
    ):
        marker = " *" if lifecycle_value == current_lifecycle else ""
        lifecycle_lines.append(f"{lifecycle_label}{marker}")

    intent_lines: List[str] = []
    for suggestion_index in range(1, 6):
        suggestion_text = "-"
        if suggestion_index - 1 < len(intent_suggestions):
            suggestion_text = intent_suggestions[suggestion_index - 1].text
        intent_lines.append(f" [{suggestion_index}] {suggestion_text}")
    intent_lines.append(" [6] write custom intent")

    domain_lines: List[str] = []
    domain_labels = ("a", "s", "d", "f")
    for domain_index, domain_label in enumerate(domain_labels):
        domain_text = "-"
        if domain_index < len(domain_suggestions):
            domain_text = domain_suggestions[domain_index]
        domain_lines.append(f" [{domain_label}] {domain_text}")
    domain_lines.append(" [g] write custom domain")
    command_lines = [
        "[1-5] intent suggestion   [6] custom intent",
        "[a|s|d|f] domain          [g] custom domain",
        "[z|x|c|v] lifecycle       [n] name        [h] help",
        "[Enter] save + next       [b] back        [q] quit",
    ]
    observation_preview_lines = _build_observation_panel_lines(
        responsibility=responsibility,
        content_width=120,
        max_lines=3,
    )
    global_inner_width = _compute_layout_width(
        header_meta=header_meta,
        code_lines=code_lines,
        authority_lines=authority_lines,
        lifecycle_lines=lifecycle_lines,
        observation_preview_lines=observation_preview_lines,
        domain_lines=domain_lines,
        intent_lines=intent_lines,
        command_lines=command_lines,
    )

    for header_line in _build_header(
        title="Blueprint Framework Inspector",
        meta="",
        width=global_inner_width,
    ):
        print_func(header_line)

    code_panel_lines = list(code_lines)
    if file_path:
        code_panel_lines = [
            _compose_left_right_line(left=f" {file_path}", right=header_meta, width=global_inner_width),
            "─" * global_inner_width,
            *snippet_lines,
        ]
    for line in render_box(title="Code evidence", lines=code_panel_lines, width=global_inner_width):
        print_func(line)

    for line in render_split_box(
        left_title="Authority",
        left_lines=authority_lines,
        right_title="Lifecycle",
        right_lines=lifecycle_lines,
        total_width=global_inner_width,
        left_border_fill="═",
        right_border_fill="─",
        preferred_left_ratio=0.6,
    ):
        print_func(line)

    observation_lines = _build_observation_panel_lines(
        responsibility=responsibility,
        content_width=global_inner_width,
        max_lines=3,
    )
    for line in render_box(
        title="Observations",
        lines=observation_lines,
        width=global_inner_width,
    ):
        print_func(line)

    for line in render_two_column_box(
        left_title="Domain suggestions",
        left_lines=domain_lines,
        right_title="Intent suggestions",
        right_lines=intent_lines,
        total_width=global_inner_width,
        preferred_left_ratio=0.45,
    ):
        print_func(line)

    for line in render_box(
        title="Commands",
        lines=command_lines,
        width=global_inner_width,
    ):
        print_func(line)
    print_func("")


def _build_header(title: str, meta: str, width: int) -> List[str]:
    """Build the inspector title header."""

    if not meta.strip():
        header_line = _center_text(title, width)
    elif display_width(meta) >= width:
        header_line = fit_text(meta, width)
    else:
        left_width = width - display_width(meta) - 1
        header_line = pad_text(title, left_width) + " " + meta
    return [
        "╔" + "═" * width + "╗",
        f"║{pad_text(header_line, width)}║",
        "╚" + "═" * width + "╝",
    ]


def _build_observation_panel_lines(
    responsibility: Dict[str, Any],
    content_width: int,
    max_lines: int = 3,
) -> list[str]:
    """Build compact observation lines with empty state and truncation."""

    observation_value = clean_string(responsibility.get("notes"))
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
    authority_lines: list[str],
    lifecycle_lines: list[str],
    observation_preview_lines: list[str],
    domain_lines: list[str],
    intent_lines: list[str],
    command_lines: list[str],
) -> int:
    """Compute one global inner width for all panels."""

    header_required = display_width("BPFW Inspector") + 1 + display_width(header_meta)
    code_required = measure_lines(code_lines)
    observations_required = measure_lines(observation_preview_lines)
    commands_required = measure_lines(command_lines)
    authority_required = max(
        display_width("Authority") + 3,
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
    intent_required = max(
        display_width("Intent suggestions") + 3,
        measure_lines(intent_lines),
    )
    two_col_required_authority = authority_required + 1 + lifecycle_required
    two_col_required_suggestions = domain_required + 1 + intent_required
    required_width = max(
        header_required,
        code_required,
        observations_required,
        commands_required,
        two_col_required_authority,
        two_col_required_suggestions,
    ) + (HORIZONTAL_PADDING * 2)

    terminal_width = shutil.get_terminal_size(fallback=(100, 30)).columns
    total_width = min(max(required_width + 2, MIN_TOTAL_WIDTH), terminal_width)
    return max(20, total_width - 2)