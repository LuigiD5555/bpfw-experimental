"""Inspector controller for navigation and command effects."""

from dataclasses import dataclass
from typing import List

from bpfw.integrations.inspector.suggestions.domain.engine import resolve_domain_origin_key
from bpfw.integrations.inspector.suggestions.domain.learning import record_domain_for_origin, record_domain_value
from bpfw.integrations.inspector.suggestions.purpose.learning import record_purpose_phrase
from bpfw.integrations.inspector.suggestions.purpose.models import PurposeSuggestion
from bpfw.core.errors import BlueprintLockedError
from bpfw.integrations.inspector.base import (
    InspectIssue,
    InspectLoadResult,
    save_blueprint,
    sync_block_code_location,
)
from bpfw.integrations.inspector.commands import (
    CUSTOM_DOMAIN_KEY,
    CUSTOM_PURPOSE_KEY,
    DOMAIN_SUGGESTION_KEYS,
    InspectorAction,
    PURPOSE_SUGGESTION_KEYS,
    run_interface_edit_submode,
)
from bpfw.integrations.inspector.input_adapter import InspectorInputReader
from bpfw.integrations.inspector.state import InspectorViewState
from bpfw.integrations.inspector.validation import validate_required_fields
from bpfw.integrations.inspector.view_modes.base import InspectorViewMode
from bpfw.integrations.shared.cli_runtime import quit_command_label


@dataclass
class InspectorControllerResult:
    """Store the outcome produced by an inspector controller action."""

    exit_code: int | None = None
    should_refresh_existing_purposes: bool = False
    should_refresh_duplicate_profiles: bool = False


class InspectorController:
    """Coordinate inspector actions without mixing rendering details."""

    def __init__(
        self,
        session: InspectLoadResult,
        input_reader: InspectorInputReader,
        print_func,
    ) -> None:
        """Initialize the inspector controller.

        Args:
            session: Loaded inspector session data.
            input_reader: Interactive input reader used by submodes.
            print_func: Function used for user-visible output.
        """

        self._session = session
        self._input_reader = input_reader
        self._print_func = print_func

    def handle_action(
        self,
        action: str,
        state: InspectorViewState,
        issue: InspectIssue,
        purpose_suggestions: List[PurposeSuggestion],
        domain_suggestions: List[str],
        view_mode: InspectorViewMode,
    ) -> InspectorControllerResult:
        """Apply one inspector action and return the controller outcome."""

        if action == InspectorAction.SAVE_NEXT:
            return self._handle_save_next(
                state=state,
                issue=issue,
                purpose_suggestions=purpose_suggestions,
                domain_suggestions=domain_suggestions,
            )

        if action == InspectorAction.SAVE_STAY:
            return self._handle_save_stay(issue=issue)

        if action == InspectorAction.BACK:
            state.move_back()
            return InspectorControllerResult()

        if action == InspectorAction.QUIT:
            self._print_func("Inspector stopped.")
            state.stop()
            return InspectorControllerResult(exit_code=0)

        if action == InspectorAction.TOGGLE_FULL_VIEW:
            state.toggle_mode(current_view_mode=view_mode)
            return InspectorControllerResult()

        if action == InspectorAction.HELP:
            return self._handle_help(view_mode=view_mode)

        if action == InspectorAction.UNKNOWN:
            for line in render_unknown_command_notification():
                self._print_func(line)
            return InspectorControllerResult()

        if action == InspectorAction.INTERFACE_EDIT:
            run_interface_edit_submode(
                block=issue.block,
                input_func=self._input_reader.read,
                print_func=self._print_func,
            )
            return InspectorControllerResult()

        return InspectorControllerResult()

    def _handle_save_stay(self, issue: InspectIssue) -> InspectorControllerResult:
        """Persist the current issue without advancing the Inspector cursor."""

        try:
            persisted = save_issue(session=self._session, issue=issue)
        except BlueprintLockedError as error:
            self._print_func(str(error))
            return InspectorControllerResult(exit_code=1)

        if not persisted:
            self._print_func("Blueprint path is unavailable.")
            return InspectorControllerResult(exit_code=1)

        self._print_func("Saved.")
        return InspectorControllerResult(should_refresh_duplicate_profiles=True)

    def _handle_save_next(
        self,
        state: InspectorViewState,
        issue: InspectIssue,
        purpose_suggestions: List[PurposeSuggestion],
        domain_suggestions: List[str],
    ) -> InspectorControllerResult:
        """Validate, persist, and advance after a save action."""

        missing_fields = validate_required_fields(issue.block)
        if missing_fields:
            for line in render_missing_fields_notification(missing_fields):
                self._print_func(line)
            return InspectorControllerResult()

        record_learning_feedback(
            issue=issue,
            purpose_suggestions=purpose_suggestions,
            domain_suggestions=domain_suggestions,
        )
        try:
            persisted = save_issue(session=self._session, issue=issue)
        except BlueprintLockedError as error:
            self._print_func(str(error))
            return InspectorControllerResult(exit_code=1)

        if not persisted:
            self._print_func("Blueprint path is unavailable.")
            return InspectorControllerResult(exit_code=1)

        self._print_func("Saved.")
        state.advance()
        return InspectorControllerResult(should_refresh_existing_purposes=True)

    def _handle_help(self, view_mode: InspectorViewMode) -> InspectorControllerResult:
        """Render help and wait for the user to return to the inspector."""

        for line in render_help_block(view_mode=view_mode):
            self._print_func(line)
        try:
            self._input_reader.read("Press any key then Enter to continue...")
        except EOFError:
            self._print_func("Interactive inspector input unavailable.")
            self._print_func("")
            self._print_func("Next:")
            self._print_func("  Run bpfw inspector in an interactive terminal.")
            return InspectorControllerResult(exit_code=1)
        return InspectorControllerResult()


def save_issue(session: InspectLoadResult, issue: InspectIssue) -> bool:
    """Save one issue and persist the blueprint."""

    if session.blueprint_path is None:
        return False

    if issue.add_on_accept:
        blocks = session.blueprint_data.get("blocks", [])
        if not isinstance(blocks, list):
            return False
        if issue.block not in blocks:
            blocks.append(issue.block)
        session.blueprint_data["blocks"] = blocks
        issue.add_on_accept = False

    sync_block_code_location(project_root=session.project_root, block=issue.block)

    save_blueprint(
        blueprint_path=session.blueprint_path,
        blueprint_data=session.blueprint_data,
        authority_document=session.authority_document,
    )
    from bpfw.integrations.inspector.work_cache import invalidate_inspector_work_cache

    invalidate_inspector_work_cache(session.project_root)
    return True


def record_learning_feedback(
    issue: InspectIssue,
    purpose_suggestions: List[PurposeSuggestion],
    domain_suggestions: List[str],
) -> None:
    """Record accepted purpose and domain values for incremental learning."""

    purpose_value = issue.block.get("purpose")
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
        record_domain_for_origin(resolve_domain_origin_key(issue.block), domain_value)


def render_missing_fields_notification(missing_fields: list[str]) -> list[str]:
    """Render notification for missing required fields."""

    from bpfw.integrations.shared.visual_notifications import render_notification_block

    lines = [f"Missing required fields: {', '.join(missing_fields)}"]
    return render_notification_block(
        title="Cannot save",
        lines=lines,
        width=compute_notification_width(),
    )


def render_unknown_command_notification() -> list[str]:
    """Render notification for an unknown inspector command."""

    from bpfw.integrations.shared.visual_notifications import render_notification_block

    lines = [
        "Use p1-p5 for purpose suggestions, p for custom purpose, d1-d5 for domain suggestions, d for custom domain, s1-s4 for lifecycle, n, i, o(notes), Enter, b, a, h, q, or ctrl+c."
    ]
    return render_notification_block(
        title="Unknown command",
        lines=lines,
        width=compute_notification_width(),
    )


def render_help_block(view_mode: InspectorViewMode) -> list[str]:
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
        "  Lifecycle",
        "  ─────────",
        "  lifecycle    Current authority stage for this block.",
        "               active        Trusted and used now.",
        "                             Two active blocks should not share",
        "                             the same purpose.",
        "               experimental  Being tested or not fully accepted yet.",
        "               legacy        Old code kept for existing behavior.",
        "               deprecated    Should be replaced or removed later.",
        "",
        "  Purpose suggestions",
        "  ───────────────────",
        "  [p1] Existing purpose from blueprint matches this block.",
        "  [p2] Learned purpose previously accepted by the user.",
        "  [p3] Symbol-based purpose from class/function name.",
        "  [p4] Docstring first sentence or supported docstring pattern.",
        "  [p5] Blended evidence from history, symbol, and docstring.",
        "  [p] write custom purpose",
        "",
        "  Domain suggestions",
        "  ──────────────────",
        "  [d1] Existing domain best matched by block behavior.",
        "  [d2] Second existing domain matched by block behavior.",
        "  [d3] Third existing domain matched by block behavior.",
        "  [d4] Symbol-based domain from the class/function name.",
        "  [d5] Previous domain used for the same code origin.",
        f"  [{CUSTOM_DOMAIN_KEY}] write custom domain",
        "",
        "  Lifecycle shortcuts",
        "  ───────────────────",
        "  [s1] active",
        "  [s2] experimental",
        "  [s3] legacy",
        "  [s4] deprecated",
        "",
        "  View mode",
        "  ─────────",
        "  Compact view shows the essential panels only.",
        "  Full view shows hierarchy, interface, and observations panels.",
        "  Use bpfw inspector --all to start in full view.",
    ]
    if view_mode.should_render_extended_panels():
        help_lines.extend([
            "  [f]        Switch back to compact view",
            "",
            "  Interface modes",
            "  ───────────────",
            "  Full view shows interface inputs and output details.",
            "",
            "  Why '-' appears",
            "  ───────────────",
            "  '-' means that source did not have enough evidence.",
            "",
            "  Editing",
            "  ───────",
            "  [i]        Edit interface",
            "  [o]        Edit notes",
        ])
    else:
        help_lines.append("  [a]        Show all panels")
    help_lines.extend(
        [
            "",
            "  Navigation",
            "  ──────────",
            "  [Enter]    Save and continue",
            "  [b]        Back",
            "  [h]        Toggle help",
            "  [q]        Quit. Ctrl+c also quits.",
            "",
        ]
    )
    return render_notification_block(
        title="Inspector help",
        lines=help_lines,
        width=compute_help_width(),
    )


def compute_help_width() -> int:
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


def compute_notification_width() -> int:
    """Compute standard inner width for standalone notification panels."""

    import shutil

    terminal_width = shutil.get_terminal_size(fallback=(100, 30)).columns
    total_width = min(max(72, 72), terminal_width)
    return max(20, total_width - 2)
