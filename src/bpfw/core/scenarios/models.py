"""Failure scenario representation."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class Scenario:
    identifier: str
    when: dict[str, Any] = field(default_factory=dict)
    expect: dict[str, Any] = field(default_factory=dict)
    must_preserve: tuple[str, ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
