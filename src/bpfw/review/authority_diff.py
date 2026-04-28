"""Authority diff checks for review/apply flows."""

from __future__ import annotations

from dataclasses import dataclass

from bpfw.authority.resources import AuthorityResourceRegistry
from bpfw.review.diff import FileChange


@dataclass(slots=True)
class AuthorityDiffFinding:
    """Represents an authority resource modified in a diff."""

    file_path: str
    resource_id: str
    severity: str
    message: str


class AuthorityDiffChecker:
    """Detects protected authority resources inside file changes."""

    def __init__(self, registry: AuthorityResourceRegistry | None = None) -> None:
        self._registry = registry or AuthorityResourceRegistry()

    def check(self, changes: list[FileChange]) -> list[AuthorityDiffFinding]:
        """Return authority findings for a list of file changes."""

        findings: list[AuthorityDiffFinding] = []
        for file_change in changes:
            resource = self._registry.resolve_by_path(file_change.path)
            if resource is None:
                continue
            findings.append(
                AuthorityDiffFinding(
                    file_path=file_change.path,
                    resource_id=resource.resource_id,
                    severity="block",
                    message="Direct authority edits are not allowed.",
                )
            )
        return findings
