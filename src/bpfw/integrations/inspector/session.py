"""Interactive session runner for the inspector integration."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bpfw.integrations.inspector.suggestions.domain.engine import suggest_domains
from bpfw.core.catalog.models import AUTHORITY_STATE_EMPTY
from bpfw.integrations.inspector.base import (
    ISSUE_DRAFT,
    ISSUE_NEW_DETECTED,
    REQUIRED_HUMAN_FIELDS,
    InspectIssue,
    InspectLoadResult,
    apply_suggestions,
    backfill_detected_docstring_from_source,
    collect_existing_purposes,
    load_inspect_session,
    has_uninspectable_source_issues,
    load_metadata_inspect_session,
    sort_inspect_issues_hierarchically,
    split_issues_by_source_availability,
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


@dataclass(slots=True)
class RestoredIssueFilterResult:
    """Filtered inspector issues restored from persisted Drift Gate decisions.

    Attributes:
        issues: Issues that are still valid metadata work.
        stale_count: Number of restored approvals that no longer point to an
            inspectable source file.
    """

    issues: list[InspectIssue]
    stale_count: int = 0


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
            if (
                not drift_gate_result.inspector_issues
                and has_uninspectable_source_issues(project_root=session.project_root, issues=session.issues)
            ):
                session = load_inspect_session(project_root=project_root)
                if session.blocked:
                    print_func(session.message or "Inspector blocked.")
                    return session.exit_code
                fresh_input_signature = preflight.repository.build_input_signature()
                try:
                    drift_gate_result = run_drift_gate(
                        session=session,
                        input_func=input_func,
                        print_func=print_func,
                        drift_state=preflight.state,
                        input_signature=fresh_input_signature,
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
                    session = load_inspect_session(project_root=project_root)
                    if session.blocked:
                        print_func(session.message or "Inspector blocked.")
                        return session.exit_code
                    rebuild_metadata_issues_after_authority_changes(session)

        merge_drift_gate_into_session(session=session, result=drift_gate_result)

        inspectable_issues, stale_issues = split_issues_by_source_availability(
            project_root=session.project_root,
            issues=session.issues,
        )
        if stale_issues and _should_block_on_stale_metadata_queue(drift_gate_result):
            print_func("Inspector blocked.")
            print_func("Reason: Metadata queue contains code references whose source files no longer exist.")
            print_func("These are structural drift items and must be resolved in Drift Gate before metadata inspection.")
            return 1
        if stale_issues:
            session.pre_inspection_context_lines = [
                *session.pre_inspection_context_lines,
                (
                    "Metadata queue: discarded "
                    f"{len(stale_issues)} stale code references after Drift Gate reconciliation."
                ),
            ]
        session.issues = inspectable_issues

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



def _should_block_on_stale_metadata_queue(drift_gate_result: DriftGateResult) -> bool:
    """Return whether stale metadata issues should block Inspector startup.

    Stale source references are structural drift when they are found while
    resuming metadata work from cache. However, after a fresh Drift Gate pass or
    after authority changes have just been applied, stale metadata issues are
    obsolete cached work. Blocking at that point prevents Inspector from opening
    even though Drift Gate already had the chance to resolve the structural
    drift.

    Args:
        drift_gate_result: Result produced by the current Drift Gate run.

    Returns:
        True when Inspector should stop and force Drift Gate, otherwise False so
        the stale metadata items can be discarded.
    """

    return (
        drift_gate_result.cache_hit
        and drift_gate_result.reviewed_human_item_count == 0
        and drift_gate_result.approved_count == 0
        and not drift_gate_result.changed_project_state()
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
    """Load metadata-only session when drift state can resume inspector work.

    Args:
        project_root: Project root directory.
        preflight: Optional precomputed drift preflight data.

    Returns:
        Tuple of metadata-only session and DriftGateResult, or None when full
        analysis is required.
    """
    if preflight is None:
        preflight = _load_drift_preflight(project_root=project_root)

    approved_resume = _try_load_approved_metadata_resume(
        project_root=project_root,
        preflight=preflight,
    )
    if approved_resume is not None:
        return approved_resume

    if not preflight.state.is_reusable_for_signature(preflight.input_signature):
        return None
    session = load_metadata_inspect_session(project_root=project_root)
    if has_uninspectable_source_issues(project_root=session.project_root, issues=session.issues):
        return None

    result = DriftGateResult(cache_hit=True)
    restored_result = _filter_restored_inspector_issues(
        state=preflight.state,
        session=session,
    )
    if restored_result.stale_count:
        return None

    for issue in restored_result.issues:
        result.approved_count += 1
        result.inspector_issues.append(issue)
    result.reused_decision_count = len(preflight.state.decisions)
    return session, result


def _try_load_approved_metadata_resume(
    project_root: Path,
    preflight: CachedDriftPreflight,
) -> tuple[InspectLoadResult, DriftGateResult] | None:
    """Resume approved Drift Gate items before running full drift again.

    Approved ``approved_for_inspector`` decisions are durable user work. When
    any of those approved blocks still needs metadata, Inspector should open
    directly on the remaining metadata queue instead of recomputing verify and
    showing Drift Gate again.

    Args:
        project_root: Project root directory.
        preflight: Loaded drift preflight state.

    Returns:
        Metadata-only session and DriftGateResult when there is unfinished
        approved metadata work, otherwise None.
    """
    if not preflight.state.has_approved_inspector_work():
        return None

    session = load_metadata_inspect_session(project_root=project_root)

    result = DriftGateResult(cache_hit=True)
    restored_result = _filter_restored_inspector_issues(
        state=preflight.state,
        session=session,
    )
    if not restored_result.issues:
        return None

    if restored_result.stale_count:
        session.pre_inspection_context_lines = [
            *session.pre_inspection_context_lines,
            (
                "Metadata queue: ignored "
                f"{restored_result.stale_count} stale approved Drift Gate references while resuming Inspector."
            ),
        ]

    for issue in restored_result.issues:
        result.approved_count += 1
        result.inspector_issues.append(issue)
    result.reused_decision_count = len(preflight.state.decisions)
    return session, result


def _filter_restored_inspector_issues(
    state: DriftState,
    session: InspectLoadResult,
) -> RestoredIssueFilterResult:
    """Return restored inspector issues that still need user metadata.

    Args:
        state: Persisted Drift Gate state.
        session: Current metadata-only inspector session.

    Returns:
        Filter result containing valid metadata issues and the number of stale
        restored approvals discarded from the resume queue.
    """
    current_blocks = session.blueprint_data.get("blocks", [])
    if not isinstance(current_blocks, list):
        current_blocks = []

    current_blocks_by_key = {
        key: block
        for block in current_blocks
        if isinstance(block, dict)
        for key in [_block_key(block)]
        if key is not None
    }

    restored_issues: list[InspectIssue] = []
    for issue in state.restored_inspector_issues():
        key = _block_key(issue.block)
        if key is None:
            restored_issues.append(issue)
            continue

        current_block = current_blocks_by_key.get(key)
        if current_block is None:
            restored_issues.append(issue)
            continue

        if _block_has_required_metadata(current_block):
            continue

        restored_issues.append(
            InspectIssue(
                issue_type=ISSUE_DRAFT,
                block=current_block,
                add_on_accept=False,
                context_lines=list(issue.context_lines),
            )
        )

    inspectable_issues, stale_issues = split_issues_by_source_availability(
        project_root=session.project_root,
        issues=restored_issues,
    )
    return RestoredIssueFilterResult(
        issues=sort_inspect_issues_hierarchically(inspectable_issues),
        stale_count=len(stale_issues),
    )


def _block_key(block: dict) -> tuple[str, str, str] | None:
    """Return the path, symbol, kind key for a blueprint block.

    Args:
        block: Blueprint block data.

    Returns:
        Stable code key, or None when unavailable.
    """
    code_data = block.get("code")
    if not isinstance(code_data, dict):
        return None
    path = _clean_string(code_data.get("path"))
    symbol = _clean_string(code_data.get("symbol"))
    kind = _clean_string(code_data.get("kind"))
    if path is None or symbol is None or kind is None:
        return None
    return path, symbol, kind


def _block_has_required_metadata(block: dict) -> bool:
    """Return whether a block has all required human metadata.

    Args:
        block: Blueprint block data.

    Returns:
        True when Inspector does not need to show the block again.
    """
    for field_name in REQUIRED_HUMAN_FIELDS:
        if _clean_string(block.get(field_name)) is None:
            return False
    return True


def _clean_string(value: object) -> str | None:
    """Return a stripped string or None for blank values.

    Args:
        value: Raw value.

    Returns:
        Clean string or None.
    """
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


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
