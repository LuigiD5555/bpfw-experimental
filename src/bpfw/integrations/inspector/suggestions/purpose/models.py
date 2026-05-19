"""Data models for purpose suggestion system."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PurposeSuggestion:
    """Represent one deterministic natural-language purpose suggestion.

    Attributes:
        text: Suggested purpose text shown to the user.
        source: Deterministic slot source identifier.
        evidence: Deterministic evidence labels used for the suggestion.
    """

    text: str
    source: str
    evidence: tuple[str, ...]
