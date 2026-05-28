"""PURPOSE domain suggestion models for inspector tool
DOMAIN  domain suggestions
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DomainSuggestion:
    """PURPOSE store information about one stable domain suggestion candidate
    DOMAIN  domain suggestions
    """

    text: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DomainEvidence:
    """PURPOSE store clean domain evidence extracted from one block
    DOMAIN  domain suggestions
    """

    path_parts: tuple[str, ...]
    module_parts: tuple[str, ...]
    symbol_tokens: tuple[str, ...]
    file_stem: str
    docstring_tokens: tuple[str, ...]
    origin_key: str
