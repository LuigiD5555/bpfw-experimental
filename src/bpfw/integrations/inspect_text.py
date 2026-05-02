"""Text inspect UI for BPFW catalog completion."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict

from bpfw.catalog.models import AUTHORITY_STATE_EMPTY
from bpfw.integrations.inspect_base import (
    ALLOWED_LIFECYCLES,
    ISSUE_NEW_DETECTED,
    InspectLoadResult,
    InspectIssue,
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


def render_drift_summary(
    session: InspectLoadResult,
    print_func: PrintFunc = print,
) -> None:
    """Render code drift that still needs inspection."""

    print_func("BPFW Inspect")
    print_func("")
    print_func("Code drift needs inspection.")
    print_func("")
    print_func("Code:")
    print_func(f"  discovered: {session.discovered_count}")
    print_func(f"  undeclared: {session.undeclared_count}")
    print_func(f"  missing declared: {session.missing_declared_count}")
    print_func("")
    print_func("Findings:")
    for finding in (session.drift_findings or [])[:10]:
        print_func(f"  [{finding.code}] {finding.path or '-'} :: {finding.symbol or '-'}")

    remaining_count = max(0, len(session.drift_findings or []) - 10)
    if remaining_count:
        print_func(f"  ... {remaining_count} more")

    print_func("")
    print_func("Next:")
    print_func("  Run bpfw verify for the full drift list.")


def render_text_screen(
    project_root: Path,
    issue_type: str,
    responsibility: Dict[str, Any],
    index: int,
    total: int,
    print_func: PrintFunc = print,
) -> None:
    """Render the free text inspect screen."""

    location_line, kind_line = _location_header(responsibility)
    print_func("")
    print_func(f"BPFW Inspect  {index + 1}/{total}  {issue_type}")
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
    print_func("  [i] intent      [c] canonical    [o] owner")
    print_func("  [l] lifecycle   [n] notes        [a] accept")
    print_func("  [s] skip        [b] back         [q] quit")
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


def _accept_issue(session: InspectLoadResult, issue: InspectIssue) -> bool:
    """Accept one issue and persist the blueprint."""

    missing_fields = validate_ready_to_accept(issue.responsibility)
    if missing_fields:
        return False
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

    if not session.issues:
        if session.missing_declared_count:
            render_drift_summary(session=session, print_func=print_func)
            return 1
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
    total = len(session.issues)
    while current_index < total:
        issue = session.issues[current_index]
        responsibility = issue.responsibility
        if issue.issue_type != ISSUE_NEW_DETECTED:
            apply_suggestions(responsibility)
        render_text_screen(
            project_root=session.project_root,
            issue_type=issue.issue_type,
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
        if action == "c":
            _edit_text_field(responsibility, "canonical_name", input_func)
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
            if not _accept_issue(session=session, issue=issue):
                print_func("Blueprint path is unavailable.")
                return 1
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
            print_func("Inspect stopped.")
            return 0

        print_func("Unknown action. Use i, c, o, l, n, a, s, b, or q.")

    print_func("")
    print_func("Inspect completed.")
    print_func("")
    print_func("Next:")
    print_func("  bpfw verify")
    print_func("  bpfw lock")
    return 0
