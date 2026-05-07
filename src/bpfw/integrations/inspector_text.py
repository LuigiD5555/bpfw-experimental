"""Text inspector UI for BPFW catalog completion."""

from collections.abc import Callable
from pathlib import Path
import shutil
import textwrap
from typing import Any, Dict, List
import unicodedata

from bpfw.catalog.intent_suggestions import IntentSuggestion, suggest_intents
from bpfw.catalog.learning import record_domain_value, record_intent_phrase
from bpfw.catalog.models import AUTHORITY_STATE_EMPTY
from bpfw.integrations.inspector_base import (
    ISSUE_NEW_DETECTED,
    InspectIssue,
    InspectLoadResult,
    apply_suggestions,
    build_code_lines,
    clean_string,
    collect_existing_intents,
    display_value,
    load_inspect_session,
    save_blueprint,
    suggest_domains,
)

InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]

REQUIRED_SAVE_FIELDS = ("intent", "name", "domain", "lifecycle")
MIN_TOTAL_WIDTH = 72
HORIZONTAL_PADDING = 1
COLUMN_GAP_WIDTH = 1
ELLIPSIS = "…"


def display_width(text: str) -> int:
    """Return the visible terminal column width for text."""

    width = 0
    for character in text:
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
    return width


def fit_text(text: str, width: int) -> str:
    """Fit text into fixed terminal width, truncating with ellipsis when needed."""

    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    if width == 1:
        return ELLIPSIS

    result = ""
    consumed = 0
    budget = width - display_width(ELLIPSIS)
    for character in text:
        char_width = 0 if unicodedata.combining(character) else (
            2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
        )
        if consumed + char_width > budget:
            break
        result += character
        consumed += char_width
    return result + ELLIPSIS


def pad_text(text: str, width: int) -> str:
    """Pad text to a fixed terminal display width."""

    fitted = fit_text(text, width)
    return fitted + (" " * max(0, width - display_width(fitted)))


def measure_lines(lines: list[str]) -> int:
    """Return the maximum display width required by the given lines."""

    if not lines:
        return 0
    return max(display_width(line) for line in lines)


def _centered_title_bar(title: str, width: int, fill: str = "─") -> str:
    """Build a centered title bar segment with symmetric fill."""

    label = f" {title} "
    label_width = display_width(label)
    if label_width >= width:
        return fit_text(label, width)
    remaining = width - label_width
    left_fill = remaining // 2
    right_fill = remaining - left_fill
    return (fill * left_fill) + label + (fill * right_fill)


def _center_text(text: str, width: int) -> str:
    """Center plain text inside fixed width."""

    text_width = display_width(text)
    if text_width >= width:
        return fit_text(text, width)
    remaining = width - text_width
    left_padding = remaining // 2
    right_padding = remaining - left_padding
    return (" " * left_padding) + text + (" " * right_padding)


def render_box(title: str, lines: list[str], width: int) -> list[str]:
    """Build a bordered section with a title and text lines."""

    top = f"╭{_centered_title_bar(title=title, width=width, fill='─')}╮"
    body = [f"│{pad_text(line, width)}│" for line in lines]
    bottom = "╰" + "─" * width + "╯"
    return [top, *body, bottom]


def render_two_column_box(
    left_title: str,
    left_lines: List[str],
    right_title: str,
    right_lines: List[str],
    total_width: int,
    preferred_left_ratio: float = 0.5,
) -> List[str]:
    """Render a two-column box using dynamically calculated widths."""

    available_width = max(2, total_width - COLUMN_GAP_WIDTH)
    left_required = max(display_width(left_title) + 3, measure_lines(left_lines))
    right_required = max(display_width(right_title) + 3, measure_lines(right_lines))
    left_width = int(available_width * preferred_left_ratio)
    left_width = max(left_width, left_required)
    right_width = available_width - left_width
    min_column_width = 8
    if right_width < min_column_width:
        left_width = available_width // 2
        right_width = available_width - left_width
    if left_width < min_column_width:
        left_width = min_column_width
        right_width = max(min_column_width, available_width - left_width)

    left_top = _centered_title_bar(title=left_title, width=left_width, fill="─")
    right_top = _centered_title_bar(title=right_title, width=right_width, fill="─")
    lines = [f"╭{left_top}┬{right_top}╮"]
    row_count = max(len(left_lines), len(right_lines))
    for row_index in range(row_count):
        left_text = left_lines[row_index] if row_index < len(left_lines) else ""
        right_text = right_lines[row_index] if row_index < len(right_lines) else ""
        lines.append(f"│{pad_text(left_text, left_width)}│{pad_text(right_text, right_width)}│")
    lines.append(f"╰{'─' * left_width}┴{'─' * right_width}╯")
    return lines


def render_authority_lifecycle_box(
    authority_lines: List[str],
    lifecycle_lines: List[str],
    total_width: int,
) -> List[str]:
    """Render mixed-emphasis Authority/Lifecycle box with dynamic widths."""

    available_width = max(2, total_width - COLUMN_GAP_WIDTH)
    left_required = max(display_width("Authority") + 3, measure_lines(authority_lines))
    right_required = max(display_width("Lifecycle") + 3, measure_lines(lifecycle_lines))
    left_width = max(int(available_width * 0.6), left_required)
    right_width = available_width - left_width
    min_column_width = 12
    if right_width < min_column_width:
        left_width = available_width - min_column_width
        right_width = min_column_width
    if left_width < min_column_width:
        left_width = min_column_width
        right_width = available_width - left_width

    left_top = _centered_title_bar(title="Authority", width=left_width, fill="═")
    right_top = _centered_title_bar(title="Lifecycle", width=right_width, fill="─")

    lines = [f"╔{left_top}╦{right_top}╮"]
    row_count = max(len(authority_lines), len(lifecycle_lines))
    for row_index in range(row_count):
        left_text = authority_lines[row_index] if row_index < len(authority_lines) else ""
        right_text = lifecycle_lines[row_index] if row_index < len(lifecycle_lines) else ""
        lines.append(f"║{pad_text(left_text, left_width)}║{pad_text(right_text, right_width)}│")
    lines.append(f"╚{'═' * left_width}╩{'─' * right_width}╯")
    return lines


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


def _render_notification_block(title: str, lines: List[str], print_func: PrintFunc, width: int) -> None:
    """Render one isolated warning or error block."""

    top = f"╭{_centered_title_bar(title=title, width=width, fill='─')}╮"
    print_func(top)
    for line in lines:
        print_func(f"│{pad_text(line, width)}│")
    print_func("╰" + "─" * width + "╯")


def _render_help_block(print_func: PrintFunc, width: int) -> None:
    """Render inspector help for field meaning and command options."""

    help_lines = [
        "",
        "  Authority fields",
        "  ────────────────",
        "  intent        What this snippet is supposed to do.",
        "  domain        The project area to which this code snippet is related.",
        "  name          Simple name for this snippet.",
        "  observations  Optional notes for this snippet.",
        "",
        "  lifecycle     Current status of this code snippet.",
        "                active        In use now.",
        "                experimental  Still being tested.",
        "                legacy        Old, but still kept.",
        "                deprecated    Should be replaced or removed later.",
        "",
        "  Selection",
        "  ─────────",
        "  [1-5]      Choose suggested intent",
        "  [6]        Write custom intent",
        "  [a|s|d|f]  Choose suggested domain",
        "  [g]        Write custom domain",
        "  [z|x|c|v]  Set lifecycle",
        "",
        "  Editing",
        "  ───────",
        "  [n]        Edit name",
        "  [o]        Edit observations",
        "",
        "  Flow",
        "  ────",
        "  [Enter]    Save and continue",
        "  [b]        Back",
        "  [h]        Toggle help",
        "  [q]        Quit",
        "",
    ]
    _render_notification_block(
        title="Inspector help",
        lines=help_lines,
        print_func=print_func,
        width=width,
    )


def _compute_help_width() -> int:
    """Compute compact dynamic width for the help panel."""

    sample_lines = [
        "  domain        The project area to which this code snippet is related.",
        "                deprecated    Should be replaced or removed later.",
        "  [a|s|d|f]  Choose suggested domain",
        "  [Enter]    Save and continue",
    ]
    required_width = max(measure_lines(sample_lines), display_width("Inspector help") + 2) + (HORIZONTAL_PADDING * 2)
    terminal_width = shutil.get_terminal_size(fallback=(100, 30)).columns
    total_width = min(max(required_width + 2, MIN_TOTAL_WIDTH), terminal_width)
    return max(20, total_width - 2)


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
    two_col_required_authority = authority_required + COLUMN_GAP_WIDTH + lifecycle_required
    two_col_required_suggestions = domain_required + COLUMN_GAP_WIDTH + intent_required
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


def _compute_notification_width() -> int:
    """Compute standard inner width for standalone notification panels."""

    terminal_width = shutil.get_terminal_size(fallback=(100, 30)).columns
    total_width = min(max(MIN_TOTAL_WIDTH, MIN_TOTAL_WIDTH), terminal_width)
    return max(20, total_width - 2)


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


def render_text_inspector_screen(
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

    for line in render_authority_lifecycle_box(
        authority_lines=authority_lines,
        lifecycle_lines=lifecycle_lines,
        total_width=global_inner_width,
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


def apply_inspector_command(
    command: str,
    issue: InspectIssue,
    intent_suggestions: List[IntentSuggestion],
    domain_suggestions: List[str],
    input_func: InputFunc,
) -> str:
    """Apply one inspector command and return the navigation action."""

    stripped_command = command.strip()

    if stripped_command == "":
        return "save_next"

    if stripped_command in {"1", "2", "3", "4", "5"}:
        suggestion_index = int(stripped_command) - 1
        if suggestion_index < len(intent_suggestions):
            issue.responsibility["intent"] = intent_suggestions[suggestion_index].text
        return "stay"

    if stripped_command.startswith("6"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("intent: ").strip()
        if value:
            issue.responsibility["intent"] = value
        return "stay"

    if stripped_command in {"a", "s", "d", "f"}:
        domain_index = {"a": 0, "s": 1, "d": 2, "f": 3}[stripped_command]
        if domain_index < len(domain_suggestions):
            issue.responsibility["domain"] = domain_suggestions[domain_index]
        return "stay"

    if stripped_command.startswith("g"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("domain: ").strip()
        if value:
            issue.responsibility["domain"] = value
        return "stay"

    if stripped_command in {"z", "x", "c", "v"}:
        issue.responsibility["lifecycle"] = {
            "z": "active",
            "x": "experimental",
            "c": "legacy",
            "v": "deprecated",
        }[stripped_command]
        return "stay"

    if stripped_command.startswith("n"):
        value = stripped_command[1:].strip()
        if not value:
            current_name = issue.responsibility.get("name", "")
            value = input_func(f"name [{current_name}]: ").strip()
        if value:
            issue.responsibility["name"] = value
        return "stay"

    if stripped_command.startswith("o"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("observations: ").strip()
        if value:
            issue.responsibility["notes"] = value
        return "stay"

    if stripped_command == "b":
        return "back"

    if stripped_command == "q":
        return "quit"

    if stripped_command == "h":
        return "help"

    return "unknown"


def _validate_required_fields(
    responsibility: Dict[str, Any],
) -> List[str]:
    """Return list of missing required field names."""

    missing: List[str] = []
    for field_name in REQUIRED_SAVE_FIELDS:
        value = responsibility.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field_name)
    return missing


def _save_issue(session: InspectLoadResult, issue: InspectIssue) -> bool:
    """Save one issue and persist the blueprint."""

    if session.blueprint_path is None:
        return False

    if issue.add_on_accept:
        responsibilities = session.blueprint_data.setdefault("responsibilities", [])
        if not isinstance(responsibilities, list):
            return False
        if issue.responsibility not in responsibilities:
            responsibilities.append(issue.responsibility)
        issue.add_on_accept = False

    save_blueprint(
        blueprint_path=session.blueprint_path,
        blueprint_data=session.blueprint_data,
    )
    return True


def _record_learning_feedback(
    issue: InspectIssue,
    intent_suggestions: List[IntentSuggestion],
    domain_suggestions: List[str],
) -> None:
    """Record accepted intent/domain values for incremental learning."""

    intent_value = issue.responsibility.get("intent")
    if isinstance(intent_value, str) and intent_value.strip():
        normalized_intent = " ".join(intent_value.strip().split()).lower()
        suggested_intents = {
            " ".join(suggestion.text.strip().split()).lower()
            for suggestion in intent_suggestions
        }
        increment = 2 if normalized_intent in suggested_intents else 3
        record_intent_phrase(intent_value, increment=increment)

    domain_value = issue.responsibility.get("domain")
    if isinstance(domain_value, str) and domain_value.strip():
        normalized_domain = domain_value.strip().lower().replace("-", "_")
        suggested_domains = {domain.strip().lower().replace("-", "_") for domain in domain_suggestions}
        increment = 2 if normalized_domain in suggested_domains else 3
        record_domain_value(domain_value, increment=increment)


def run_text_inspector(
    project_root: Path,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> int:
    """Run the direct MVP inspector UI."""

    session = load_inspect_session(project_root=project_root)
    if session.blocked:
        print_func(session.message or "Inspector blocked.")
        return session.exit_code

    if not session.issues:
        if session.missing_declared_count:
            print_func("BPFW Inspector")
            print_func("")
            print_func("Code drift needs inspection.")
            print_func("")
            print_func("Code:")
            print_func(f"  discovered: {session.discovered_count}")
            print_func(f"  undeclared: {session.undeclared_count}")
            print_func(f"  missing declared: {session.missing_declared_count}")
            print_func("")
            print_func("Next:")
            print_func("  Run bpfw verify for the full drift list.")
            return 1
        if session.authority_state == AUTHORITY_STATE_EMPTY:
            print_func("No responsibilities to complete.")
        else:
            print_func("All responsibilities are already complete.")
        return 0

    return run_text_inspector_session(
        session=session,
        input_func=input_func,
        print_func=print_func,
    )


def run_text_inspector_session(
    session: InspectLoadResult,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> int:
    """Run text inspector against an already loaded session."""

    current_index = 0
    total = len(session.issues)
    existing_intents = collect_existing_intents(session.blueprint_data)
    while current_index < total:
        issue = session.issues[current_index]
        responsibility = issue.responsibility
        if issue.issue_type != ISSUE_NEW_DETECTED:
            apply_suggestions(responsibility)

        intent_suggestions = suggest_intents(
            responsibility,
            existing_intents=existing_intents,
        )
        domain_suggestions = suggest_domains(responsibility)

        render_text_inspector_screen(
            project_root=session.project_root,
            issue_type=issue.issue_type,
            responsibility=responsibility,
            index=current_index,
            total=total,
            intent_suggestions=intent_suggestions,
            domain_suggestions=domain_suggestions,
            print_func=print_func,
        )
        try:
            raw_command = input_func("> ")
        except EOFError:
            print_func("Interactive inspector input unavailable.")
            print_func("")
            print_func("Next:")
            print_func("  Run bpfw inspector in an interactive terminal.")
            return 1

        action = apply_inspector_command(
            command=raw_command,
            issue=issue,
            intent_suggestions=intent_suggestions,
            domain_suggestions=domain_suggestions,
            input_func=input_func,
        )

        if action == "save_next":
            missing_fields = _validate_required_fields(responsibility)
            if missing_fields:
                _render_notification_block(
                    title="Cannot save",
                    lines=[f"Missing required fields: {', '.join(missing_fields)}"],
                    print_func=print_func,
                    width=_compute_notification_width(),
                )
                continue
            _record_learning_feedback(
                issue=issue,
                intent_suggestions=intent_suggestions,
                domain_suggestions=domain_suggestions,
            )
            if not _save_issue(session=session, issue=issue):
                print_func("Blueprint path is unavailable.")
                return 1
            print_func("Saved.")
            current_index += 1
            continue

        if action == "back":
            current_index = max(0, current_index - 1)
            continue

        if action == "quit":
            print_func("Inspector stopped.")
            return 0

        if action == "help":
            _render_help_block(print_func=print_func, width=_compute_help_width())
            try:
                input_func("Press any key then Enter to continue...")
            except EOFError:
                print_func("Interactive inspector input unavailable.")
                print_func("")
                print_func("Next:")
                print_func("  Run bpfw inspector in an interactive terminal.")
                return 1
            continue

        if action == "unknown":
            _render_notification_block(
                title="Unknown command",
                lines=[
                    "Use 1/2/3/4/5/6, a/s/d/f, g<domain>, z/x/c/v, n, o(observations), Enter, b, h, or q."
                ],
                print_func=print_func,
                width=_compute_notification_width(),
            )

    print_func("")
    print_func("Inspector completed.")
    print_func("")
    print_func("Next:")
    print_func("  bpfw verify")
    print_func("  bpfw lock")
    return 0
