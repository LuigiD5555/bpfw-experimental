"""PURPOSE canonical symbol type vocabulary shared by init and planner
DOMAIN  blueprint checks
"""

from typing import Final


VALID_SYMBOL_TYPES: Final[tuple[str, ...]] = (
    "class",
    "function",
    "method",
    "module",
    "dataclass",
    "protocol",
    "enum",
    "exception",
    "nested_class",
    "nested_function",
)


SYMBOL_TYPE_ALIASES: Final[dict[str, str]] = {
    "nested_method": "method",
}


def normalize_symbol_type(raw_symbol_type: str) -> str:
    """PURPOSE get canonical symbol type with safe fallback
    DOMAIN  blueprint checks
    """

    normalized = (raw_symbol_type or "").strip().lower()
    normalized = SYMBOL_TYPE_ALIASES.get(normalized, normalized)
    if normalized in VALID_SYMBOL_TYPES:
        return normalized
    return "function"
