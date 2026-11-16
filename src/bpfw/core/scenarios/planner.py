"""Resolve scenarios declared in Blueprint v2."""
from __future__ import annotations
from bpfw.core.catalog.domain.models import BlueprintDocument
from bpfw.core.scenarios.models import Scenario


def load_scenarios(document: BlueprintDocument) -> dict[str, Scenario]:
    result: dict[str, Scenario] = {}
    for raw in document.scenarios:
        if not isinstance(raw, dict):
            continue
        identifier = str(raw.get("id") or "").strip()
        if not identifier:
            continue
        result[identifier] = Scenario(
            identifier=identifier,
            when=dict(raw.get("when") or {}) if isinstance(raw.get("when"), dict) else {},
            expect=dict(raw.get("expect") or {}) if isinstance(raw.get("expect"), dict) else {},
            must_preserve=tuple(str(v) for v in raw.get("must_preserve", []) if isinstance(v, str)),
            evidence=tuple(v for v in raw.get("evidence", []) if isinstance(v, dict)),
        )
    return result
