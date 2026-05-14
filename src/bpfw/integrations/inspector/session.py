"""Interactive session runner for the inspector integration."""

from collections.abc import Callable
from pathlib import Path
from typing import List

from bpfw.catalog.purpose_suggestions import PurposeSuggestion, suggest_purposes
from bpfw.catalog.learning import record_domain_value, record_purpose_phrase
from bpfw.catalog.models import AUTHORITY_STATE_EMPTY
from bpfw.catalog.schema import get_blocks, get_purpose, set_blocks
from bpfw.integrations.inspector.base import (
    ISSUE_NEW_DETECTED,
    InspectIssue,
    InspectLoadResult,
    apply_suggestions,
    backfill_detected_docstring_from_source,
    collect_existing_purposes,
    load_inspect_session,
    save_blueprint,
    suggest_domains,
)
from bpfw.integrations.inspector.commands import (
    CUSTOM_DOMAIN_KEY,
    DOMAIN_SUGGESTION_KEYS,
    apply_inspector_command,
    run_interface_edit_submode,
)
from bpfw.integrations.inspector.validation import validate_required_fields
from bpfw.integrations.inspector.screen import (
    DEFAULT_INSPECTOR_HEADER_TITLE,
    render_inspector_screen,
)
from bpfw.integrations.shared.cli_runtime import normalize_command, quit_command_label

InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


def run_text_inspector(
    project_root: Path,
    header_title: str = DEFAULT_INSPECTOR_HEADER_TITLE,
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
            print_func("No blocks to complete.")
        else:
            print_func("All blocks are already complete.")
        return 0

    return run_text_inspector_session(
        session=session,
        header_title=header_title,
        input_func=input_func,
        print_func=print_func,
    )


def run_text_inspector_session(
    session: InspectLoadResult,
    header_title: str = DEFAULT_INSPECTOR_HEADER_TITLE,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> int:
    """Run text inspector against an already loaded session."""

    current_index = 0
    total = len(session.issues)
    existing_purposes = collect_existing_purposes(session.blueprint_data)
    suggestion_cache: dict[str, list] = {}
    while current_index < total:
        issue = session.issues[current_index]
        block = issue.block
        if issue.issue_type != ISSUE_NEW_DETECTED:
            apply_suggestions(block)

        cache_key = block.get("id") or ""
        if not cache_key:
            code = block.get("code") or block.get("location") or {}
            cache_key = f"{code.get('path', '')}:{code.get('symbol', '')}"

        if cache_key in suggestion_cache:
            purpose_suggestions, domain_suggestions = suggestion_cache[cache_key]
        else:
            backfill_detected_docstring_from_source(
                project_root=session.project_root,
                block=block,
            )
            purpose_suggestions = suggest_purposes(
                block,
                existing_purposes=existing_purposes,
            )
            domain_suggestions = suggest_domains(block, project_blocks=get_blocks(session.blueprint_data))
            if cache_key:
                suggestion_cache[cache_key] = (purpose_suggestions, domain_suggestions)

        render_inspector_screen(
            project_root=session.project_root,
            issue_type=issue.issue_type,
            block=block,
            index=current_index,
            total=total,
            purpose_suggestions=purpose_suggestions,
            domain_suggestions=domain_suggestions,
            header_title=header_title,
            print_func=print_func,
        )
        try:
            raw_command = input_func("> ")
            action = apply_inspector_command(
                command=normalize_command(raw_command),
                issue=issue,
                purpose_suggestions=purpose_suggestions,
                domain_suggestions=domain_suggestions,
                input_func=input_func,
            )
        except EOFError:
            print_func("Interactive inspector input unavailable.")
            print_func("")
            print_func("Next:")
            print_func("  Run bpfw inspector in an interactive terminal.")
            return 1
        except KeyboardInterrupt:
            print_func("Inspector stopped.")
            return 0

        if action == "save_next":
            missing_fields = validate_required_fields(block)
            if missing_fields:
                for line in _render_missing_fields_notification(missing_fields):
                    print_func(line)
                continue
            _record_learning_feedback(
                issue=issue,
                purpose_suggestions=purpose_suggestions,
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
            for line in _render_help_block():
                print_func(line)
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
            for line in _render_unknown_command_notification():
                print_func(line)

        if action == "interface_edit":
            run_interface_edit_submode(
                block=block,
                input_func=input_func,
                print_func=print_func,
            )
            continue

    print_func("")
    print_func("Inspector completed.")
    print_func("")
    print_func("Next:")
    print_func("  bpfw verify")
    print_func("  bpfw lock")
    return 0


def _save_issue(session: InspectLoadResult, issue: InspectIssue) -> bool:
    """Save one issue and persist the blueprint."""

    if session.blueprint_path is None:
        return False

    if issue.add_on_accept:
        blocks = get_blocks(session.blueprint_data)
        if not isinstance(blocks, list):
            return False
        if issue.block not in blocks:
            blocks.append(issue.block)
        set_blocks(session.blueprint_data, blocks)
        issue.add_on_accept = False

    save_blueprint(
        blueprint_path=session.blueprint_path,
        blueprint_data=session.blueprint_data,
    )
    return True


def _record_learning_feedback(
    issue: InspectIssue,
    purpose_suggestions: List[PurposeSuggestion],
    domain_suggestions: List[str],
) -> None:
    """Record accepted purpose/domain values for incremental learning."""

    purpose_value = get_purpose(issue.block)
    if isinstance(purpose_value, str) and purpose_value.strip():
        normalized_purpose = " ".join(purpose_value.strip().split()).lower()
        suggested_purposes = {
            " ".join(suggestion.text.strip().split()).lower()
            for suggestion in purpose_suggestions
        }
        increment = 2 if normalized_purpose in suggested_purposes else 3
        record_purpose_phrase(purpose_value, increment=increment)

    domain_value = issue.block.get("domain")
    if isinstance(domain_value, str) and domain_value.strip():
        normalized_domain = domain_value.strip().lower().replace("-", "_")
        suggested_domains = {domain.strip().lower().replace("-", "_") for domain in domain_suggestions}
        increment = 2 if normalized_domain in suggested_domains else 3
        record_domain_value(domain_value, increment=increment)


def _render_missing_fields_notification(missing_fields: list[str]) -> list[str]:
    """Render notification for missing required fields."""

    from bpfw.integrations.shared.visual_notifications import render_notification_block

    lines = [f"Missing required fields: {', '.join(missing_fields)}"]
    return render_notification_block(
        title="Cannot save",
        lines=lines,
        width=_compute_notification_width(),
    )


def _render_unknown_command_notification() -> list[str]:
    """Render notification for unknown command."""

    from bpfw.integrations.shared.visual_notifications import render_notification_block

    lines = [
        "Use 1/2/3/4/5/6, a/s/d/f, g<domain>, z/x/c/v, n, o(notes), Enter, b, h, or q."
    ]
    return render_notification_block(
        title="Unknown command",
        lines=lines,
        width=_compute_notification_width(),
    )


def _render_help_block() -> list[str]:
    """Render inspector help for field meaning and command options."""

    from bpfw.integrations.shared.visual_notifications import render_notification_block

    help_lines = [
        "",
        "  Authority fields",
        "  ────────────────",
        "  purpose       What this block is supposed to do.",
        "  domain        Where this block belongs in the system.",
        "  name          Simple block name.",
        "  notes         Optional notes for this block.",
        "  interface     Input and output type definitions.",
        "",
        "  status        Current block status.",
        "                active        In use now.",
        "                experimental  Still being tested.",
        "                legacy        Old, but still kept.",
        "                deprecated    Should be replaced or removed later.",
        "",
        "  Selection",
        "  ─────────",
        "  [1-5]      Choose suggested purpose",
        "  [6]        Write custom purpose",
        f"  [{'|'.join(DOMAIN_SUGGESTION_KEYS)}]  Choose suggested domain",
        f"  [{CUSTOM_DOMAIN_KEY}]        Write custom domain",
        "  [z|x|c|v]  Set status",
        "",
        "  Editing",
        "  ───────",
        "  [n]        Edit name",
        "  [o]        Edit notes",
        "  [i]        Edit interface",
        "",
        "  Flow",
        "  ────",
        "  [Enter]    Save and continue",
        "  [b]        Back",
        "  [h]        Toggle help",
        f"  {quit_command_label('Quit'):<10}",
        "",
    ]
    return render_notification_block(
        title="Inspector help",
        lines=help_lines,
        width=_compute_help_width(),
    )


def _compute_help_width() -> int:
    """Compute compact dynamic width for the help panel."""

    import shutil
    from bpfw.integrations.shared.visual_width import display_width, measure_lines

    sample_lines = [
        "  domain        Where this block belongs in the system.",
        "                deprecated    Should be replaced or removed later.",
        f"  [{'|'.join(DOMAIN_SUGGESTION_KEYS)}]  Choose suggested domain",
        "  [Enter]    Save and continue",
    ]
    required_width = max(measure_lines(sample_lines), display_width("Inspector help") + 2) + 2
    terminal_width = shutil.get_terminal_size(fallback=(100, 30)).columns
    total_width = min(max(required_width + 2, 72), terminal_width)
    return max(20, total_width - 2)


def _compute_notification_width() -> int:
    """Compute standard inner width for standalone notification panels."""

    import shutil

    terminal_width = shutil.get_terminal_size(fallback=(100, 30)).columns
    total_width = min(max(72, 72), terminal_width)
    return max(20, total_width - 2)
