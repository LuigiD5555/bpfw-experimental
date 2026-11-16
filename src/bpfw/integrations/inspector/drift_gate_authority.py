"""Authority request and text-mutation helpers used by Drift Gate.

This module deliberately contains no terminal interaction and no persistence.
It builds explicit Blueprint Engine requests and performs deterministic text
transformations used by the legacy fast-path writer. The runner remains the
orchestrator that decides when a write is allowed and records the outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bpfw.core.atomic_io import atomic_write_text
from bpfw.core.authority.patch.transaction import TransactionBackup
from bpfw.core.blueprint_engine import (
    BlueprintChangeKind,
    BlueprintChangeRequest,
    BlueprintChangeSource,
)
from bpfw.integrations.diff.models import BlueprintTarget, CodeTarget


@dataclass(frozen=True, slots=True)
class AuthorityWriteResult:
    """Outcome of one narrow authority-file write."""

    success: bool
    error: str | None = None
    recovery_preserved: bool = False


class DriftAuthorityWriter:
    """Crash-safe narrow writer used by Drift Gate fast paths.

    It shares the same recovery directory and clean-start contract as the
    Blueprint Engine transaction layer, so a fast patch cannot overwrite
    recovery data from an earlier failed authority transaction.
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)

    def write_text(self, relative_path: Path, text: str) -> AuthorityWriteResult:
        relative_path = Path(relative_path)
        backup = TransactionBackup(self.project_root)
        try:
            backup.ensure_clean_start()
            backup.backup(relative_path)
        except (OSError, RuntimeError) as error:
            return AuthorityWriteResult(False, str(error), backup.has_pending_recovery())

        target = self.project_root / relative_path
        try:
            atomic_write_text(target, text)
        except BaseException as write_error:
            try:
                backup.rollback()
            except BaseException as rollback_error:
                return AuthorityWriteResult(
                    False,
                    f"write failed: {write_error}; rollback failed: {rollback_error}",
                    True,
                )
            backup.commit()
            return AuthorityWriteResult(False, str(write_error), False)

        backup.commit()
        return AuthorityWriteResult(True)


class DriftAuthorityActions:
    """Build authority changes and deterministic shard text mutations."""

    @staticmethod
    def attach_code_request(code: CodeTarget, covered_by: str) -> BlueprintChangeRequest:
        return BlueprintChangeRequest(
            kind=BlueprintChangeKind.ADD_COVERED_CODE,
            source=BlueprintChangeSource.INSPECTOR,
            human_confirmed=True,
            payload={
                "rule_data": {
                    "path": code.path,
                    "symbol": code.symbol,
                    "kind": code.kind,
                    "covered_by": covered_by,
                    "reason": "covered implementation detail",
                }
            },
            reason="Drift Gate decision: attach code to existing responsibility.",
        )

    @staticmethod
    def ignore_code_request(code: CodeTarget, reason: str) -> BlueprintChangeRequest:
        return BlueprintChangeRequest(
            kind=BlueprintChangeKind.ADD_IGNORE_RULE,
            source=BlueprintChangeSource.INSPECTOR,
            human_confirmed=True,
            payload={
                "rule_data": {
                    "path": code.path,
                    "symbol": code.symbol,
                    "kind": code.kind,
                    "reason": reason,
                }
            },
            reason="Drift Gate decision: ignore undeclared code.",
        )

    @staticmethod
    def mark_status_request(target: BlueprintTarget, status: str) -> BlueprintChangeRequest:
        if target.source_shard_path is None:
            raise ValueError("target source shard is required")
        return BlueprintChangeRequest(
            kind=BlueprintChangeKind.UPDATE_METADATA,
            source=BlueprintChangeSource.INSPECTOR,
            human_confirmed=True,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
                "metadata_changes": {"status": status, "lifecycle": status},
            },
            reason=f"Drift Gate decision: mark block as {status}.",
        )

    @staticmethod
    def delete_block_request(target: BlueprintTarget) -> BlueprintChangeRequest:
        if target.source_shard_path is None:
            raise ValueError("target source shard is required")
        return BlueprintChangeRequest(
            kind=BlueprintChangeKind.DELETE_BLOCK,
            source=BlueprintChangeSource.INSPECTOR,
            human_confirmed=True,
            payload={
                "block_id": target.block_id,
                "source_shard_path": target.source_shard_path,
            },
            reason="Drift Gate decision: remove old declaration.",
        )

    @staticmethod
    def remove_block_from_shard_text(original_text: str, block_id: str) -> str | None:
        lines = original_text.splitlines(keepends=True)
        block_start = DriftAuthorityActions.find_yaml_block_start(lines, block_id)
        if block_start is None:
            return None
        block_end = DriftAuthorityActions.find_yaml_block_end(lines, block_start)
        del lines[block_start:block_end]
        return "".join(lines)

    @staticmethod
    def replace_code_reference_in_shard_text(
        original_text: str,
        block_id: str,
        new_path: str,
        new_symbol: str,
        new_kind: str,
        new_name: str,
    ) -> str | None:
        lines = original_text.splitlines(keepends=True)
        block_start = DriftAuthorityActions.find_yaml_block_start(lines, block_id)
        if block_start is None:
            return None
        block_end = DriftAuthorityActions.find_yaml_block_end(lines, block_start)
        DriftAuthorityActions.replace_top_level_yaml_field(
            lines, block_start, block_end, "name", new_name
        )
        code_start = DriftAuthorityActions.find_yaml_section_start(
            lines, block_start, block_end, "code"
        )
        if code_start is None:
            insert_at = min(block_start + 1, len(lines))
            lines.insert(insert_at, "  code:\n")
            block_end += 1
            code_start = insert_at
        for field_name, field_value in (
            ("path", new_path),
            ("symbol", new_symbol),
            ("kind", new_kind),
        ):
            DriftAuthorityActions.replace_nested_yaml_field(
                lines, code_start, block_end, field_name, field_value
            )
        return "".join(lines)

    @staticmethod
    def find_yaml_block_start(lines: list[str], block_id: str) -> int | None:
        escaped_block_id = re.escape(block_id)
        pattern = re.compile(rf"^\s*-\s+id:\s*(['\"]?){escaped_block_id}\1\s*$")
        for index, line in enumerate(lines):
            if pattern.match(line.rstrip("\n")):
                return index
        return None

    @staticmethod
    def find_yaml_block_end(lines: list[str], block_start: int) -> int:
        for index in range(block_start + 1, len(lines)):
            if re.match(r"^\s*-\s+id:\s*", lines[index]):
                return index
        return len(lines)

    @staticmethod
    def find_yaml_section_start(
        lines: list[str], block_start: int, block_end: int, section_name: str
    ) -> int | None:
        pattern = re.compile(rf"^  {re.escape(section_name)}:\s*$")
        for index in range(block_start + 1, block_end):
            if pattern.match(lines[index].rstrip("\n")):
                return index
        return None

    @staticmethod
    def replace_top_level_yaml_field(
        lines: list[str],
        block_start: int,
        block_end: int,
        field_name: str,
        field_value: str,
    ) -> None:
        pattern = re.compile(rf"^  {re.escape(field_name)}:")
        replacement = f"  {field_name}: {DriftAuthorityActions.format_yaml_scalar(field_value)}\n"
        for index in range(block_start + 1, block_end):
            if pattern.match(lines[index]):
                lines[index] = replacement
                return
        lines.insert(block_start + 1, replacement)

    @staticmethod
    def replace_nested_yaml_field(
        lines: list[str],
        section_start: int,
        block_end: int,
        field_name: str,
        field_value: str,
    ) -> None:
        pattern = re.compile(rf"^    {re.escape(field_name)}:")
        replacement = f"    {field_name}: {DriftAuthorityActions.format_yaml_scalar(field_value)}\n"
        insert_at = section_start + 1
        for index in range(section_start + 1, block_end):
            line = lines[index]
            if line.startswith("  ") and not line.startswith("    "):
                break
            insert_at = index + 1
            if pattern.match(line):
                lines[index] = replacement
                return
        lines.insert(insert_at, replacement)

    @staticmethod
    def format_yaml_scalar(value: str) -> str:
        text = str(value)
        lower_text = text.lower()
        unsafe = (
            not text
            or text.strip() != text
            or lower_text in {"null", "true", "false", "yes", "no", "on", "off"}
            or any(character in text for character in ":#[]{}&,*!|>'\"%@`")
        )
        if not unsafe:
            return text
        return "'" + text.replace("'", "''") + "'"
