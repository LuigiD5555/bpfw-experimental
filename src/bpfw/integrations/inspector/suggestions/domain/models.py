"""Domain suggestion models for inspector integration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DomainSuggestion:
    """Represent one deterministic domain suggestion candidate.

    Attributes:
        text: Suggested domain text.
        evidence: Deterministic evidence labels used to produce this suggestion.
    """

    text: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DomainEvidence:
    """Store normalized domain evidence extracted from one block.

    Attributes:
        path_parts: Normalized source path segments.
        module_parts: Normalized module segments.
        symbol_tokens: Tokenized symbol identifier.
        file_stem: File stem extracted from block path.
        docstring_tokens: Tokenized docstring terms.
        origin_key: Stable key used for origin-based domain history.
    """

    path_parts: tuple[str, ...]
    module_parts: tuple[str, ...]
    symbol_tokens: tuple[str, ...]
    file_stem: str
    docstring_tokens: tuple[str, ...]
    origin_key: str
