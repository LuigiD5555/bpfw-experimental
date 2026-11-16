"""Data models for purpose suggestion system."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PurposeSuggestion:
    """Represent one stable natural-language purpose suggestion."""

    text: str
    source: str
    evidence: tuple[str, ...]
