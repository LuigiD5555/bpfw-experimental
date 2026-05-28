"""PURPOSE structured result of applying an authority patch plan
DOMAIN  blueprint file changes
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AuthorityPatchResult:
    """PURPOSE structured result returned by AuthorityPatchEngine.apply
    DOMAIN  blueprint file changes
    """

    success: bool = False
    applied_operations: list[str] = field(default_factory=list)
    skipped_operations: list[str] = field(default_factory=list)
    modified_files: list[Path] = field(default_factory=list)
    manifest_updated: bool = False
    rolled_back: bool = False
    messages: list[str] = field(default_factory=list)
    error_message: str | None = None

    def add_applied(self, kind_label: str) -> None:
        """PURPOSE record a successfully applied operation
        DOMAIN  blueprint file changes
        """
        self.applied_operations.append(kind_label)

    def add_skipped(self, kind_label: str, reason: str) -> None:
        """PURPOSE record a skipped operation
        DOMAIN  blueprint file changes
        """
        self.skipped_operations.append(kind_label)
        self.messages.append(f"Skipped {kind_label}: {reason}")

    def add_modified(self, path: Path) -> None:
        """PURPOSE record a file that was written
        DOMAIN  blueprint file changes
        """
        self.modified_files.append(path)