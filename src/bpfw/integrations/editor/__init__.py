"""BPFW Editor — one active SQLite authority and one CLI explorer.

YAML remains a supported import format via `bpfw migrate`, not an alternative
editor or writer. The Editor itself has a single current implementation.
"""
from __future__ import annotations

import sys
from pathlib import Path

from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.result import OptionalIntegrationResult


def can_use_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def run_interactive_editor(project_root: Path) -> int:
    from bpfw.core.authority.sqlite.migration import active_backend
    root=Path(project_root).resolve()
    if active_backend(root) != 'sqlite':
        print('Editor requires SQLite authority. Convert using bpfw migrate --to sqlite --plan, '
              'then bpfw migrate --to sqlite --apply. YAML remains import-only.')
        return 2
    if not can_use_interactive_terminal():
        print('Editor needs a terminal for interactive navigation; use bpfw editor --json for scripting.')
        return 1
    from bpfw.core.authority.sqlite.commands import run_sqlite_cli
    return run_sqlite_cli('editor',None,['--interactive'],root,False)


def run_editor(project_root: Path) -> int:
    return run_interactive_editor(project_root)


class EditorIntegration(OptionalIntegration):
    """Adapter from the integration registry to the sole Editor application."""

    name='editor'

    def is_available(self) -> bool:
        return True

    def run(self, project_root: Path, command_arguments: dict[str,str] | None = None) -> OptionalIntegrationResult:
        return OptionalIntegrationResult(message='', exit_code=run_editor(project_root))


__all__=['EditorIntegration','can_use_interactive_terminal','run_editor','run_interactive_editor']
