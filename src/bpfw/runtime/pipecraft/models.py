"""Structured results returned by the PipeCraft JSON boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class PipeCraftRuntimeInfo:
    version: str
    platform: str
    path: Path
    sha256: str
    managed: bool = True

@dataclass(frozen=True)
class PipeCraftResponse:
    command: tuple[str, ...]
    returncode: int
    payload: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""

    @property
    def success(self) -> bool:
        if self.returncode != 0:
            return False
        payload_success = self.payload.get("success")
        if isinstance(payload_success, bool):
            return payload_success
        payload_valid = self.payload.get("valid")
        if isinstance(payload_valid, bool):
            return payload_valid
        return True
