"""Analyzer protocol for extensible BPFW verification."""
from __future__ import annotations
from typing import Protocol
from bpfw.core.verification.context import VerificationContext
from bpfw.reports.finding import Finding

class Analyzer(Protocol):
    name: str
    def analyze(self, context: VerificationContext) -> list[Finding]: ...
