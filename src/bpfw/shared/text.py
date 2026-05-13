"""Shared text normalization helpers."""


def to_snake_case(value: object) -> str:
    """Convert a value to snake_case, returning an empty string when blank."""

    if value is None:
        return ""

    value_text = str(value).strip()
    if not value_text:
        return ""

    result: list[str] = []
    for character in value_text:
        if character.isupper():
            if result and result[-1] != "_":
                result.append("_")
            result.append(character.lower())
        elif character in (" ", "-", "."):
            if result and result[-1] != "_":
                result.append("_")
        else:
            result.append(character)
    return "".join(result).strip("_")


def normalize_text_command(raw_value: str) -> str:
    """Normalize free-form command input for interactive dispatch."""

    return raw_value.strip().lower()
