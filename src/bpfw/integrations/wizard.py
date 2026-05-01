"""Interactive wizard integration for BPFW MVP catalog completion."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import yaml

from bpfw.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.catalog.loader import BlueprintLoader
from bpfw.catalog.models import (
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
)
from bpfw.catalog.writer import to_snake_case
from bpfw.core.errors import BlueprintLockedError
from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult

try:
    from InquirerPy import inquirer
except ImportError:
    inquirer = None


ALLOWED_LIFECYCLES = ("active", "experimental", "legacy", "deprecated")
CODE_VIEWPORT_HEIGHT = 10
DETAIL_VIEWPORT_HEIGHT = 6
MIN_VIEWPORT_WIDTH = 72
MAX_VIEWPORT_WIDTH = 110
NARROW_LAYOUT_WIDTH = 92
PANEL_INNER_MARGIN = 4

ViewportName = Literal["code", "authority", "detected"]

LIFECYCLE_MENU = {
    "1": "active",
    "2": "experimental",
    "3": "legacy",
    "4": "deprecated",
}

REQUIRED_HUMAN_FIELDS = ("intent", "canonical_name", "owner_layer", "lifecycle")
EDIT_ACTIONS = {
    "Edit intent": "intent",
    "Edit owner layer": "owner_layer",
    "Edit lifecycle": "lifecycle",
    "Edit notes": "notes",
}

VIEWPORT_ACTIONS = {
    "Focus code": "code",
    "Focus authority": "authority",
    "Focus detected": "detected",
}

MOVE_ACTIONS = {
    "Scroll down": "down",
    "Scroll up": "up",
    "Page down": "page_down",
    "Page up": "page_up",
    "Scroll right": "right",
    "Scroll left": "left",
    "Page right": "page_right",
    "Page left": "page_left",
    "Reset viewport": "reset",
}

@dataclass
class ViewportSpec:
    """Rendered dimensions for the wizard viewports."""

    width: int
    inner_width: int
    code_height: int
    authority_height: int
    detected_height: int
    use_columns: bool


@dataclass
class ViewportState:
    """Scroll state for one bounded viewport."""

    vertical_offset: int
    horizontal_offset: int
    height: int
    width: int
    fixed_prefix_width: int = 0


@dataclass
class WizardState:
    """Mutable state for one wizard responsibility screen."""

    responsibility_index: int
    active_viewport: ViewportName
    code: ViewportState
    authority: ViewportState
    detected: ViewportState


def get_incomplete_responsibilities(
    blueprint_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return responsibilities that have at least one missing required human field.

    Required human fields are: intent, canonical_name, owner_layer, lifecycle.

    Args:
        blueprint_data: Parsed blueprint dictionary.

    Returns:
        List of responsibility dicts with incomplete human fields.
    """
    responsibilities = blueprint_data.get("responsibilities", [])
    if not isinstance(responsibilities, list):
        return []

    incomplete: List[Dict[str, Any]] = []
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue
        for field_name in REQUIRED_HUMAN_FIELDS:
            value = responsibility.get(field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                incomplete.append(responsibility)
                break
    return incomplete


def prompt_for_lifecycle() -> str:
    """Display lifecycle menu and return the selected lifecycle string.

    Accepts either the numeric option (1-4) or the exact lifecycle name.

    Returns:
        One of: active, experimental, legacy, deprecated.
    """
    print("Lifecycle:")
    print("  1) active")
    print("  2) experimental")
    print("  3) legacy")
    print("  4) deprecated")

    while True:
        user_input = input("> ").strip()
        if user_input in LIFECYCLE_MENU:
            return LIFECYCLE_MENU[user_input]
        if user_input in ALLOWED_LIFECYCLES:
            return user_input
        print("Invalid lifecycle. Enter 1-4 or exact lifecycle name.")


def prompt_for_lifecycle_rich(console: Console, current_value: str | None = None) -> str:
    """Prompt for lifecycle using compact Rich-friendly output."""

    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    for option, lifecycle in LIFECYCLE_MENU.items():
        marker = "current" if lifecycle == current_value else ""
        table.add_row(option, f"{lifecycle} {marker}".strip())
    console.print(Panel(table, title="Lifecycle", border_style="cyan"))

    while True:
        user_input = console.input("[bold]> [/]").strip()
        if not user_input and current_value in ALLOWED_LIFECYCLES:
            return current_value
        if user_input in LIFECYCLE_MENU:
            return LIFECYCLE_MENU[user_input]
        if user_input in ALLOWED_LIFECYCLES:
            return user_input
        console.print("[red]Invalid lifecycle. Enter 1-4 or exact lifecycle name.[/]")


def _clean_string(value: Any) -> str | None:
    """Return a stripped string or None for blank values."""

    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _display_value(value: Any) -> str:
    """Render empty values consistently in wizard tables."""

    cleaned = _clean_string(value)
    return cleaned if cleaned is not None else "-"


def compute_viewport_spec(console_width: int) -> ViewportSpec:
    """Compute stable viewport dimensions from a terminal width."""

    if console_width <= 0:
        console_width = MIN_VIEWPORT_WIDTH
    available_width = max(console_width - 2, 40)
    if available_width < MIN_VIEWPORT_WIDTH:
        viewport_width = available_width
    else:
        viewport_width = min(max(available_width, MIN_VIEWPORT_WIDTH), MAX_VIEWPORT_WIDTH)

    return ViewportSpec(
        width=viewport_width,
        inner_width=max(viewport_width - PANEL_INNER_MARGIN, 20),
        code_height=CODE_VIEWPORT_HEIGHT,
        authority_height=DETAIL_VIEWPORT_HEIGHT,
        detected_height=DETAIL_VIEWPORT_HEIGHT,
        use_columns=viewport_width >= NARROW_LAYOUT_WIDTH,
    )


def _clamp_viewport_state(
    state: ViewportState,
    total_lines: int,
    max_line_width: int,
) -> ViewportState:
    """Clamp viewport offsets to valid bounds."""

    max_vertical = max(total_lines - state.height, 0)
    visible_scroll_width = max(state.width - state.fixed_prefix_width, 1)
    max_horizontal = max(max_line_width - state.fixed_prefix_width - visible_scroll_width, 0)
    return ViewportState(
        vertical_offset=min(max(state.vertical_offset, 0), max_vertical),
        horizontal_offset=min(max(state.horizontal_offset, 0), max_horizontal),
        height=state.height,
        width=state.width,
        fixed_prefix_width=state.fixed_prefix_width,
    )


def slice_viewport_lines(
    lines: list[str],
    state: ViewportState,
    inner_width: int,
) -> list[str]:
    """Slice lines through a bounded vertical and horizontal viewport."""

    clamped_state = _clamp_viewport_state(
        state=state,
        total_lines=len(lines),
        max_line_width=max((len(line) for line in lines), default=0),
    )
    visible_lines = lines[
        clamped_state.vertical_offset:clamped_state.vertical_offset + clamped_state.height
    ]
    visible_width = max(inner_width, 1)
    fixed_prefix_width = min(clamped_state.fixed_prefix_width, visible_width)
    scrollable_width = max(visible_width - fixed_prefix_width, 1)

    sliced_lines = []
    for line in visible_lines:
        prefix = line[:fixed_prefix_width]
        scrollable = line[fixed_prefix_width:]
        segment = scrollable[
            clamped_state.horizontal_offset:clamped_state.horizontal_offset + scrollable_width
        ]
        sliced_lines.append(f"{prefix}{segment}".ljust(visible_width))

    while len(sliced_lines) < clamped_state.height:
        sliced_lines.append("".ljust(visible_width))

    return sliced_lines


def move_viewport(
    state: ViewportState,
    command: str,
    total_lines: int,
    max_line_width: int,
) -> ViewportState:
    """Move a viewport in response to one navigation command."""

    vertical_offset = state.vertical_offset
    horizontal_offset = state.horizontal_offset
    horizontal_page = max(state.width // 2, 1)

    if command == "down":
        vertical_offset += 1
    elif command == "up":
        vertical_offset -= 1
    elif command == "page_down":
        vertical_offset += state.height
    elif command == "page_up":
        vertical_offset -= state.height
    elif command == "right":
        horizontal_offset += 4
    elif command == "left":
        horizontal_offset -= 4
    elif command == "page_right":
        horizontal_offset += horizontal_page
    elif command == "page_left":
        horizontal_offset -= horizontal_page
    elif command == "reset":
        vertical_offset = 0
        horizontal_offset = 0

    return _clamp_viewport_state(
        state=ViewportState(
            vertical_offset=vertical_offset,
            horizontal_offset=horizontal_offset,
            height=state.height,
            width=state.width,
            fixed_prefix_width=state.fixed_prefix_width,
        ),
        total_lines=total_lines,
        max_line_width=max_line_width,
    )


def _truncate_line(value: str, width: int) -> str:
    """Truncate a line to fit inside a fixed-width viewport."""

    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width == 1:
        return "…"
    return f"{value[:width - 1]}…"


def _viewport_title(
    name: str,
    lines: list[str],
    state: ViewportState,
) -> str:
    """Build a title with vertical and horizontal scroll indicators."""

    total_lines = len(lines)
    max_line_width = max((len(line) for line in lines), default=0)
    max_vertical = max(total_lines - state.height, 0)
    max_horizontal = max(max_line_width - state.width, 0)
    markers = []
    if state.vertical_offset > 0:
        markers.append("↑")
    if state.vertical_offset < max_vertical:
        markers.append("↓")
    if state.horizontal_offset > 0:
        markers.append("←")
    if state.horizontal_offset < max_horizontal:
        markers.append("→")
    marker_text = f" {' '.join(markers)}" if markers else ""
    return (
        f"{name} v {state.vertical_offset}/{total_lines} "
        f"h {state.horizontal_offset}{marker_text}"
    )


def suggest_owner_layer(responsibility: Dict[str, Any]) -> str | None:
    """Suggest owner_layer from the code path."""

    location = responsibility.get("location", {})
    if not isinstance(location, dict):
        return None

    path_value = _clean_string(location.get("path"))
    if path_value is None:
        return None

    path = Path(path_value)
    parts = path.parts
    if len(parts) >= 3 and parts[0] == "src" and parts[1] == "bpfw":
        return parts[2] if parts[2] != "__init__.py" else "package"
    if len(parts) >= 2 and parts[0] == "src":
        return parts[1]
    if parts:
        first_part = parts[0]
        if first_part.endswith(".py"):
            return Path(first_part).stem
        return first_part
    return None


def suggest_lifecycle(responsibility: Dict[str, Any]) -> str:
    """Suggest a lifecycle without silently committing semantic authority."""

    current_lifecycle = _clean_string(responsibility.get("lifecycle"))
    if current_lifecycle in ALLOWED_LIFECYCLES:
        return current_lifecycle
    return "active"


def ensure_generated_defaults(responsibility: Dict[str, Any]) -> None:
    """Fill required generated fields that do not need human semantics."""

    location = responsibility.get("location", {})
    if not isinstance(location, dict):
        return

    symbol = _clean_string(location.get("symbol"))
    if symbol is None:
        return

    if _clean_string(responsibility.get("canonical_name")) is None:
        responsibility["canonical_name"] = symbol
    if _clean_string(responsibility.get("id")) is None:
        responsibility["id"] = to_snake_case(symbol)


def build_code_lines(
    project_root: Path,
    responsibility: Dict[str, Any],
) -> list[str]:
    """Build numbered source lines for the responsibility location."""

    location = responsibility.get("location", {})
    if not isinstance(location, dict):
        return ["No location metadata available."]

    path_value = _clean_string(location.get("path"))
    if path_value is None:
        return ["No source path available."]

    source_path = project_root / path_value
    if not source_path.exists():
        return [f"Source file not found: {path_value}"]

    try:
        source_lines = source_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return [f"Source file is not UTF-8: {path_value}"]

    start_line = int(location.get("start_line") or 1)
    end_line = int(location.get("end_line") or start_line)
    start_index = max(start_line - 1, 0)
    end_index = min(end_line, len(source_lines))
    if end_index <= start_index:
        end_index = min(start_index + 1, len(source_lines))

    lines = []
    for offset, line in enumerate(source_lines[start_index:end_index]):
        line_number = start_line + offset
        lines.append(f"{line_number:>4}  {line.rstrip()}")
    return lines or ["No source lines available."]


def build_code_preview(
    project_root: Path,
    responsibility: Dict[str, Any],
    max_lines: int = CODE_VIEWPORT_HEIGHT,
) -> Text:
    """Build a compatibility code preview for tests and simple callers."""

    text = Text()
    for line in build_code_lines(project_root, responsibility)[:max_lines]:
        text.append(line)
        text.append("\n")
    return text


def build_authority_lines(responsibility: Dict[str, Any]) -> list[str]:
    """Build fixed text lines for authority fields."""

    suggested_owner = suggest_owner_layer(responsibility)
    suggested_lifecycle = suggest_lifecycle(responsibility)
    owner_status = "suggested" if suggested_owner == responsibility.get("owner_layer") else ""
    lifecycle_status = "suggested" if suggested_lifecycle == responsibility.get("lifecycle") else ""
    return [
        f"{'intent':<12} {_display_value(responsibility.get('intent')):<22} {'required'}",
        f"{'owner_layer':<12} {_display_value(responsibility.get('owner_layer')):<22} {owner_status}",
        f"{'lifecycle':<12} {_display_value(responsibility.get('lifecycle')):<22} {lifecycle_status}",
        f"{'notes':<12} {_display_value(responsibility.get('notes')):<22} {'optional'}",
    ]


def build_detected_lines(responsibility: Dict[str, Any]) -> list[str]:
    """Build fixed text lines for detected metadata."""

    location = responsibility.get("location", {})
    detected = responsibility.get("detected", {})
    if not isinstance(location, dict):
        location = {}
    if not isinstance(detected, dict):
        detected = {}

    methods = detected.get("methods", [])
    if isinstance(methods, list) and methods:
        methods_value = ", ".join(str(method) for method in methods)
    else:
        methods_value = "-"
    imports = detected.get("imports", [])
    if isinstance(imports, list) and imports:
        import_lines = [f"{'import':<12} {str(import_value)}" for import_value in imports]
    else:
        import_lines = [f"{'imports':<12} -"]

    return [
        f"{'type':<12} {_display_value(location.get('symbol_type'))}",
        f"{'signature':<12} {_display_value(detected.get('signature'))}",
        f"{'docstring':<12} {_display_value(detected.get('docstring'))}",
        f"{'methods':<12} {methods_value}",
        *import_lines,
    ]


def _text_from_lines(lines: list[str], style: str | None = None) -> Text:
    """Build Rich Text from viewport lines."""

    text = Text(no_wrap=True, overflow="crop")
    for line in lines:
        text.append(line, style=style)
        text.append("\n")
    return text


def _render_viewport_panel(
    title: str,
    lines: list[str],
    state: ViewportState,
    border_style: str,
) -> Panel:
    """Render a bounded viewport panel."""

    sliced_lines = slice_viewport_lines(
        lines=lines,
        state=state,
        inner_width=state.width,
    )
    return Panel(
        _text_from_lines(sliced_lines),
        title=_viewport_title(title, lines, state),
        border_style=border_style,
        width=state.width + PANEL_INNER_MARGIN,
    )


def _build_header_panel(
    responsibility: Dict[str, Any],
    state: WizardState,
    total: int,
    pending: int,
    width: int,
) -> Panel:
    """Build the fixed header viewport."""

    location = responsibility.get("location", {})
    if not isinstance(location, dict):
        location = {}

    path_value = _display_value(location.get("path"))
    symbol = _display_value(location.get("symbol"))
    symbol_type = _display_value(location.get("symbol_type"))
    start_line = _display_value(location.get("start_line"))
    end_line = _display_value(location.get("end_line"))
    inner_width = max(width - PANEL_INNER_MARGIN, 20)
    lines = [
        f"{state.responsibility_index + 1}/{total}  draft · {pending} pending · focus: {state.active_viewport}",
        f"{path_value} :: {symbol}",
        f"{symbol_type} · lines {start_line}-{end_line}",
    ]
    text = Text(no_wrap=True, overflow="crop")
    for line in lines:
        text.append(_truncate_line(line, inner_width))
        text.append("\n")
    return Panel(text, title=f"BPFW Wizard {state.responsibility_index + 1}/{total}", width=width)


def _initial_wizard_state(
    responsibility_index: int,
    spec: ViewportSpec,
) -> WizardState:
    """Build initial viewport state for one responsibility."""

    return WizardState(
        responsibility_index=responsibility_index,
        active_viewport="code",
        code=ViewportState(
            vertical_offset=0,
            horizontal_offset=0,
            height=spec.code_height,
            width=spec.inner_width,
            fixed_prefix_width=6,
        ),
        authority=ViewportState(
            vertical_offset=0,
            horizontal_offset=0,
            height=spec.authority_height,
            width=spec.inner_width if not spec.use_columns else max((spec.inner_width - 2) // 2, 20),
        ),
        detected=ViewportState(
            vertical_offset=0,
            horizontal_offset=0,
            height=spec.detected_height,
            width=spec.inner_width if not spec.use_columns else max((spec.inner_width - 2) // 2, 20),
        ),
    )


def _get_viewport_state(state: WizardState, viewport_name: ViewportName) -> ViewportState:
    """Read one viewport state from wizard state."""

    return getattr(state, viewport_name)


def _set_viewport_state(
    state: WizardState,
    viewport_name: ViewportName,
    viewport_state: ViewportState,
) -> None:
    """Update one viewport state in place."""

    setattr(state, viewport_name, viewport_state)


def render_responsibility_screen(
    console: Console,
    project_root: Path,
    responsibility: Dict[str, Any],
    state: WizardState,
    total: int,
    pending: int,
    spec: ViewportSpec,
) -> None:
    """Render one wizard responsibility screen with bounded viewports."""

    code_lines = build_code_lines(project_root=project_root, responsibility=responsibility)
    authority_lines = build_authority_lines(responsibility=responsibility)
    detected_lines = build_detected_lines(responsibility=responsibility)

    header_panel = _build_header_panel(
        responsibility=responsibility,
        state=state,
        total=total,
        pending=pending,
        width=spec.width,
    )
    code_panel = _render_viewport_panel(
        title="Code",
        lines=code_lines,
        state=state.code,
        border_style="blue",
    )
    authority_panel = _render_viewport_panel(
        title="Authority",
        lines=authority_lines,
        state=state.authority,
        border_style="green",
    )
    detected_panel = _render_viewport_panel(
        title="Detected",
        lines=detected_lines,
        state=state.detected,
        border_style="cyan",
    )

    console.print(header_panel, width=spec.width, no_wrap=True, overflow="crop")
    console.print(code_panel, width=spec.width, no_wrap=True, overflow="crop")
    if spec.use_columns:
        details = Table.grid(expand=False)
        details.add_column(width=state.authority.width + PANEL_INNER_MARGIN)
        details.add_column(width=state.detected.width + PANEL_INNER_MARGIN)
        details.add_row(authority_panel, detected_panel)
        console.print(details, width=spec.width, no_wrap=True, overflow="crop")
    else:
        console.print(authority_panel, width=spec.width, no_wrap=True, overflow="crop")
        console.print(detected_panel, width=spec.width, no_wrap=True, overflow="crop")


def validate_ready_to_accept(responsibility: Dict[str, Any]) -> list[str]:
    """Return missing required fields before accepting a responsibility."""

    ensure_generated_defaults(responsibility)
    missing_fields = []
    for field_name in REQUIRED_HUMAN_FIELDS:
        if _clean_string(responsibility.get(field_name)) is None:
            missing_fields.append(field_name)
    return missing_fields


def _select_action(console: Console) -> str:
    """Select the next wizard action."""

    choices = [
        "Focus code",
        "Focus authority",
        "Focus detected",
        "Scroll down",
        "Scroll up",
        "Page down",
        "Page up",
        "Scroll right",
        "Scroll left",
        "Page right",
        "Page left",
        "Reset viewport",
        "Full code temporarily",
        "Edit intent",
        "Edit owner layer",
        "Edit lifecycle",
        "Edit notes",
        "Accept and next",
        "Skip",
        "Back",
        "Save and quit",
    ]
    if inquirer is not None and console.is_terminal:
        return inquirer.select(message="Action", choices=choices).execute()

    console.print("Actions:")
    for index, choice in enumerate(choices, start=1):
        console.print(f"  {index}) {choice}")
    while True:
        user_input = console.input("[bold]> [/]").strip()
        if user_input.isdigit():
            selected_index = int(user_input)
            if 1 <= selected_index <= len(choices):
                return choices[selected_index - 1]
        console.print("[red]Choose a valid action number.[/]")


def _select_lifecycle(console: Console, current_value: str | None) -> str:
    """Select lifecycle with InquirerPy when available."""

    choices = list(ALLOWED_LIFECYCLES)
    if inquirer is not None and console.is_terminal:
        default = current_value if current_value in ALLOWED_LIFECYCLES else "active"
        return inquirer.select(
            message="Lifecycle",
            choices=choices,
            default=default,
        ).execute()

    return prompt_for_lifecycle_rich(console=console, current_value=current_value)


def _select_owner_layer(
    console: Console,
    responsibility: Dict[str, Any],
) -> str:
    """Select owner layer from suggestions or custom input."""

    suggested_owner = suggest_owner_layer(responsibility)
    owner_choices = [
        choice
        for choice in (
            suggested_owner,
            "cli",
            "catalog",
            "core",
            "protection",
            "reports",
            "integrations",
            "package",
            "Custom",
        )
        if choice is not None
    ]
    deduped_choices = list(dict.fromkeys(owner_choices))
    current_owner = _clean_string(responsibility.get("owner_layer"))
    default = current_owner if current_owner in deduped_choices else deduped_choices[0]

    if inquirer is not None and console.is_terminal:
        selected = inquirer.select(
            message="Owner layer",
            choices=deduped_choices,
            default=default,
        ).execute()
    else:
        console.print("Owner layer:")
        for index, choice in enumerate(deduped_choices, start=1):
            console.print(f"  {index}) {choice}")
        selected = ""
        while not selected:
            user_input = console.input("[bold]> [/]").strip()
            if user_input.isdigit():
                selected_index = int(user_input)
                if 1 <= selected_index <= len(deduped_choices):
                    selected = deduped_choices[selected_index - 1]
            if not selected:
                console.print("[red]Choose a valid owner layer number.[/]")

    if selected == "Custom":
        while True:
            custom_owner = console.input("owner layer: ").strip()
            if custom_owner:
                return custom_owner
            console.print("[red]owner layer cannot be empty.[/]")
    return selected


def _edit_text_field(
    console: Console,
    responsibility: Dict[str, Any],
    field_name: str,
) -> None:
    """Edit one text field."""

    current_value = _clean_string(responsibility.get(field_name))
    prompt_label = field_name.replace("_", " ")
    if current_value:
        console.print(f"[dim]Current {prompt_label}: {current_value}[/]")
    if inquirer is not None and console.is_terminal:
        user_input = inquirer.text(message=prompt_label, default=current_value or "").execute().strip()
    else:
        user_input = console.input(f"{prompt_label}: ").strip()
    if field_name != "notes" and not user_input:
        console.print(f"[red]{prompt_label} cannot be empty.[/]")
        return
    responsibility[field_name] = user_input or None


def _active_viewport_lines(
    project_root: Path,
    responsibility: Dict[str, Any],
    active_viewport: ViewportName,
) -> list[str]:
    """Build lines for the active viewport."""

    if active_viewport == "code":
        return build_code_lines(project_root=project_root, responsibility=responsibility)
    if active_viewport == "authority":
        return build_authority_lines(responsibility=responsibility)
    return build_detected_lines(responsibility=responsibility)


def _show_full_code_temporarily(
    console: Console,
    project_root: Path,
    responsibility: Dict[str, Any],
    spec: ViewportSpec,
) -> None:
    """Show code in temporary fixed-size pages."""

    code_lines = build_code_lines(project_root=project_root, responsibility=responsibility)
    page_start = 0
    page_size = spec.code_height
    while page_start < len(code_lines):
        temporary_state = ViewportState(
            vertical_offset=page_start,
            horizontal_offset=0,
            height=page_size,
            width=spec.inner_width,
            fixed_prefix_width=6,
        )
        console.print(
            _render_viewport_panel(
                title="Full code",
                lines=code_lines,
                state=temporary_state,
                border_style="blue",
            )
        )
        page_start += page_size
        if page_start >= len(code_lines):
            return
        if inquirer is not None and console.is_terminal:
            action = inquirer.select(
                message="Full code",
                choices=["Next page", "Close"],
            ).execute()
            if action == "Close":
                return
        else:
            user_input = console.input("Press Enter for next page or q to close: ").strip().lower()
            if user_input == "q":
                return


def _same_intent_groups(responsibilities: list[Dict[str, Any]]) -> dict[str, list[Dict[str, Any]]]:
    groups: dict[str, list[Dict[str, Any]]] = defaultdict(list)
    for responsibility in responsibilities:
        intent = _clean_string(responsibility.get("intent"))
        if intent is None:
            continue
        groups[to_snake_case(intent)].append(responsibility)
    return groups


def _related_entry(responsibility: Dict[str, Any], relation: str) -> dict[str, str | None]:
    location = responsibility.get("location", {})
    if not isinstance(location, dict):
        location = {}
    return {
        "path": _clean_string(location.get("path")),
        "symbol": _clean_string(location.get("symbol")),
        "kind": _clean_string(location.get("symbol_type")),
        "relation": relation,
    }


def apply_automatic_authority_fields(blueprint_data: Dict[str, Any]) -> None:
    """Recalculate authority fields derived from declared intent/lifecycle."""

    raw_responsibilities = blueprint_data.get("responsibilities", [])
    if not isinstance(raw_responsibilities, list):
        return

    responsibilities = [
        responsibility
        for responsibility in raw_responsibilities
        if isinstance(responsibility, dict)
    ]

    for responsibility in responsibilities:
        ensure_generated_defaults(responsibility)
        intent = _clean_string(responsibility.get("intent"))
        duplicate_policy = responsibility.setdefault("duplicate_policy", {})
        if not isinstance(duplicate_policy, dict):
            duplicate_policy = {}
            responsibility["duplicate_policy"] = duplicate_policy
        duplicate_policy.setdefault("allow_multiple_non_active", True)
        duplicate_policy.setdefault("forbidden_active_duplicates", True)
        duplicate_policy["group"] = to_snake_case(intent) if intent else None
        duplicate_policy["suspected_duplicates"] = []
        responsibility["related_code"] = []

        replacement = responsibility.setdefault("replacement", {})
        if not isinstance(replacement, dict):
            replacement = {}
            responsibility["replacement"] = replacement
        replacement.setdefault("replaces", None)
        replacement.setdefault("replaced_by", None)
        replacement.setdefault("reason", None)

    for _intent_group, grouped_responsibilities in _same_intent_groups(responsibilities).items():
        active_responsibilities = [
            responsibility
            for responsibility in grouped_responsibilities
            if responsibility.get("lifecycle") == "active"
        ]
        if len(active_responsibilities) > 1:
            active_ids = [
                str(responsibility.get("id"))
                for responsibility in active_responsibilities
                if _clean_string(responsibility.get("id")) is not None
            ]
            for responsibility in active_responsibilities:
                duplicate_policy = responsibility["duplicate_policy"]
                responsibility_id = str(responsibility.get("id"))
                duplicate_policy["suspected_duplicates"] = [
                    active_id for active_id in active_ids if active_id != responsibility_id
                ]

        for responsibility in grouped_responsibilities:
            lifecycle = responsibility.get("lifecycle")
            related_entries = []
            for related in grouped_responsibilities:
                if related is responsibility:
                    continue
                related_lifecycle = related.get("lifecycle")
                if lifecycle != related_lifecycle:
                    related_entries.append(
                        _related_entry(
                            related,
                            relation=f"same_intent_{related_lifecycle or 'unknown'}",
                        )
                    )
            responsibility["related_code"] = related_entries

        deprecated_or_legacy = [
            responsibility
            for responsibility in grouped_responsibilities
            if responsibility.get("lifecycle") in {"deprecated", "legacy"}
        ]
        experimental = [
            responsibility
            for responsibility in grouped_responsibilities
            if responsibility.get("lifecycle") == "experimental"
        ]
        if deprecated_or_legacy and experimental:
            replacement_target = deprecated_or_legacy[0]
            replacement_target_id = _clean_string(replacement_target.get("id"))
            for responsibility in experimental:
                replacement = responsibility["replacement"]
                if replacement.get("replaces") is None:
                    replacement["replaces"] = replacement_target_id
                if replacement.get("reason") is None:
                    replacement["reason"] = "same intent experimental replacement candidate"


def save_blueprint(
    blueprint_path: Path,
    blueprint_data: Dict[str, Any],
) -> None:
    """Save blueprint data to the YAML file.

    Args:
        blueprint_path: Path to bpfw/blueprint.yaml.
        blueprint_data: Blueprint data dictionary to serialize.
    """
    apply_automatic_authority_fields(blueprint_data)
    rendered = yaml.dump(blueprint_data, sort_keys=False, allow_unicode=True)
    blueprint_path.write_text(rendered, encoding="utf-8")


def run_wizard(project_root: Path) -> int:
    """Run the interactive wizard to complete required human fields.

    Steps:
        1. Resolve project root.
        2. Load blueprint.
        3. Exit 1 if blueprint is missing.
        4. Exit 1 if blueprint is invalid.
        5. Exit 1 if blueprint is locked.
        6. Find responsibilities with missing human fields.
        7. Prompt for each incomplete responsibility.
        8. Save after each responsibility.
        9. Print completion message.

    Args:
        project_root: Root directory of the project.

    Returns:
        Exit code: 0 on success, 1 on error or refusal.
    """
    project_root = project_root.resolve()

    # Step 2: Load blueprint
    loader = BlueprintLoader(project_root=project_root)
    load_result = loader.load()

    # Step 3: If blueprint missing
    if load_result.state == AUTHORITY_STATE_MISSING:
        print("No blueprint found. Run bpfw init first.")
        return 1

    # Step 4: If blueprint invalid
    if load_result.state == AUTHORITY_STATE_INVALID:
        print("Blueprint is invalid. Fix bpfw/blueprint.yaml before running wizard.")
        return 1

    # Step 5: If blueprint is locked
    try:
        ensure_blueprint_can_be_written(project_root=project_root)
    except BlueprintLockedError:
        print("Blueprint is locked. Run bpfw unlock before editing.")
        return 1

    blueprint_data = load_result.data
    blueprint_path = Path(load_result.path)

    # Step 6: Find incomplete responsibilities
    incomplete = get_incomplete_responsibilities(blueprint_data)

    if not incomplete:
        if load_result.state == AUTHORITY_STATE_EMPTY:
            print("No responsibilities to complete.")
        else:
            print("All responsibilities are already complete.")
        return 0

    total = len(incomplete)
    console = Console()
    console.print("[green]Blueprint is unlocked.[/]")

    current_index = 0
    while current_index < total:
        spec = compute_viewport_spec(console.width)
        wizard_state = _initial_wizard_state(
            responsibility_index=current_index,
            spec=spec,
        )
        responsibility = incomplete[current_index]
        while True:
            ensure_generated_defaults(responsibility)
            if _clean_string(responsibility.get("owner_layer")) is None:
                suggested_owner = suggest_owner_layer(responsibility)
                if suggested_owner is not None:
                    responsibility["owner_layer"] = suggested_owner
            if _clean_string(responsibility.get("lifecycle")) is None:
                responsibility["lifecycle"] = suggest_lifecycle(responsibility)

            render_responsibility_screen(
                console=console,
                project_root=project_root,
                responsibility=responsibility,
                state=wizard_state,
                total=total,
                pending=total - current_index,
                spec=spec,
            )

            action = _select_action(console=console)

            if action in VIEWPORT_ACTIONS:
                wizard_state.active_viewport = VIEWPORT_ACTIONS[action]
                continue

            if action in MOVE_ACTIONS:
                active_state = _get_viewport_state(
                    state=wizard_state,
                    viewport_name=wizard_state.active_viewport,
                )
                active_lines = _active_viewport_lines(
                    project_root=project_root,
                    responsibility=responsibility,
                    active_viewport=wizard_state.active_viewport,
                )
                moved_state = move_viewport(
                    state=active_state,
                    command=MOVE_ACTIONS[action],
                    total_lines=len(active_lines),
                    max_line_width=max((len(line) for line in active_lines), default=0),
                )
                _set_viewport_state(
                    state=wizard_state,
                    viewport_name=wizard_state.active_viewport,
                    viewport_state=moved_state,
                )
                continue

            if action in EDIT_ACTIONS:
                field_name = EDIT_ACTIONS[action]
                if field_name == "lifecycle":
                    responsibility["lifecycle"] = _select_lifecycle(
                        console=console,
                        current_value=_clean_string(responsibility.get("lifecycle")),
                    )
                    continue
                if field_name == "owner_layer":
                    responsibility["owner_layer"] = _select_owner_layer(
                        console=console,
                        responsibility=responsibility,
                    )
                    continue
                _edit_text_field(
                    console=console,
                    responsibility=responsibility,
                    field_name=field_name,
                )
                continue

            if action == "Full code temporarily":
                _show_full_code_temporarily(
                    console=console,
                    project_root=project_root,
                    responsibility=responsibility,
                    spec=spec,
                )
                continue

            if action == "Accept and next":
                missing_fields = validate_ready_to_accept(responsibility)
                if missing_fields:
                    console.print(
                        f"[red]Missing required fields: {', '.join(missing_fields)}[/]"
                    )
                    continue
                save_blueprint(blueprint_path, blueprint_data)
                console.print("[green]Saved.[/]")
                current_index += 1
                break

            if action == "Skip":
                current_index += 1
                break

            if action == "Back":
                current_index = max(0, current_index - 1)
                break

            if action == "Save and quit":
                save_blueprint(blueprint_path, blueprint_data)
                console.print("[green]Saved. Wizard stopped.[/]")
                return 0

    # Step 9: Completion message
    console.print()
    console.print("[green]Wizard completed.[/]")
    console.print()
    console.print("Next:")
    console.print("  bpfw verify")
    console.print("  bpfw lock")

    return 0


class RichWizardIntegration(OptionalIntegration):
    """Optional terminal wizard integration."""

    name = "wizard"

    def is_available(self) -> bool:
        """Return True when the built-in terminal wizard can run."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Run the interactive terminal wizard."""

        exit_code = run_wizard(project_root=project_root)
        return OptionalIntegrationResult(message="", exit_code=exit_code)


def complete_human_fields(project_root: Path) -> tuple[Path, int]:
    """Fill missing intent and lifecycle fields deterministically.

    This is the non-interactive fallback used by the engine pipeline.
    It assigns default values without prompting the user.

    Args:
        project_root: Root directory of the project.

    Returns:
        Tuple of (blueprint_path, updated_entry_count).
    """
    ensure_blueprint_can_be_written(project_root=project_root)
    loader = BlueprintLoader(project_root=project_root)
    load_result = loader.load()
    blueprint_path = Path(load_result.path)
    payload = load_result.data
    responsibilities = payload.get("responsibilities", [])
    if not isinstance(responsibilities, list):
        return blueprint_path, 0

    updated_entries = 0
    for responsibility in responsibilities:
        if not isinstance(responsibility, dict):
            continue

        lifecycle_value = responsibility.get("lifecycle")
        if lifecycle_value is None or (isinstance(lifecycle_value, str) and not lifecycle_value.strip()):
            responsibility["lifecycle"] = "active"
            updated_entries += 1

        intent_value = responsibility.get("intent")
        if intent_value is None or (isinstance(intent_value, str) and not intent_value.strip()):
            responsibility_identifier = str(responsibility.get("id", "")).strip()
            canonical_name = (
                str(responsibility.get("canonical_name", "")).strip().lower()
            )
            generated_intent = (
                f"{canonical_name}:{responsibility_identifier}"
                if canonical_name
                else responsibility_identifier.replace("_", " ")
            )
            responsibility["intent"] = generated_intent.strip() or "define intent"
            updated_entries += 1

    rendered = yaml.dump(payload, sort_keys=False, allow_unicode=True)
    blueprint_path.write_text(rendered, encoding="utf-8")
    return blueprint_path, updated_entries
