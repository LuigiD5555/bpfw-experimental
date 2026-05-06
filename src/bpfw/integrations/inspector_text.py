"""Text inspector UI for BPFW catalog completion."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List

from bpfw.catalog.intent_suggestions import IntentSuggestion, suggest_intents
from bpfw.catalog.models import AUTHORITY_STATE_EMPTY
from bpfw.integrations.inspector_base import (
    ISSUE_NEW_DETECTED,
    InspectIssue,
    InspectLoadResult,
    apply_suggestions,
    build_code_lines,
    clean_string,
    display_value,
    load_inspect_session,
    save_blueprint,
    suggest_domains,
)

InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]

REQUIRED_SAVE_FIELDS = ("intent", "canonical_name", "domain", "lifecycle")


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
    print_func(f"BPFW Inspector                         {index + 1}/{total} {issue_type}")
    print_func("")

    # Code preview
    for code_line in build_code_lines(project_root, responsibility)[:32]:
        print_func(f"  {code_line}")
    print_func("")

    # Authority section
    print_func("authority:")
    print_func(f"  intent:    {display_value(responsibility.get('intent'))}")
    print_func(f"  domain:    {display_value(responsibility.get('domain'))}")
    print_func(f"  name:      {display_value(responsibility.get('canonical_name'))}")
    print_func(f"  lifecycle: {display_value(responsibility.get('lifecycle'))}")
    print_func("")

    # Intent suggestions
    print_func("intent suggestions:")
    for suggestion_index, suggestion in enumerate(intent_suggestions[:3], start=1):
        print_func(f"  {suggestion_index}  {suggestion.text}")
    print_func("  +  write custom intent")
    print_func("")

    # Domain suggestions
    print_func("domain suggestions:")
    domain_labels = ("x", "y", "z")
    for domain_index, domain_label in enumerate(domain_labels):
        if domain_index < len(domain_suggestions):
            print_func(f"  {domain_label}  {domain_suggestions[domain_index]}")
    print_func("  w  write custom domain")
    print_func("")

    # Lifecycle
    print_func("lifecycle:")
    current_lifecycle = clean_string(responsibility.get("lifecycle")) or ""
    for lifecycle_value, lifecycle_label in (
        ("active", "a  active"),
        ("experimental", "e  experimental"),
        ("legacy", "l  legacy"),
        ("deprecated", "d  deprecated"),
    ):
        marker = " <--" if lifecycle_value == current_lifecycle else ""
        print_func(f"  {lifecycle_label}{marker}")
    print_func("")

    # Commands
    print_func("commands:")
    print_func("  1/2/3 intent   + <intent>   x/y/z domain   w <domain>")
    print_func("  a/e/l/d lifecycle   n <name>   o <notes>   Enter save+next")
    print_func("  b back   q quit")
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

    if stripped_command in {"1", "2", "3"}:
        suggestion_index = int(stripped_command) - 1
        if suggestion_index < len(intent_suggestions):
            issue.responsibility["intent"] = intent_suggestions[suggestion_index].text
        return "stay"

    if stripped_command.startswith("+"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("intent: ").strip()
        if value:
            issue.responsibility["intent"] = value
        return "stay"

    if stripped_command in {"x", "y", "z"}:
        domain_index = {"x": 0, "y": 1, "z": 2}[stripped_command]
        if domain_index < len(domain_suggestions):
            issue.responsibility["domain"] = domain_suggestions[domain_index]
        return "stay"

    if stripped_command.startswith("w"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("domain: ").strip()
        if value:
            issue.responsibility["domain"] = value
        return "stay"

    if stripped_command in {"a", "e", "l", "d"}:
        issue.responsibility["lifecycle"] = {
            "a": "active",
            "e": "experimental",
            "l": "legacy",
            "d": "deprecated",
        }[stripped_command]
        return "stay"

    if stripped_command.startswith("n"):
        value = stripped_command[1:].strip()
        if not value:
            current_name = issue.responsibility.get("canonical_name", "")
            value = input_func(f"name [{current_name}]: ").strip()
        if value:
            issue.responsibility["canonical_name"] = value
        return "stay"

    if stripped_command.startswith("o"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("notes: ").strip()
        if value:
            issue.responsibility["notes"] = value
        return "stay"

    if stripped_command == "b":
        return "back"

    if stripped_command == "q":
        return "quit"

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
    while current_index < total:
        issue = session.issues[current_index]
        responsibility = issue.responsibility
        if issue.issue_type != ISSUE_NEW_DETECTED:
            apply_suggestions(responsibility)

        intent_suggestions = suggest_intents(responsibility)
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
                print_func("Cannot save. Missing required fields:")
                for missing_field in missing_fields:
                    print_func(f"  {missing_field}")
                continue
            if not _save_issue(session=session, issue=issue):
                print_func("Blueprint path is unavailable.")
                return 1
            print_func("Saved.")
            # Reload session after save for reliable back navigation
            session = load_inspect_session(project_root=session.project_root)
            total = len(session.issues)
            current_index += 1
            continue

        if action == "back":
            current_index = max(0, current_index - 1)
            # Reload session to get saved data for the previous issue
            session = load_inspect_session(project_root=session.project_root)
            total = len(session.issues)
            continue

        if action == "quit":
            print_func("Inspector stopped.")
            return 0

        if action == "unknown":
            print_func(
                "Unknown command. Use 1/2/3/+, x/y/z/w, a/e/l/d, n, o, Enter, b, or q."
            )

    print_func("")
    print_func("Inspector completed.")
    print_func("")
    print_func("Next:")
    print_func("  bpfw verify")
    print_func("  bpfw lock")
    return 0