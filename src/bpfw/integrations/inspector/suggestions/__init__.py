"""Inspector-only suggestion and learning modules."""

from bpfw.integrations.inspector.suggestions.domain import (
    DomainSuggestion,
    resolve_domain_origin_key,
    suggest_domains,
)
from bpfw.integrations.inspector.suggestions.purpose import (
    PurposeSuggestion,
    compact_purpose_text,
    suggest_purposes,
)

__all__ = [
    "DomainSuggestion",
    "PurposeSuggestion",
    "compact_purpose_text",
    "resolve_domain_origin_key",
    "suggest_domains",
    "suggest_purposes",
]
