"""Deterministic JSON storage helpers for change workflow state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ChangeStoreError(RuntimeError):
    """Raised when change store operations fail."""


def ensure_directory(path: Path) -> None:
    """Ensure directory exists for state persistence."""

    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    """Read JSON object from disk."""

    if not path.exists():
        raise ChangeStoreError(f"State file does not exist: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ChangeStoreError(f"Invalid JSON in state file: {path}") from error

    if not isinstance(payload, dict):
        raise ChangeStoreError(f"State file must contain a JSON object: {path}")

    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist JSON object in deterministic encoding."""

    ensure_directory(path.parent)
    path.write_text(f"{json.dumps(payload, indent=2, ensure_ascii=True)}\n", encoding="utf-8")
