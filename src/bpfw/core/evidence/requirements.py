"""Extract structured evidence requirements from invariants."""
from __future__ import annotations
from bpfw.core.catalog.domain.models import BlueprintDocument
from bpfw.core.evidence.models import EvidenceRequirement


def collect_evidence_requirements(document: BlueprintDocument) -> list[EvidenceRequirement]:
    requirements: list[EvidenceRequirement] = []
    for block in document.blocks:
        for invariant in block.invariants:
            for raw in invariant.evidence:
                if not isinstance(raw, dict):
                    continue
                kind = str(raw.get("type") or "").strip().lower()
                if kind == "command":
                    command = raw.get("command")
                    if isinstance(command, list) and command and all(isinstance(part, str) and part for part in command):
                        requirements.append(EvidenceRequirement(
                            invariant_id=invariant.identifier,
                            kind="command",
                            command=tuple(command),
                        ))
                elif kind == "scenario":
                    scenario = raw.get("scenario")
                    if isinstance(scenario, str) and scenario.strip():
                        requirements.append(EvidenceRequirement(
                            invariant_id=invariant.identifier,
                            kind="scenario",
                            scenario=scenario.strip(),
                        ))
    return requirements
