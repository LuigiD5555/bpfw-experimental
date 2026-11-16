"""System-level verification engine layered above legacy catalog checks."""
from __future__ import annotations
from bpfw.core.verification.analyzers import (
    DeclaredInvariantAnalyzer,
    FailoverCapacityAnalyzer,
    IntentCoverageAnalyzer,
    InteractionStateAnalyzer,
    NonIdempotentRetryAnalyzer,
    RetryAmplificationAnalyzer,
    ScalingBlindSpotAnalyzer,
)
from bpfw.core.verification.context import VerificationContext
from bpfw.core.verification.registry import AnalyzerRegistry
from bpfw.reports.finding import Finding

class SystemVerificationEngine:
    def __init__(self, registry: AnalyzerRegistry | None = None) -> None:
        if registry is None:
            registry = AnalyzerRegistry()
            for analyzer in (
                IntentCoverageAnalyzer(),
                DeclaredInvariantAnalyzer(),
                ScalingBlindSpotAnalyzer(),
                RetryAmplificationAnalyzer(),
                NonIdempotentRetryAnalyzer(),
                FailoverCapacityAnalyzer(),
                InteractionStateAnalyzer(),
            ):
                registry.register(analyzer)
        self.registry = registry

    def verify(self, context: VerificationContext) -> list[Finding]:
        findings: list[Finding] = []
        for analyzer in self.registry.all():
            findings.extend(analyzer.analyze(context))
        return findings
