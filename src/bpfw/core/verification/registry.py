"""Analyzer registration without a monolithic verify function."""
from __future__ import annotations
from bpfw.core.verification.analyzer import Analyzer

class AnalyzerRegistry:
    def __init__(self) -> None:
        self._analyzers: list[Analyzer] = []
    def register(self, analyzer: Analyzer) -> None:
        self._analyzers.append(analyzer)
    def all(self) -> tuple[Analyzer, ...]:
        return tuple(self._analyzers)
