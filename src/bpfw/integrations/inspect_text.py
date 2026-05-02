"""Text inspect UI for BPFW catalog completion."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict

from bpfw.catalog.models import AUTHORITY_STATE_EMPTY
from bpfw.integrations.inspect_base import (
    ALLOWED_LIFECYCLES,
    InspectLoadResult,
    apply_suggestions,
    build_authority_lines,
    build_code_lines,
    build_suggestion_lines,
    clean_string,
    load_inspect_session,
    save_blueprint,
    validate_ready_to_accept,
)

InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


def _location_header(responsibility: Dict[str, Any]) -> tuple[str, str]:
    location = responsibility.get("location", {})
    if not isinstance(location, dict):
        return "unknown :: unknown", "unknown  lines -"

    path = clean_string(location.get("path")) or "unknown"
    symbol = clean_string(location.get("symbol")) or "unknown"
    symbol_type = clean_string(location.get("symbol_type")) or "unknown"
    start_line = location.get("start_line")
    end_line = location.get("end_line")
    if isinstance(start_line, int) and isinstance(end_line, int):
        line_text = f"lines {start_line}-{end_line}"
    else:
        line_text = "lines -"
    return f"{path} :: {symbol}", f"{symbol_type}  {line_text}"


def render_text_screen(
    project_root: Path,
    responsibility: Dict[str, Any],
    index: int,
    total: int,
    print_func: PrintFunc = print,
) -> None:
    """Render the free text inspect screen."""

    location_line, kind_line = _location_header(responsibility)
    print_func("")
    print_func(f"BPFW Inspect  {index + 1}/{total}  draft")
    print_func("")
    print_func(location_line)
    print_func(kind_line)
    print_func("")
    print_func("Code")
    for code_line in build_code_lines(project_root, responsibility)[:10]:
        print_func(f"  {code_line}")
    print_func("")
    print_func("Authority")
    for line in build_authority_lines(responsibility):
        print_func(line)
    print_func("")
    print_func("Suggestions")
    for line in build_suggestion_lines(responsibility):
        print_func(line)
    print_func("")
    print_func("Actions")
    print_func("  [i] intent   [o] owner   [l] lifecycle   [n] notes")
    print_func("  [a] accept   [s] skip    [b] back        [q] quit")
    print_func("")


def _edit_text_field(
    responsibility: Dict[str, Any],
    field_name: str,
    input_func: InputFunc,
) -> None:
    current_value = clean_string(responsibility.get(field_name)) or ""
    prompt = f"{field_name} [{current_value}]: "
    value = input_func(prompt).strip()
    if value:
        responsibility[field_name] = value


def _edit_lifecycle(
    responsibility: Dict[str, Any],
    input_func: InputFunc,
    print_func: PrintFunc,
) -> None:
    current_value = clean_string(responsibility.get("lifecycle")) or "active"
    while True:
        value = input_func(f"lifecycle [{current_value}]: ").strip() or current_value
        if value in ALLOWED_LIFECYCLES:
            responsibility["lifecycle"] = value
            return
        print_func("Invalid lifecycle. Use active, experimental, legacy, or deprecated.")


def run_text_inspect(
    project_root: Path,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> int:
    """Run the free text inspect UI."""

    session = load_inspect_session(project_root=project_root)
    if session.blocked:
        print_func(session.message or "Inspect blocked.")
        return session.exit_code

    if not session.incomplete:
        if session.authority_state == AUTHORITY_STATE_EMPTY:
            print_func("No responsibilities to complete.")
        else:
            print_func("All responsibilities are already complete.")
        return 0

    return run_text_inspect_session(
        session=session,
        input_func=input_func,
        print_func=print_func,
    )


def run_text_inspect_session(
    session: InspectLoadResult,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> int:
    """Run text inspect against an already loaded session."""

    current_index = 0
    total = len(session.incomplete)
    while current_index < total:
        responsibility = session.incomplete[current_index]
        apply_suggestions(responsibility)
        render_text_screen(
            project_root=session.project_root,
            responsibility=responsibility,
            index=current_index,
            total=total,
            print_func=print_func,
        )
        try:
            action = input_func("> ").strip().lower()
        except EOFError:
            print_func("Interactive inspect input unavailable.")
            print_func("")
            print_func("Next:")
            print_func("  Run bpfw inspect in an interactive terminal.")
            return 1

        if action == "i":
            _edit_text_field(responsibility, "intent", input_func)
            continue
        if action == "o":
            _edit_text_field(responsibility, "owner_layer", input_func)
            continue
        if action == "l":
            _edit_lifecycle(responsibility, input_func, print_func)
            continue
        if action == "n":
            _edit_text_field(responsibility, "notes", input_func)
            continue
        if action == "a":
            missing_fields = validate_ready_to_accept(responsibility)
            if missing_fields:
                print_func(f"Missing required fields: {', '.join(missing_fields)}")
                continue
            if session.blueprint_path is None:
                print_func("Blueprint path is unavailable.")
                return 1
            save_blueprint(
                blueprint_path=session.blueprint_path,
                blueprint_data=session.blueprint_data,
            )
            print_func("Saved.")
            current_index += 1
            continue
        if action == "s":
            current_index += 1
            continue
        if action == "b":
            current_index = max(0, current_index - 1)
            continue
        if action == "q":
            if session.blueprint_path is not None:
                save_blueprint(
                    blueprint_path=session.blueprint_path,
                    blueprint_data=session.blueprint_data,
                )
            print_func("Saved. Inspect stopped.")
            return 0

        print_func("Unknown action. Use i, o, l, n, a, s, b, or q.")

    print_func("")
    print_func("Inspect completed.")
    print_func("")
    print_func("Next:")
    print_func("  bpfw verify")
    print_func("  bpfw lock")
    return 0
