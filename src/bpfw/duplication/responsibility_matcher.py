"""Responsibility matching heuristics for scanned symbols."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpfw.blueprint.models import BlueprintResponsibility
from bpfw.duplication.naming_policy import tokenize_name
from bpfw.duplication.symbol_scanner import ScannedSymbol


@dataclass(slots=True)
class ResponsibilityMatch:
    """Heuristic match between one symbol and one responsibility."""

    responsibility_id: str
    score: int
    token_overlap: list[str]
    path_aligned: bool



def _responsibility_tokens(responsibility: BlueprintResponsibility) -> set[str]:
    collected_tokens: set[str] = set()
    for token in tokenize_name(responsibility.canonical_name):
        collected_tokens.add(token)
    for token in tokenize_name(responsibility.responsibility_id):
        collected_tokens.add(token)
    for forbidden_symbol in responsibility.forbidden_duplicates:
        for token in tokenize_name(forbidden_symbol):
            collected_tokens.add(token)
    return collected_tokens



def _responsibility_paths(responsibility: BlueprintResponsibility) -> set[str]:
    allowed_roots: set[str] = set()
    for allowed_file in responsibility.allowed_files:
        parent_directory = str(Path(allowed_file).parent)
        if parent_directory and parent_directory != ".":
            allowed_roots.add(parent_directory)
    for implementation in responsibility.allowed_implementations:
        implementation_parent_directory = str(Path(implementation.file).parent)
        if implementation_parent_directory and implementation_parent_directory != ".":
            allowed_roots.add(implementation_parent_directory)
    return allowed_roots



def _is_path_aligned(symbol_path: str, responsibility_roots: set[str]) -> bool:
    normalized_symbol_path = symbol_path.replace("\\", "/")
    for root in responsibility_roots:
        normalized_root = root.replace("\\", "/")
        if normalized_symbol_path.startswith(f"{normalized_root}/") or normalized_symbol_path == normalized_root:
            return True
    return False



def match_symbol_to_responsibility(
    symbol: ScannedSymbol,
    symbol_tokens: set[str],
    responsibility: BlueprintResponsibility,
) -> ResponsibilityMatch:
    """Compute heuristic responsibility score for one symbol."""

    token_overlap = sorted(symbol_tokens.intersection(_responsibility_tokens(responsibility)))
    path_aligned = _is_path_aligned(symbol.file_path, _responsibility_paths(responsibility))

    score = 0
    if path_aligned:
        score += 3
    if token_overlap:
        score += min(4, len(token_overlap) * 2)

    return ResponsibilityMatch(
        responsibility_id=responsibility.responsibility_id,
        score=score,
        token_overlap=token_overlap,
        path_aligned=path_aligned,
    )



def best_responsibility_match(
    symbol: ScannedSymbol,
    symbol_tokens: set[str],
    responsibilities: list[BlueprintResponsibility],
) -> ResponsibilityMatch | None:
    """Return best-scoring responsibility candidate for symbol."""

    if not responsibilities:
        return None

    matches = [
        match_symbol_to_responsibility(
            symbol=symbol,
            symbol_tokens=symbol_tokens,
            responsibility=responsibility,
        )
        for responsibility in responsibilities
    ]
    matches.sort(key=lambda match: match.score, reverse=True)
    best_match = matches[0]
    if best_match.score <= 0:
        return None
    return best_match
