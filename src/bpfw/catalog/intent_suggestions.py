"""Deterministic natural-language intent suggestions for catalog responsibilities."""

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IntentSuggestion:
    """Represent one deterministic natural-language intent suggestion."""

    text: str
    score: int
    evidence: tuple[str, ...]


ACTION_WORDS = {
    "create": "Create",
    "generate": "Create",
    "build": "Build",
    "make": "Create",
    "issue": "Create",
    "provide": "Provide",
    "validate": "Validate",
    "verify": "Validate",
    "check": "Validate",
    "assert": "Validate",
    "load": "Load",
    "read": "Read",
    "open": "Load",
    "parse": "Parse",
    "save": "Write",
    "write": "Write",
    "dump": "Write",
    "serialize": "Serialize",
    "scan": "Scan",
    "collect": "Collect",
    "discover": "Discover",
    "detect": "Detect",
    "find": "Detect",
    "protect": "Protect",
    "lock": "Protect",
    "block": "Block",
    "prevent": "Block",
    "render": "Render",
    "format": "Format",
    "display": "Render",
    "resolve": "Resolve",
    "map": "Map",
    "convert": "Convert",
    "extract": "Extract",
}

ROLE_TO_ACTION = {
    "issuer": "Create",
    "validator": "Validate",
    "verifier": "Validate",
    "loader": "Load",
    "reader": "Read",
    "parser": "Parse",
    "writer": "Write",
    "scanner": "Scan",
    "detector": "Detect",
    "protector": "Protect",
    "renderer": "Render",
    "formatter": "Format",
    "extractor": "Extract",
    "resolver": "Resolve",
    "builder": "Build",
    "factory": "Create",
    "repository": "Store",
}

CONTEXT_WORDS = {
    "auth": "authentication",
    "jwt": "JWT",
    "token": "token",
    "blueprint": "blueprint",
    "authority": "authority",
    "catalog": "catalog",
    "drift": "drift",
    "source": "source code",
    "scanner": "source scanner",
    "verify": "verification",
    "lock": "protection",
}


def suggest_intents(responsibility: dict[str, Any]) -> list[IntentSuggestion]:
    """Suggest natural-language intents from deterministic responsibility evidence."""

    evidence_text = collect_evidence_text(responsibility)
    tokens = tokenize_evidence(evidence_text)

    suggestions = [
        build_symbol_based_suggestion(responsibility, tokens),
        build_method_based_suggestion(responsibility, tokens),
        build_path_based_suggestion(responsibility, tokens),
    ]

    valid_suggestions = [
        suggestion for suggestion in suggestions
        if suggestion is not None and suggestion.text.strip()
    ]

    unique_suggestions = deduplicate_suggestions(valid_suggestions)
    return sorted(unique_suggestions, key=lambda suggestion: suggestion.score, reverse=True)[:3]


def collect_evidence_text(responsibility: dict[str, Any]) -> str:
    """Collect deterministic text evidence from one responsibility dictionary."""

    parts: list[str] = []

    for key in ("intent", "canonical_name", "name"):
        value = responsibility.get(key)
        if isinstance(value, str):
            parts.append(value)

    location = responsibility.get("location")
    if isinstance(location, dict):
        for key in ("path", "module", "symbol", "symbol_type"):
            value = location.get(key)
            if isinstance(value, str):
                parts.append(value)

    detected = responsibility.get("detected")
    if isinstance(detected, dict):
        for key in ("qualified_name", "kind", "docstring", "signature"):
            value = detected.get(key)
            if isinstance(value, str):
                parts.append(value)

        for key in ("methods", "functions", "imports", "decorators"):
            values = detected.get(key)
            if isinstance(values, list):
                parts.extend(str(value) for value in values)

    return " ".join(parts)


def tokenize_evidence(text: str) -> list[str]:
    """Convert technical names and text evidence into normalized tokens."""

    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    spaced = spaced.replace("_", " ").replace("-", " ").replace("/", " ").replace(".", " ")
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", spaced)]


def build_symbol_based_suggestion(
    responsibility: dict[str, Any],
    tokens: list[str],
) -> IntentSuggestion | None:
    """Build an intent suggestion from the symbol name and known role suffixes."""

    symbol = get_symbol_name(responsibility)
    if not symbol:
        return None

    symbol_tokens = tokenize_evidence(symbol)
    action = detect_action_from_role(symbol_tokens) or detect_action(tokens)
    object_text = detect_object_from_symbol(symbol_tokens)

    if not action or not object_text:
        return None

    context = detect_context(tokens)
    text = compose_intent(action=action, object_text=object_text, context=context)

    return IntentSuggestion(
        text=text,
        score=70,
        evidence=(f"symbol: {symbol}",),
    )


def build_method_based_suggestion(
    responsibility: dict[str, Any],
    tokens: list[str],
) -> IntentSuggestion | None:
    """Build an intent suggestion from detected methods or functions."""

    action = detect_action(tokens)
    object_text = detect_object(tokens)

    if not action or not object_text:
        return None

    context = detect_context(tokens)
    text = compose_intent(action=action, object_text=object_text, context=context)

    return IntentSuggestion(
        text=text,
        score=60,
        evidence=("methods/functions",),
    )


def build_path_based_suggestion(
    responsibility: dict[str, Any],
    tokens: list[str],
) -> IntentSuggestion | None:
    """Build an intent suggestion from path and domain-like evidence."""

    action = detect_action(tokens)
    context = detect_context(tokens)
    object_text = detect_object(tokens)

    if not action or not object_text:
        return None

    text = compose_intent(action=action, object_text=object_text, context=context)

    return IntentSuggestion(
        text=text,
        score=45,
        evidence=("path/module",),
    )


def get_symbol_name(responsibility: dict[str, Any]) -> str:
    """Return the most specific symbol name available in a responsibility."""

    location = responsibility.get("location")
    if isinstance(location, dict):
        symbol = location.get("symbol")
        if isinstance(symbol, str) and symbol.strip():
            return symbol.strip()

    detected = responsibility.get("detected")
    if isinstance(detected, dict):
        qualified_name = detected.get("qualified_name")
        if isinstance(qualified_name, str) and qualified_name.strip():
            return qualified_name.split(".")[-1].strip()

    return ""


def detect_action(tokens: list[str]) -> str:
    """Detect the strongest action from normalized evidence tokens."""

    for token in tokens:
        action = ACTION_WORDS.get(token)
        if action:
            return action
    return ""


def detect_action_from_role(tokens: list[str]) -> str:
    """Detect an action from class role suffix tokens."""

    for token in reversed(tokens):
        action = ROLE_TO_ACTION.get(token)
        if action:
            return action
    return ""


def detect_object_from_symbol(tokens: list[str]) -> str:
    """Detect the object portion of a symbol name."""

    object_tokens = [token for token in tokens if token not in ROLE_TO_ACTION]
    return humanize_object(object_tokens)


def detect_object(tokens: list[str]) -> str:
    """Detect a likely business object from evidence tokens."""

    priority = (
        "blueprint",
        "authority",
        "responsibility",
        "declaration",
        "token",
        "user",
        "project",
        "source",
        "code",
        "file",
        "drift",
        "catalog",
    )

    selected = [token for token in priority if token in tokens]
    return humanize_object(selected[:3])


def detect_context(tokens: list[str]) -> str:
    """Detect a useful context phrase from evidence tokens."""

    if "auth" in tokens or "authentication" in tokens:
        return "for authentication flows"

    if "blueprint" in tokens and ("source" in tokens or "code" in tokens):
        return "against detected source code"

    if "disk" in tokens or "path" in tokens or "file" in tokens:
        return "from disk"

    if "project" in tokens:
        return "for a project"

    return ""


def compose_intent(action: str, object_text: str, context: str) -> str:
    """Compose a natural-language intent from deterministic parts."""

    if context:
        return f"{action} {object_text} {context}"
    return f"{action} {object_text}"


def humanize_object(tokens: list[str]) -> str:
    """Convert object tokens into a readable object phrase."""

    if not tokens:
        return ""

    mapped_tokens = [CONTEXT_WORDS.get(token, token) for token in tokens]
    return " ".join(mapped_tokens)


def deduplicate_suggestions(
    suggestions: list[IntentSuggestion],
) -> list[IntentSuggestion]:
    """Remove duplicate intent suggestions while preserving highest scores."""

    by_text: dict[str, IntentSuggestion] = {}

    for suggestion in suggestions:
        existing = by_text.get(suggestion.text)
        if existing is None or suggestion.score > existing.score:
            by_text[suggestion.text] = suggestion

    return list(by_text.values())