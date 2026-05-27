"""Interactive session runner for the inspector integration."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bpfw.integrations.inspector.suggestions.domain.engine import suggest_domains
from bpfw.core.catalog.models import AUTHORITY_STATE_EMPTY
from bpfw.integrations.inspector.base import (
    ISSUE_NEW_DETECTED,
    InspectLoadResult,
    apply_suggestions,
    backfill_detected_docstring_from_source,
    collect_existing_purposes,
    load_inspect_session,
    load_metadata_inspect_session,
)
from bpfw.integrations.inspector.commands import apply_inspector_command
from bpfw.integrations.inspector.drift_gate import (
    DriftGateResult,
    merge_drift_gate_into_session,
    rebuild_metadata_issues_after_authority_changes,
    run_drift_gate,
)
from bpfw.integrations.inspector.drift_state import DriftState, DriftStateRepository
from bpfw.integrations.diff.models import DiffItem
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


@dataclass(slots=True)
class CachedDriftPreflight:
    """Precomputed drift state inputs for inspector startup.

    Attributes:
        repository: Drift state repository.
        state: Persisted drift state.
        input_signature: Current project input signature, or the persisted
            signature when pending work is restored before filesystem validation.
        trusted_pending_snapshot: Whether pending work was loaded directly from
            the persisted snapshot to avoid recomputing drift inputs before UI.
    """

    repository: DriftStateRepository
    state: DriftState
    input_signature: str
    trusted_pending_snapshot: bool = False
    trusted_pending_snapshot: bool = False


def run_text_inspector(
    project_root: Path,
    header_title: str = DEFAULT_INSPECTOR_HEADER_TITLE,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
    show_all: bool = False,
) -> int:
    """Run the direct MVP inspector UI."""

    with _profiler.measure("inspector.open_ui_total"):
        preflight = _load_drift_preflight(project_root=project_root)
        cached_pending = _try_load_cached_pending_preflight(project_root=project_root, preflight=preflight)
        used_minimal_pending_session = False
        if cached_pending is not None:
            session, pending_items = cached_pending
            used_minimal_pending_session = True
            if session.blocked:
                print_func(session.message or "Inspector blocked.")
                return session.exit_code
            try:
                with _profiler.measure("inspector.drift_gate.cached_pending"):
                    drift_gate_result = run_drift_gate(
                        session=session,
                        input_func=input_func,
                        print_func=print_func,
                        cached_human_items=pending_items,
                        drift_state=preflight.state,
                        input_signature=preflight.input_signature,
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
        else:
            cached_preflight = _try_load_cached_preflight(project_root=project_root, preflight=preflight)
            if cached_preflight is not None:
                session, drift_gate_result = cached_preflight
                if session.blocked:
                    print_func(session.message or "Inspector blocked.")
                    return session.exit_code
            else:
                session = load_inspect_session(project_root=project_root)
                if session.blocked:
                    print_func(session.message or "Inspector blocked.")
                    return session.exit_code

                try:
                    drift_gate_result = run_drift_gate(
                        session=session,
                        input_func=input_func,
                        print_func=print_func,
                        drift_state=preflight.state,
                        input_signature=preflight.input_signature,
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

        if drift_gate_result.stopped:
            return drift_gate_result.exit_code

        if drift_gate_result.changed_project_state():
            with _profiler.measure("inspector.reload_after_authority_change"):
                session = load_inspect_session(project_root=project_root)
            if session.blocked:
                print_func(session.message or "Inspector blocked.")
                return session.exit_code
            rebuild_metadata_issues_after_authority_changes(session)
        elif used_minimal_pending_session:
            with _profiler.measure("inspector.metadata_session_after_cached_gate"):
                session = load_metadata_inspect_session(project_root=project_root)
            if session.blocked:
                print_func(session.message or "Inspector blocked.")
                return session.exit_code

        merge_drift_gate_into_session(session=session, result=drift_gate_result)

        if not session.issues:
            _render_no_inspector_work(session=session, drift_gate_result=drift_gate_result, print_func=print_func)
            return 0

        return run_text_inspector_session(
            session=session,
            header_title=header_title,
            input_func=input_func,
            print_func=print_func,
            show_all=show_all,
        )


def _load_drift_preflight(project_root: Path) -> CachedDriftPreflight:
    """Load drift state and compute only the signature required for this run.

    Pending human drift decisions are durable work. When such work exists, the
    Inspector should show it immediately instead of walking the whole project
    just to prove what the user has not resolved yet. A full input signature is
    rebuilt only when no pending snapshot can be reused.

    Args:
        project_root: Project root directory.

    Returns:
        Cached drift preflight data.
    """
    with _profiler.measure("inspector.preflight.total"):
        repository = DriftStateRepository(project_root)
        with _profiler.measure("inspector.preflight.load_drift_state"):
            state = repository.load()
        if state.has_pending_items() and state.input_signature is not None:
            return CachedDriftPreflight(
                repository=repository,
                state=state,
                input_signature=state.input_signature,
                trusted_pending_snapshot=True,
            )
        with _profiler.measure("inspector.preflight.input_signature"):
            input_signature = repository.build_input_signature()
        return CachedDriftPreflight(repository=repository, state=state, input_signature=input_signature)


def _try_load_cached_pending_preflight(
    project_root: Path,
    preflight: CachedDriftPreflight,
) -> tuple[InspectLoadResult, list[DiffItem]] | None:
    """Load pending Drift Gate items without full scan/verify when inputs are unchanged.

    Args:
        project_root: Project root directory.
        preflight: Current drift preflight data.

    Returns:
        Metadata-only session and cached pending items, or None.
    """
    if preflight.trusted_pending_snapshot:
        if not preflight.state.has_pending_items():
            return None
    elif not preflight.state.has_reusable_pending_items(preflight.input_signature):
        return None
    session = _build_minimal_pending_drift_session(project_root=project_root)
    return session, preflight.state.restored_pending_items()


def _build_minimal_pending_drift_session(project_root: Path) -> InspectLoadResult:
    """Build a minimal session for cached Drift Gate rendering.

    This avoids loading authority, scanning code, or running verify before a
    cached pending Drift Gate item is shown. Metadata is loaded only after the
    Drift Gate completes and inspection is actually needed.

    Args:
        project_root: Project root directory.

    Returns:
        Minimal inspector load result suitable for cached Drift Gate review.
    """
    resolved_root = project_root.resolve()
    return InspectLoadResult(
        project_root=resolved_root,
        blueprint_path=None,
        blueprint_data={},
        incomplete=[],
        issues=[],
        authority_state="cached_pending_drift",
    )


def _try_load_cached_preflight(
    project_root: Path,
    preflight: CachedDriftPreflight | None = None,
) -> tuple[InspectLoadResult, DriftGateResult] | None:
    """Load metadata-only session when drift state proves inputs unchanged.

    Args:
        project_root: Project root directory.
        preflight: Optional precomputed drift preflight data.

    Returns:
        Tuple of metadata-only session and DriftGateResult, or None when full
        analysis is required.
    """
    if preflight is None:
        preflight = _load_drift_preflight(project_root=project_root)
    if not preflight.state.is_reusable_for_signature(preflight.input_signature):
        return None
    session = load_metadata_inspect_session(project_root=project_root)
    result = DriftGateResult(cache_hit=True)
    for issue in preflight.state.restored_inspector_issues():
        result.approved_count += 1
        result.inspector_issues.append(issue)
    result.reused_decision_count = len(preflight.state.decisions)
    return session, result


def _render_no_inspector_work(session: InspectLoadResult, drift_gate_result, print_func: PrintFunc) -> None:  # noqa: ANN001
    """Render the final no-work inspector message.

    Args:
        session: Loaded inspector session.
        drift_gate_result: Result from Drift Gate.
        print_func: Function used to print output.
    """
    print_func("BPFW Inspector")
    if drift_gate_result.safe_mechanical_updates:
        print_func(f"Auto-sync: {drift_gate_result.safe_mechanical_updates} safe mechanical updates applied.")
    if drift_gate_result.skipped_count:
        print_func(f"Unresolved: {drift_gate_result.skipped_count} drift decisions skipped.")
    else:
        print_func("No human drift decisions required.")
    if session.authority_state == AUTHORITY_STATE_EMPTY:
        print_func("No blocks to complete.")
    else:
        print_func("All blocks are already complete.")
    print_func("No incomplete metadata found.")
    print_func("Next:")
    print_func("  bpfw verify")
    print_func("  bpfw lock")


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
            pre_inspection_context_lines=issue.context_lines or session.pre_inspection_context_lines,
            project_blocks=project_blocks if isinstance(project_blocks, list) else [],
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
