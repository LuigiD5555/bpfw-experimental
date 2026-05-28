"""PURPOSE apply-plan model for the BPFW diff decision manager
DOMAIN  optional integrations
"""

from dataclasses import dataclass, field
from pathlib import Path

from bpfw.core.blueprint_engine.models import BlueprintChangeRequest
from bpfw.integrations.diff.models import SourceChangeRequest


@dataclass(frozen=True)
class FileStamp:
    """PURPOSE snapshot of one file at the moment an action was added
    DOMAIN  optional integrations
    """

    path: Path
    exists: bool
    modified_ns: int | None = None
    size: int | None = None


@dataclass(frozen=True)
class PlannedAuthorityAction:
    """PURPOSE authority action accepted by the user but not yet applied
    DOMAIN  optional integrations
    """

    diff_item_id: str
    label: str
    request: BlueprintChangeRequest
    file_stamps: tuple[FileStamp, ...] = ()


@dataclass(frozen=True)
class PlannedSourceAction:
    """PURPOSE source action accepted by the user but not yet applied
    DOMAIN  optional integrations
    """

    diff_item_id: str
    label: str
    request: SourceChangeRequest
    file_stamps: tuple[FileStamp, ...] = ()


@dataclass(frozen=True)
class PlanConflict:
    """PURPOSE store information about a conflict between planned actions
    DOMAIN  optional integrations
    """

    message: str
    conflicting_item_ids: tuple[str, ...]


@dataclass
class DiffApplyPlan:
    """PURPOSE store accepted diff decisions before applying them
    DOMAIN  optional integrations
    """

    authority_actions: list[PlannedAuthorityAction] = field(default_factory=list)
    source_actions: list[PlannedSourceAction] = field(default_factory=list)

    def is_empty(self) -> bool:
        """PURPOSE check whether the plan has no pending actions
        DOMAIN  optional integrations
        """
        return not self.authority_actions and not self.source_actions

    def action_count(self) -> int:
        """PURPOSE get the total action count
        DOMAIN  optional integrations
        """
        return len(self.authority_actions) + len(self.source_actions)

    def planned_item_ids(self) -> set[str]:
        """PURPOSE get diff item identifiers already represented in the plan
        DOMAIN  optional integrations
        """
        return {
            action.diff_item_id
            for action in [*self.authority_actions, *self.source_actions]
        }

    def add_authority_action(self, action: PlannedAuthorityAction) -> list[PlanConflict]:
        """PURPOSE add one authority action and return conflicts
        DOMAIN  optional integrations
        """
        self.authority_actions.append(action)
        return self.detect_conflicts()

    def add_source_action(self, action: PlannedSourceAction) -> list[PlanConflict]:
        """PURPOSE add one source action and return conflicts
        DOMAIN  optional integrations
        """
        self.source_actions.append(action)
        return self.detect_conflicts()

    def remove_actions_for_item(self, diff_item_id: str) -> None:
        """PURPOSE remove all actions produced by a diff item
        DOMAIN  optional integrations
        """
        self.authority_actions = [
            action for action in self.authority_actions if action.diff_item_id != diff_item_id
        ]
        self.source_actions = [
            action for action in self.source_actions if action.diff_item_id != diff_item_id
        ]

    def clear(self) -> None:
        """PURPOSE remove every planned action
        DOMAIN  optional integrations
        """
        self.authority_actions.clear()
        self.source_actions.clear()

    def authority_requests(self) -> list[BlueprintChangeRequest]:
        """PURPOSE get Blueprint Engine requests in plan order
        DOMAIN  optional integrations
        """
        return [action.request for action in self.authority_actions]

    def detect_conflicts(self) -> list[PlanConflict]:
        """PURPOSE find simple intra-plan conflicts
        DOMAIN  optional integrations
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
        """PURPOSE get labels for actions whose source files changed
        DOMAIN  optional integrations
        """
        stale: list[str] = []
        for action in [*self.authority_actions, *self.source_actions]:
            for stamp in action.file_stamps:
                if _collect_file_stamp(project_root, stamp.path) != stamp:
                    stale.append(action.label)
                    break
        return stale


def collect_file_stamps(project_root: Path, paths: list[Path]) -> tuple[FileStamp, ...]:
    """PURPOSE collect file stamps for paths relevant to one planned action
    DOMAIN  optional integrations
    """
    unique_paths = sorted(set(paths))
    return tuple(_collect_file_stamp(project_root, path) for path in unique_paths)


def _collect_file_stamp(project_root: Path, path: Path) -> FileStamp:
    """PURPOSE collect one file stamp
    DOMAIN  optional integrations
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
    """PURPOSE get a stable target label for one authority request
    DOMAIN  optional integrations
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
