"""Apply-plan model for the BPFW diff decision manager."""

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.core.blueprint_engine.models import BlueprintChangeRequest
from bpfw.integrations.diff.models import SourceChangeRequest


@dataclass(frozen=True)
class FileStamp:
    """Snapshot of one file at the moment an action was added.

    Attributes:
        path: Project-relative path.
        exists: Whether the file existed.
        modified_ns: Last modified timestamp in nanoseconds when available.
        size: File size in bytes when available.
    """

    path: Path
    exists: bool
    modified_ns: int | None = None
    size: int | None = None


@dataclass(frozen=True)
class PlannedAuthorityAction:
    """Authority action accepted by the user but not yet applied.

    Attributes:
        diff_item_id: Identifier of the diff item that produced the action.
        label: Human-readable action label.
        request: Blueprint Engine request to apply later.
        file_stamps: File stamps used to detect stale plans.
    """

    diff_item_id: str
    label: str
    request: BlueprintChangeRequest
    file_stamps: tuple[FileStamp, ...] = ()


@dataclass(frozen=True)
class PlannedSourceAction:
    """Source action accepted by the user but not yet applied.

    Attributes:
        diff_item_id: Identifier of the diff item that produced the action.
        label: Human-readable action label.
        request: Source action request.
        file_stamps: File stamps used to detect stale plans.
    """

    diff_item_id: str
    label: str
    request: SourceChangeRequest
    file_stamps: tuple[FileStamp, ...] = ()


@dataclass(frozen=True)
class PlanConflict:
    """Represent a conflict between planned actions.

    Attributes:
        message: Human-readable conflict description.
        conflicting_item_ids: Diff item identifiers involved in the conflict.
    """

    message: str
    conflicting_item_ids: tuple[str, ...]


@dataclass
class DiffApplyPlan:
    """Store accepted diff decisions before applying them.

    The plan is intentionally separate from the review screens. Diff owns the
    decisions, but BlueprintEngine still owns mechanical writes under ``bpfw/``.
    """

    authority_actions: list[PlannedAuthorityAction] = field(default_factory=list)
    source_actions: list[PlannedSourceAction] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return whether the plan has no pending actions.

        Returns:
            True when no authority or source actions are present.
        """
        return not self.authority_actions and not self.source_actions

    def action_count(self) -> int:
        """Return the total action count.

        Returns:
            Number of planned actions.
        """
        return len(self.authority_actions) + len(self.source_actions)

    def planned_item_ids(self) -> set[str]:
        """Return diff item identifiers already represented in the plan.

        Returns:
            Set of planned diff item identifiers.
        """
        return {
            action.diff_item_id
            for action in [*self.authority_actions, *self.source_actions]
        }

    def add_authority_action(self, action: PlannedAuthorityAction) -> list[PlanConflict]:
        """Add one authority action and return conflicts.

        Args:
            action: Authority action to add.

        Returns:
            List of conflicts after adding the action.
        """
        self.authority_actions.append(action)
        return self.detect_conflicts()

    def add_source_action(self, action: PlannedSourceAction) -> list[PlanConflict]:
        """Add one source action and return conflicts.

        Args:
            action: Source action to add.

        Returns:
            List of conflicts after adding the action.
        """
        self.source_actions.append(action)
        return self.detect_conflicts()

    def remove_actions_for_item(self, diff_item_id: str) -> None:
        """Remove all actions produced by a diff item.

        Args:
            diff_item_id: Item identifier whose actions should be removed.
        """
        self.authority_actions = [
            action for action in self.authority_actions if action.diff_item_id != diff_item_id
        ]
        self.source_actions = [
            action for action in self.source_actions if action.diff_item_id != diff_item_id
        ]

    def clear(self) -> None:
        """Remove every planned action."""
        self.authority_actions.clear()
        self.source_actions.clear()

    def authority_requests(self) -> list[BlueprintChangeRequest]:
        """Return Blueprint Engine requests in plan order.

        Returns:
            Authority change requests.
        """
        return [action.request for action in self.authority_actions]

    def detect_conflicts(self) -> list[PlanConflict]:
        """Detect simple intra-plan conflicts.

        Returns:
            Conflicts found in the current plan.
        """
        conflicts: list[PlanConflict] = []
        targets: dict[str, list[str]] = {}
        for action in self.authority_actions:
            target = _authority_action_target(action.request)
            if target is None:
                continue
            targets.setdefault(target, []).append(action.diff_item_id)
        for action in self.source_actions:
            target = action.request.target.display_label()
            targets.setdefault(target, []).append(action.diff_item_id)

        for target, item_ids in targets.items():
            unique_ids = tuple(dict.fromkeys(item_ids))
            if len(unique_ids) > 1:
                conflicts.append(
                    PlanConflict(
                        message=f"Multiple planned actions target {target}.",
                        conflicting_item_ids=unique_ids,
                    )
                )
        return conflicts

    def stale_actions(self, project_root: Path) -> list[str]:
        """Return labels for actions whose source files changed.

        Args:
            project_root: Project root directory.

        Returns:
            Labels for stale planned actions.
        """
        stale: list[str] = []
        for action in [*self.authority_actions, *self.source_actions]:
            for stamp in action.file_stamps:
                if _collect_file_stamp(project_root, stamp.path) != stamp:
                    stale.append(action.label)
                    break
        return stale


def collect_file_stamps(project_root: Path, paths: list[Path]) -> tuple[FileStamp, ...]:
    """Collect file stamps for paths relevant to one planned action.

    Args:
        project_root: Project root directory.
        paths: Project-relative paths to snapshot.

    Returns:
        Tuple of file stamps.
    """
    unique_paths = sorted(set(paths))
    return tuple(_collect_file_stamp(project_root, path) for path in unique_paths)


def _collect_file_stamp(project_root: Path, path: Path) -> FileStamp:
    """Collect one file stamp.

    Args:
        project_root: Project root directory.
        path: Project-relative path.

    Returns:
        File stamp for the path.
    """
    absolute_path = project_root / path
    if not absolute_path.exists():
        return FileStamp(path=path, exists=False)
    stat_result = absolute_path.stat()
    return FileStamp(
        path=path,
        exists=True,
        modified_ns=stat_result.st_mtime_ns,
        size=stat_result.st_size,
    )


def _authority_action_target(request: BlueprintChangeRequest) -> str | None:
    """Return a stable target label for one authority request.

    Args:
        request: Blueprint Engine request.

    Returns:
        Target label, or None when not applicable.
    """
    payload = request.payload
    block_id = payload.get("block_id")
    if isinstance(block_id, str) and block_id:
        return block_id
    block_data = payload.get("block_data")
    if isinstance(block_data, dict):
        created_id = block_data.get("id")
        if isinstance(created_id, str) and created_id:
            return created_id
    rule_data = payload.get("rule_data")
    if isinstance(rule_data, dict):
        path_value = rule_data.get("path")
        symbol_value = rule_data.get("symbol")
        if path_value and symbol_value:
            return f"{path_value}::{symbol_value}"
    return None
