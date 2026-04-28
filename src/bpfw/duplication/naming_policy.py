"""Naming heuristics for duplication intent detection."""

from __future__ import annotations

import re
from dataclasses import dataclass


_SUSPICIOUS_TERMS = {
    "manager",
    "processor",
    "helper",
    "utils",
    "smart",
    "enhanced",
    "unified",
    "better",
    "new",
}


@dataclass(slots=True)
class NamingSignals:
    """Derived naming signals from symbol name and responsibility data."""

    symbol_tokens: set[str]
    has_suspicious_term: bool
    suspicious_terms_found: list[str]



def _split_camel_case(name: str) -> str:
    split_stage_one = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    split_stage_two = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", split_stage_one)
    return split_stage_two



def tokenize_name(raw_name: str) -> list[str]:
    """Tokenize snake/camel names into lowercase semantic tokens."""

    normalized_value = _split_camel_case(raw_name.replace("-", " ").replace("_", " "))
    token_candidates = re.split(r"[^A-Za-z0-9]+", normalized_value)
    return [token.lower() for token in token_candidates if token]



def build_naming_signals(symbol_name: str) -> NamingSignals:
    symbol_tokens = set(tokenize_name(symbol_name))
    suspicious_terms_found = sorted(token for token in symbol_tokens if token in _SUSPICIOUS_TERMS)
    return NamingSignals(
        symbol_tokens=symbol_tokens,
        has_suspicious_term=bool(suspicious_terms_found),
        suspicious_terms_found=suspicious_terms_found,
    )



def is_forbidden_duplicate(symbol_name: str, forbidden_duplicates: list[str]) -> bool:
    normalized_symbol_name = symbol_name.strip().lower()
    normalized_forbidden = {forbidden.strip().lower() for forbidden in forbidden_duplicates}
    return normalized_symbol_name in normalized_forbidden
