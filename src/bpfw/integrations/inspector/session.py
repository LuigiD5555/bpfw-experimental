"""Interactive session runner for the inspector integration."""

from collections.abc import Callable
from pathlib import Path

from bpfw.integrations.inspector.suggestions.domain.engine import suggest_domains
from bpfw.catalog.models import AUTHORITY_STATE_EMPTY
from bpfw.integrations.inspector.base import (
    ISSUE_NEW_DETECTED,
    InspectLoadResult,
    apply_suggestions,
    backfill_detected_docstring_from_source,
    collect_existing_purposes,
    load_inspect_session,
)
from bpfw.integrations.inspector.commands import apply_inspector_command
from bpfw.integrations.inspector.controller import (
    InspectorController,
)
from bpfw.integrations.inspector.input_adapter import InspectorInputReader
from bpfw.integrations.inspector.screen import (
    DEFAULT_INSPECTOR_HEADER_TITLE,
    render_inspector_screen,
)
from bpfw.integrations.inspector.state import InspectorViewState
from bpfw.integrations.inspector.view_modes import resolve_inspector_view_mode
from bpfw.integrations.shared.cli_runtime import normalize_command
from bpfw.integrations.inspector.suggestions.purpose.engine import suggest_purposes
from bpfw.core.profiling import RuntimeProfiler

_profiler = RuntimeProfiler()

InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


def run_text_inspector(
    project_root: Path,
    header_title: str = DEFAULT_INSPECTOR_HEADER_TITLE,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
    show_all: bool = False,
) -> int:
    """Run the direct MVP inspector UI."""

    with _profiler.measure("inspector.open_ui_total"):
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
            show_all=show_all,
        )


def run_text_inspector_session(
    session: InspectLoadResult,
    header_title: str = DEFAULT_INSPECTOR_HEADER_TITLE,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
    show_all: bool = False,
) -> int:
    """Run text inspector against an already loaded session."""

    total = len(session.issues)
    input_reader = InspectorInputReader(input_func)
    controller = InspectorController(
        session=session,
        input_reader=input_reader,
        print_func=print_func,
    )
    state = InspectorViewState.from_show_all(show_all=show_all)
    existing_purposes = collect_existing_purposes(session.blueprint_data)

    while state.is_running and state.current_index < total:
        issue = session.issues[state.current_index]
        block = issue.block
        if issue.issue_type != ISSUE_NEW_DETECTED:
            apply_suggestions(block)

        backfill_detected_docstring_from_source(
            project_root=session.project_root,
            block=block,
        )
        project_blocks = session.blueprint_data.get("blocks", [])
        purpose_suggestions = suggest_purposes(
            block,
            project_blocks=project_blocks,
            existing_purposes=existing_purposes,
        )
        domain_suggestions = suggest_domains(block, project_blocks=project_blocks)
        view_mode = resolve_inspector_view_mode(state.mode_name)

        render_inspector_screen(
            project_root=session.project_root,
            issue_type=issue.issue_type,
            block=block,
            index=state.current_index,
            total=total,
            purpose_suggestions=purpose_suggestions,
            domain_suggestions=domain_suggestions,
            header_title=header_title,
            print_func=print_func,
            view_mode=view_mode,
        )
        try:
            raw_command = input_reader.read("> ")
            action = apply_inspector_command(
                command=normalize_command(raw_command),
                issue=issue,
                purpose_suggestions=purpose_suggestions,
                domain_suggestions=domain_suggestions,
                input_func=input_reader.read,
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

        result = controller.handle_action(
            action=action,
            state=state,
            issue=issue,
            purpose_suggestions=purpose_suggestions,
            domain_suggestions=domain_suggestions,
            view_mode=view_mode,
        )
        if result.should_refresh_existing_purposes:
            existing_purposes = collect_existing_purposes(session.blueprint_data)
        if result.exit_code is not None:
            return result.exit_code

    print_func("")
    print_func("Inspector completed.")
    print_func("")
    print_func("Next:")
    print_func("  bpfw verify")
    print_func("  bpfw lock")
    return 0
