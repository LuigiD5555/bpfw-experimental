"""PURPOSE data models for purpose suggestion system
DOMAIN  purpose suggestions
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PurposeSuggestion:
    """PURPOSE store information about one stable natural-language purpose suggestion
    DOMAIN  purpose suggestions
    """

    text: str
    source: str
    evidence: tuple[str, ...]
