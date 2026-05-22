"""Declared-vs-discovered drift comparison for BPFW MVP Catalog Mode."""

from typing import Any, Dict, List, Set, Tuple

from bpfw.catalog.models import (
    AUTHORITY_STATE_DEFINED,
    DiscoveredCodeUnit,
)
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding

_SOURCE = "bpfw"

# Type alias for the exact matching key: (path, symbol, kind).
_DeclarationKey = Tuple[str, str, str]


def _extract_declared_keys(
    blueprint_data: Dict[str, Any],
) -> Tuple[Set[_DeclarationKey], Dict[_DeclarationKey, Dict[str, Any]]]:
    """Extract the set of declared block keys from blueprint data."""
    blocks = blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        return set(), {}

    declared_keys: Set[_DeclarationKey] = set()
    declared_by_key: Dict[_DeclarationKey, Dict[str, Any]] = {}

    for block in blocks:
        if not isinstance(block, dict):
            continue

        code = block.get("code", {})
        if not isinstance(code, dict):
            continue

        path = code.get("path")
        symbol = code.get("symbol")
        kind = code.get("kind")

        if path and symbol and kind:
            key = (str(path), str(symbol), str(kind))
            declared_keys.add(key)
            declared_by_key[key] = block

    return declared_keys, declared_by_key


def _extract_discovered_keys(
    discovered_units: List[DiscoveredCodeUnit],
) -> Tuple[Set[_DeclarationKey], Dict[_DeclarationKey, DiscoveredCodeUnit]]:
    """Extract the set of discovered code unit keys.

    Returns a tuple of:
      - The set of all discovered keys.
      - A mapping from each key back to its DiscoveredCodeUnit.
    """
    discovered_keys: Set[_DeclarationKey] = set()
    discovered_by_key: Dict[_DeclarationKey, DiscoveredCodeUnit] = {}

    for unit in discovered_units:
        key = (unit.path, unit.symbol, unit.symbol_type)
        discovered_keys.add(key)
        discovered_by_key[key] = unit

    return discovered_keys, discovered_by_key



def _extract_rule_keys(blueprint_data: Dict[str, Any], section_name: str) -> Set[_DeclarationKey]:
    """Extract path, symbol, and kind keys from an authority rule section.

    Args:
        blueprint_data: Parsed blueprint data.
        section_name: Authority section key, such as ``ignored_code`` or ``covered_code``.

    Returns:
        Set of declaration keys covered by the authority rules.
    """
    authority = blueprint_data.get("authority")
    if not isinstance(authority, dict):
        return set()
    rules = authority.get(section_name)
    if not isinstance(rules, list):
        return set()

    rule_keys: Set[_DeclarationKey] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        path_value = rule.get("path")
        symbol_value = rule.get("symbol")
        kind_value = rule.get("kind") or rule.get("symbol_type")
        if not path_value or not symbol_value:
            continue
        if kind_value:
            rule_keys.add((str(path_value), str(symbol_value), str(kind_value)))
            continue
        for fallback_kind in ("class", "function", "method"):
            rule_keys.add((str(path_value), str(symbol_value), fallback_kind))
    return rule_keys

def _find_missing_declared(
    declared_keys: Set[_DeclarationKey],
    discovered_keys: Set[_DeclarationKey],
) -> List[Finding]:
    """Produce MISSING_DECLARED_CODE findings for declared keys absent from discovery."""
    findings: List[Finding] = []

    missing_keys = declared_keys - discovered_keys
    for declared_path, declared_symbol, declared_kind in sorted(missing_keys):
        findings.append(
            Finding(
                source=_SOURCE,
                code="MISSING_DECLARED_CODE",
                severity=FINDING_SEVERITY_BLOCK,
                path=declared_path,
                symbol=declared_symbol,
                message=(
                    "The blueprint declares this code unit, "
                    "but it was not found in the codebase."
                ),
                evidence={
                    "kind": declared_kind,
                },
            )
        )

    return findings


def _find_undeclared(
    discovered_keys: Set[_DeclarationKey],
    declared_keys: Set[_DeclarationKey],
    discovered_by_key: Dict[_DeclarationKey, DiscoveredCodeUnit],
) -> List[Finding]:
    """Produce UNDECLARED_CODE findings for discovered keys absent from declarations."""
    findings: List[Finding] = []

    undeclared_keys = discovered_keys - declared_keys
    for key in sorted(undeclared_keys):
        unit = discovered_by_key[key]
        findings.append(
            Finding(
                source=_SOURCE,
                code="UNDECLARED_CODE",
                severity=FINDING_SEVERITY_BLOCK,
                path=unit.path,
                symbol=unit.symbol,
                message=(
                    "This code unit exists but is not declared "
                    "in bpfw/blueprint.yaml."
                ),
                evidence={
                    "kind": unit.symbol_type,
                    "qualified_name": unit.qualified_name,
                },
            )
        )

    return findings


def compare_declared_to_discovered(
    blueprint_data: Dict[str, Any],
    discovered_units: List[DiscoveredCodeUnit],
    authority_state: str,
) -> List[Finding]:
    """Compare declared blocks against discovered code units.

    Drift only runs when the blueprint is in the ``defined`` state.  For all
    other states (``missing``, ``empty``, ``invalid``, ``draft``) the
    function returns an empty list — validation handles those cases.

    Matching uses the exact composite key ``path + symbol + kind``.
    No rename detection, no semantic duplicate inference, no lifecycle
    inspection, and no file scanning is performed here.

    Parameters
    ----------
    blueprint_data:
        Parsed YAML content of the blueprint file.
    discovered_units:
        Code units discovered by the AST scanner.
    authority_state:
        One of the ``AUTHORITY_STATE_*`` constants.

    Returns
    -------
    list[Finding]
        Drift findings (``MISSING_DECLARED_CODE`` and/or
        ``UNDECLARED_CODE``).
    """
    # Rules 1-4: non-actionable blueprint states return no drift findings.
    if authority_state != AUTHORITY_STATE_DEFINED:
        return []

    # Rule 5: perform drift comparison only for defined authority.
    declared_keys, _declared_by_key = _extract_declared_keys(blueprint_data)
    discovered_keys, discovered_by_key = _extract_discovered_keys(discovered_units)
    ignored_keys = _extract_rule_keys(blueprint_data, "ignored_code")
    covered_keys = _extract_rule_keys(blueprint_data, "covered_code")
    declared_or_covered_keys = declared_keys | ignored_keys | covered_keys

    findings: List[Finding] = []

    # Rule 6: declared code not found in discovery.
    findings.extend(_find_missing_declared(declared_keys, discovered_keys))

    # Rule 7: discovered code not found in declarations.
    findings.extend(_find_undeclared(discovered_keys, declared_or_covered_keys, discovered_by_key))

    return findings
