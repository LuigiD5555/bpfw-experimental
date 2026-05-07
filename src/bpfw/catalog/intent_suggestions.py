"""Deterministic natural-language intent suggestions for catalog responsibilities."""

import re
from dataclasses import dataclass
from typing import Any

from bpfw.catalog.learning import (
    get_top_learned_intents,
    load_learning_scores,
    score_phrase_context_match,
)

@dataclass(frozen=True, slots=True)
class IntentSuggestion:
    """Represent one deterministic natural-language intent suggestion."""

    text: str
    source: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _EvidenceItem:
    """Represent one weighted source of intent evidence."""

    source: str
    text: str
    weight: int


@dataclass(frozen=True, slots=True)
class _NormalizedFacts:
    """Hold normalized evidence grouped by source confidence."""

    symbol: str
    symbol_type: str
    symbol_tokens: tuple[str, ...]
    path_tokens: tuple[str, ...]
    module_tokens: tuple[str, ...]
    signature_tokens: tuple[str, ...]
    parameter_tokens: tuple[str, ...]
    return_tokens: tuple[str, ...]
    method_tokens: tuple[str, ...]
    function_tokens: tuple[str, ...]
    docstring_tokens: tuple[str, ...]
    import_tokens: tuple[str, ...]
    decorator_tokens: tuple[str, ...]
    raw_functions: tuple[str, ...]
    raw_methods: tuple[str, ...]
    all_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DetectedAction:
    """Represent the selected action and its evidence."""

    verb: str
    score: int
    evidence: tuple[str, ...]
    matched_token: str


@dataclass(frozen=True, slots=True)
class _DetectedObject:
    """Represent the selected object and its evidence."""

    text: str
    score: int
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DetectedContext:
    """Represent the selected context and its evidence."""

    text: str
    score: int
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DetectedBehavior:
    """Represent a behavior signal used to select templates."""

    text: str
    score: int
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    """Represent an unranked intent sentence candidate."""

    text: str
    score: int
    evidence: tuple[str, ...]
    source: str


ACTION_WORDS = {
    "verify": "Validate",
    "check": "Validate",
    "validate": "Validate",
    "assert": "Validate",
    "load": "Load",
    "read": "Load",
    "open": "Load",
    "parse": "Load",
    "save": "Write",
    "write": "Write",
    "dump": "Write",
    "serialize": "Write",
    "scan": "Scan",
    "collect": "Collect",
    "discover": "Scan",
    "tokenize": "Normalize",
    "normalize": "Normalize",
    "compose": "Compose",
    "compare": "Compare",
    "diff": "Compare",
    "match": "Compare",
    "detect": "Detect",
    "find": "Detect",
    "block": "Block",
    "prevent": "Block",
    "deny": "Block",
    "create": "Create",
    "build": "Create",
    "generate": "Create",
    "make": "Create",
    "issue": "Create",
    "resolve": "Resolve",
    "map": "Resolve",
    "convert": "Resolve",
    "render": "Render",
    "format": "Render",
    "display": "Render",
    "delete": "Remove",
    "remove": "Remove",
    "lock": "Protect",
    "protect": "Protect",
    "unlock": "Unlock",
    "run": "Run",
    "execute": "Run",
    "extract": "Extract",
    "suggest": "Suggest",
}

ROLE_TO_ACTION = {
    "issuer": "Create",
    "validator": "Validate",
    "verifier": "Validate",
    "loader": "Load",
    "reader": "Load",
    "parser": "Load",
    "writer": "Write",
    "scanner": "Scan",
    "collector": "Collect",
    "normalizer": "Normalize",
    "composer": "Compose",
    "detector": "Detect",
    "protector": "Protect",
    "renderer": "Render",
    "formatter": "Render",
    "extractor": "Extract",
    "resolver": "Resolve",
    "builder": "Create",
    "factory": "Create",
    "suggestion": "Suggest",
    "suggestor": "Suggest",
    "runner": "Run",
    "executor": "Run",
}

LOW_WEIGHT_ROLES = {
    "manager",
    "handler",
    "service",
    "helper",
    "util",
    "utility",
    "base",
    "abstract",
    "mixin",
    "engine",
    "controller",
}

NOISE_TOKENS = LOW_WEIGHT_ROLES | {
    "src",
    "bpfw",
    "catalog",
    "core",
    "integrations",
    "protection",
    "reports",
    "py",
    "self",
    "none",
    "list",
    "dict",
    "tuple",
    "set",
    "str",
    "int",
    "bool",
    "any",
}

MINIMUM_SCORE = 55
MAX_INTENT_WORDS = 5
MAX_INTENT_CHARACTERS = 48
LOW_VALUE_CONTEXT_PHRASES = (
    "from deterministic responsibility evidence",
    "from one responsibility dictionary",
    "from responsibility evidence",
    "from responsibility data",
    "from evidence",
    "using responsibility evidence",
    "based on responsibility evidence",
)
LOW_VALUE_ADJECTIVES = frozenset(
    {"natural-language", "natural", "language", "deterministic", "ranked", "one", "current", "specific"}
)
COMPACTION_REPLACEMENTS = (
    ("Produce ranked intent suggestions", "Rank intent suggestions"),
    ("Produce intent suggestions", "Suggest intents"),
    ("Suggest natural-language intents", "Suggest intents"),
    ("Suggest natural language intents", "Suggest intents"),
    ("Suggest intent suggestions", "Suggest intents"),
    ("Collect deterministic text evidence", "Collect evidence text"),
    ("Collect text evidence", "Collect evidence text"),
    ("Collect responsibility evidence", "Collect evidence text"),
    ("Build candidate suggestions", "Build suggestions"),
    ("Compose candidate suggestions", "Compose suggestions"),
    ("Compose intent sentence candidates", "Build intent candidates"),
)


def suggest_intents(
    responsibility: dict[str, Any],
    existing_intents: tuple[str, ...] = (),
) -> list[IntentSuggestion]:
    """Suggest intents using stable inspector slots.

    Slot meaning:
    - existing_intent: reuse from current blueprint intents when similar.
    - learned_based: reuse from previously accepted intents when context matches.
    - name_based/docstring_based/blended_based: generated from current code evidence.
    - custom_intent: manual user entry option.
    """

    evidence = _collect_evidence(responsibility)
    facts = _normalize_facts(evidence)
    action = detect_action(facts)
    if action is None:
        return _empty_intent_slots()

    detected_object = detect_object(facts=facts, action=action)
    if detected_object is None:
        return _empty_intent_slots()

    context = detect_context(facts=facts, action=action, detected_object=detected_object)
    behavior = detect_behavior(facts=facts, action=action, detected_object=detected_object)
    slots = compose_fixed_intent_slots(
        action=action,
        detected_object=detected_object,
        context=context,
        behavior=behavior,
        facts=facts,
        existing_intents=existing_intents,
    )
    return normalize_duplicate_slots(slots)


def _empty_intent_slots() -> list[IntentSuggestion]:
    """Return fixed empty intent slots when no intent can be inferred."""

    return [
        IntentSuggestion("-", "existing_intent", ("source: existing_intent",)),
        IntentSuggestion("-", "learned_based", ("source: learned_based",)),
        IntentSuggestion("-", "name_based", ("source: name_based",)),
        IntentSuggestion("-", "docstring_based", ("source: docstring_based",)),
        IntentSuggestion("-", "blended_based", ("source: blended_based",)),
        IntentSuggestion("Write custom intent...", "custom_intent", ("source: custom_intent",)),
    ]


def _make_slot(
    text: str,
    source: str,
    evidence: tuple[str, ...],
) -> IntentSuggestion:
    """Create one fixed suggestion slot with a placeholder when empty."""

    cleaned = compact_intent_text(text)
    if not cleaned:
        cleaned = "-"
    return IntentSuggestion(text=cleaned, source=source, evidence=evidence)


def compose_fixed_intent_slots(
    action: _DetectedAction,
    detected_object: _DetectedObject,
    context: _DetectedContext,
    behavior: _DetectedBehavior,
    facts: _NormalizedFacts,
    existing_intents: tuple[str, ...],
) -> list[IntentSuggestion]:
    """Compose intent suggestions in a fixed inspector slot order."""

    return [
        _make_slot(
            text=_compose_existing_intent_based_candidate(
                facts=facts,
                existing_intents=existing_intents,
            ),
            source="existing_intent",
            evidence=("source: existing_intent",),
        ),
        _make_slot(
            text=_compose_learned_based_candidate(facts=facts),
            source="learned_based",
            evidence=("source: learned_based",),
        ),
        _make_slot(
            text=_compose_name_based_candidate(
                facts=facts,
                action=action,
            ),
            source="name_based",
            evidence=("source: name_based",),
        ),
        _make_slot(
            text=_compose_docstring_based_candidate(
                facts=facts,
                action=action,
            ),
            source="docstring_based",
            evidence=("source: docstring_based",),
        ),
        _make_slot(
            text=_compose_blended_based_candidate(
                action=action,
                detected_object=detected_object,
                context=context,
                behavior=behavior,
                facts=facts,
            ),
            source="blended_based",
            evidence=("source: blended_based",),
        ),
        IntentSuggestion(
            text="Write custom intent...",
            source="custom_intent",
            evidence=("source: custom_intent",),
        ),
    ]


def normalize_duplicate_slots(
    suggestions: list[IntentSuggestion],
) -> list[IntentSuggestion]:
    """Replace repeated suggestion text with placeholders while preserving slot order."""

    seen: set[str] = set()
    normalized: list[IntentSuggestion] = []
    for suggestion in suggestions:
        key = " ".join(tokenize_evidence(suggestion.text))
        if suggestion.text != "-" and key in seen:
            normalized.append(
                IntentSuggestion(
                    text="-",
                    source=suggestion.source,
                    evidence=suggestion.evidence + ("duplicate: hidden",),
                )
            )
            continue
        if suggestion.text != "-":
            seen.add(key)
        normalized.append(suggestion)
    return normalized


def _collect_evidence(responsibility: dict[str, Any]) -> list[_EvidenceItem]:
    """Collect structured deterministic evidence from one responsibility."""

    evidence: list[_EvidenceItem] = []

    location = responsibility.get("location")
    if isinstance(location, dict):
        _append_evidence(evidence, source="path", value=location.get("path"), weight=10)
        _append_evidence(evidence, source="module", value=location.get("module"), weight=10)
        _append_evidence(evidence, source="symbol", value=location.get("symbol"), weight=50)
        _append_evidence(
            evidence,
            source="symbol_type",
            value=location.get("symbol_type"),
            weight=15,
        )

    detected = responsibility.get("detected")
    if isinstance(detected, dict):
        if not any(item.source == "symbol" for item in evidence):
            qualified_name = detected.get("qualified_name")
            if isinstance(qualified_name, str) and qualified_name.strip():
                _append_evidence(
                    evidence,
                    source="symbol",
                    value=qualified_name.split(".")[-1],
                    weight=50,
                )

        if not any(item.source == "symbol_type" for item in evidence):
            _append_evidence(
                evidence,
                source="symbol_type",
                value=detected.get("kind"),
                weight=15,
            )

        _append_evidence(
            evidence,
            source="docstring",
            value=detected.get("docstring"),
            weight=25,
        )
        _append_evidence(
            evidence,
            source="signature",
            value=detected.get("signature"),
            weight=45,
        )

        for source, weight in (
            ("methods", 35),
            ("functions", 25),
            ("imports", 15),
            ("decorators", 15),
        ):
            values = detected.get(source)
            if isinstance(values, list):
                for value in values:
                    _append_evidence(evidence, source=source, value=value, weight=weight)

    for source in ("name", "name"):
        _append_evidence(
            evidence,
            source=source,
            value=responsibility.get(source),
            weight=35,
        )

    return evidence


def _append_evidence(
    evidence: list[_EvidenceItem],
    source: str,
    value: Any,
    weight: int,
) -> None:
    """Append one evidence item when the value is meaningful text."""

    if isinstance(value, str) and value.strip():
        evidence.append(_EvidenceItem(source=source, text=value.strip(), weight=weight))


def collect_evidence_text(responsibility: dict[str, Any]) -> str:
    """Collect deterministic text evidence from one responsibility dictionary."""

    return " ".join(item.text for item in _collect_evidence(responsibility))


def _normalize_facts(evidence: list[_EvidenceItem]) -> _NormalizedFacts:
    """Normalize evidence into source-specific token groups."""

    values_by_source: dict[str, list[str]] = {}
    for item in evidence:
        values_by_source.setdefault(item.source, []).append(item.text)

    symbol = _first_text(values_by_source.get("symbol", []))
    symbol_type = _first_text(values_by_source.get("symbol_type", []))
    signature = _first_text(values_by_source.get("signature", []))
    parameters, return_type = _parse_signature(signature)

    symbol_tokens = tuple(tokenize_evidence(symbol))
    path_tokens = _tokens_from_values(values_by_source.get("path", []))
    module_tokens = _tokens_from_values(values_by_source.get("module", []))
    signature_tokens = tuple(tokenize_evidence(signature))
    parameter_tokens = _tokens_from_values(parameters)
    return_tokens = tuple(tokenize_evidence(return_type))
    method_tokens = _tokens_from_values(values_by_source.get("methods", []))
    function_tokens = _tokens_from_values(values_by_source.get("functions", []))
    docstring_tokens = _tokens_from_values(values_by_source.get("docstring", []))
    import_tokens = _tokens_from_values(values_by_source.get("imports", []))
    decorator_tokens = _tokens_from_values(values_by_source.get("decorators", []))
    all_tokens = (
        symbol_tokens
        + path_tokens
        + module_tokens
        + signature_tokens
        + parameter_tokens
        + return_tokens
        + method_tokens
        + function_tokens
        + docstring_tokens
        + import_tokens
        + decorator_tokens
    )

    return _NormalizedFacts(
        symbol=symbol,
        symbol_type=symbol_type,
        symbol_tokens=symbol_tokens,
        path_tokens=path_tokens,
        module_tokens=module_tokens,
        signature_tokens=signature_tokens,
        parameter_tokens=parameter_tokens,
        return_tokens=return_tokens,
        method_tokens=method_tokens,
        function_tokens=function_tokens,
        docstring_tokens=docstring_tokens,
        import_tokens=import_tokens,
        decorator_tokens=decorator_tokens,
        raw_functions=tuple(values_by_source.get("functions", [])),
        raw_methods=tuple(values_by_source.get("methods", [])),
        all_tokens=all_tokens,
    )


def _first_text(values: list[str]) -> str:
    """Return the first non-empty text from a list."""

    for value in values:
        if value.strip():
            return value.strip()
    return ""


def _tokens_from_values(values: list[str]) -> tuple[str, ...]:
    """Tokenize multiple values into one tuple."""

    tokens: list[str] = []
    for value in values:
        tokens.extend(tokenize_evidence(value))
    return tuple(tokens)


def _parse_signature(signature: str) -> tuple[list[str], str]:
    """Extract parameter fragments and return type from a signature string."""

    if not signature:
        return [], ""

    parameters: list[str] = []
    parameters_match = re.search(r"\((.*?)\)", signature)
    if parameters_match:
        raw_parameters = parameters_match.group(1)
        for raw_parameter in raw_parameters.split(","):
            name = raw_parameter.split(":", 1)[0].strip()
            if name and name != "self":
                parameters.append(name)

    return_type = ""
    return_match = re.search(r"->\s*([^:]+)$", signature)
    if return_match:
        return_type = return_match.group(1).strip()

    return parameters, return_type


def tokenize_evidence(text: str) -> list[str]:
    """Convert technical names and text evidence into normalized tokens."""

    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    spaced = spaced.replace("_", " ").replace("-", " ")
    spaced = spaced.replace("/", " ").replace(".", " ")
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", spaced)
    return [_normalize_token(token) for token in tokens]


def _normalize_token(token: str) -> str:
    """Normalize one token for deterministic ranking."""

    lowered = token.lower()
    if len(lowered) > 4 and lowered.endswith("ies"):
        return f"{lowered[:-3]}y"
    if len(lowered) > 3 and lowered.endswith("s"):
        return lowered[:-1]
    return lowered


def detect_action(facts: _NormalizedFacts) -> _DetectedAction | None:
    """Detect the strongest action from source-weighted normalized facts."""

    candidates: list[_DetectedAction] = []

    command_action = _detect_command_action(facts.symbol_tokens)
    if command_action is not None:
        candidates.append(command_action)

    symbol_action = _detect_action_in_tokens(
        tokens=facts.symbol_tokens,
        score=50,
        evidence_source="symbol",
    )
    if symbol_action is not None:
        candidates.append(symbol_action)

    method_action = _detect_action_in_tokens(
        tokens=facts.method_tokens,
        score=35,
        evidence_source="methods",
    )
    if method_action is not None:
        candidates.append(method_action)

    docstring_action = _detect_action_in_tokens(
        tokens=facts.docstring_tokens,
        score=25,
        evidence_source="docstring",
    )
    if docstring_action is not None:
        candidates.append(docstring_action)

    function_action = _detect_action_in_tokens(
        tokens=facts.function_tokens,
        score=25,
        evidence_source="functions",
    )
    if function_action is not None:
        candidates.append(function_action)

    role_action = _detect_role_action(facts.symbol_tokens)
    if role_action is not None:
        candidates.append(role_action)

    path_action = _detect_action_in_tokens(
        tokens=facts.path_tokens + facts.module_tokens,
        score=10,
        evidence_source="path/module",
    )
    if path_action is not None:
        candidates.append(path_action)

    return _highest_scored(candidates)


def _detect_action_in_tokens(
    tokens: tuple[str, ...],
    score: int,
    evidence_source: str,
) -> _DetectedAction | None:
    """Detect an action from one token stream."""

    low_weight_action: _DetectedAction | None = None
    for token in tokens:
        if token in LOW_WEIGHT_ROLES:
            low_weight_action = _DetectedAction(
                verb=token.title(),
                score=min(score, 15),
                evidence=(f"{evidence_source}: {token}",),
                matched_token=token,
            )
            continue

        verb = ACTION_WORDS.get(token)
        if verb is not None:
            return _DetectedAction(
                verb=verb,
                score=score,
                evidence=(f"{evidence_source}: {token}",),
                matched_token=token,
            )

    return low_weight_action


def _detect_command_action(tokens: tuple[str, ...]) -> _DetectedAction | None:
    """Detect command wrapper symbols as runnable command-line behavior."""

    if "command" not in tokens:
        return None

    if "verify" in tokens or "verification" in tokens:
        return _DetectedAction(
            verb="Run",
            score=50,
            evidence=("symbol: command",),
            matched_token="command",
        )

    return None


def _detect_role_action(tokens: tuple[str, ...]) -> _DetectedAction | None:
    """Detect an action from a class role suffix."""

    for token in reversed(tokens):
        verb = ROLE_TO_ACTION.get(token)
        if verb is not None:
            return _DetectedAction(
                verb=verb,
                score=20,
                evidence=(f"role: {token}",),
                matched_token=token,
            )
    return None


def _highest_scored(candidates: list[_DetectedAction]) -> _DetectedAction | None:
    """Return the highest-scored action candidate."""

    if not candidates:
        return None
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[0]


def detect_object(
    facts: _NormalizedFacts,
    action: _DetectedAction,
) -> _DetectedObject | None:
    """Detect the object acted on by the snippet."""

    all_tokens = facts.all_tokens

    known_object = _detect_known_object(facts=facts, action=action)
    if known_object is not None:
        return known_object

    symbol_object = _object_from_tokens(
        tokens=facts.symbol_tokens,
        action=action,
        score=35,
        evidence_source="symbol",
    )
    if symbol_object is not None:
        return symbol_object

    parameter_object = _object_from_tokens(
        tokens=facts.parameter_tokens + facts.return_tokens,
        action=action,
        score=25,
        evidence_source="signature",
    )
    if parameter_object is not None:
        return parameter_object

    call_object = _object_from_tokens(
        tokens=facts.function_tokens + facts.method_tokens,
        action=action,
        score=20,
        evidence_source="calls",
    )
    if call_object is not None:
        return call_object

    path_object = _object_from_tokens(
        tokens=facts.path_tokens + facts.module_tokens,
        action=action,
        score=10,
        evidence_source="path/module",
    )
    if path_object is not None:
        return path_object

    if "intent" in all_tokens and action.verb == "Suggest":
        return _DetectedObject(
            text="intent",
            score=35,
            evidence=("symbol: intent",),
        )

    return None


def _detect_known_object(
    facts: _NormalizedFacts,
    action: _DetectedAction,
) -> _DetectedObject | None:
    """Detect domain-specific object phrases from deterministic token sets."""

    tokens = set(facts.all_tokens)

    if {"duplicate", "intent"} <= tokens:
        return _DetectedObject(
            text="duplicate active responsibilities by intent",
            score=45,
            evidence=("tokens: duplicate intent",),
        )

    if "authority" in tokens and "file" in tokens:
        return _DetectedObject(
            text="authority files",
            score=40,
            evidence=("tokens: authority file",),
        )

    if "blueprint" in tokens and (
        "authority" in tokens
        or "yaml" in tokens
        or "path" in tokens
        or "loader" in tokens
        or "writer" in tokens
        or action.verb in {"Load", "Write"}
    ):
        return _DetectedObject(
            text="blueprint authority",
            score=40,
            evidence=("tokens: blueprint authority",),
        )

    if "responsibility" in tokens and (
        "declaration" in tokens
        or "compare" in tokens
        or "declared" in tokens
        or "detected" in tokens
    ):
        return _DetectedObject(
            text="responsibility declarations",
            score=40,
            evidence=("tokens: responsibility declarations",),
        )

    if "python" in tokens and ("source" in tokens or "file" in tokens):
        return _DetectedObject(
            text="Python source files",
            score=40,
            evidence=("tokens: python source",),
        )

    if "project" in tokens and ("source" in tokens or "code" in tokens):
        return _DetectedObject(
            text="project source code",
            score=35,
            evidence=("tokens: project source",),
        )

    if "command" in tokens and ("verify" in tokens or "verification" in tokens):
        return _DetectedObject(
            text="blueprint verification",
            score=35,
            evidence=("tokens: verify command",),
        )

    if action.verb == "Suggest" and "intent" in tokens and "responsibility" in tokens:
        return _DetectedObject(
            text="natural-language intents",
            score=45,
            evidence=("tokens: intent responsibility",),
        )

    if action.verb == "Collect" and "evidence" in tokens:
        return _DetectedObject(
            text="responsibility evidence",
            score=40,
            evidence=("tokens: evidence",),
        )

    if action.verb == "Normalize" and "evidence" in tokens:
        return _DetectedObject(
            text="technical evidence tokens",
            score=40,
            evidence=("tokens: evidence",),
        )

    if action.verb == "Compose" and "candidate" in tokens:
        return _DetectedObject(
            text="intent sentence candidates",
            score=40,
            evidence=("tokens: candidate",),
        )

    return None


def _object_from_tokens(
    tokens: tuple[str, ...],
    action: _DetectedAction,
    score: int,
    evidence_source: str,
) -> _DetectedObject | None:
    """Build an object phrase from one token stream."""

    object_tokens = [
        token for token in tokens
        if token != action.matched_token
        and ACTION_WORDS.get(token) != action.verb
        and token not in ROLE_TO_ACTION
        and token not in NOISE_TOKENS
    ]
    object_tokens = _dedupe_tokens(object_tokens)
    if not object_tokens:
        return None

    text = _humanize_object_tokens(object_tokens[:4])
    if not text:
        return None

    return _DetectedObject(
        text=text,
        score=score,
        evidence=(f"{evidence_source}: {' '.join(object_tokens[:4])}",),
    )


def _dedupe_tokens(tokens: list[str]) -> list[str]:
    """Return tokens with duplicates removed while preserving order."""

    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _humanize_object_tokens(tokens: list[str]) -> str:
    """Convert normalized object tokens into a readable object phrase."""

    if not tokens:
        return ""

    replacements = {
        "jwt": "JWT",
        "yaml": "YAML",
        "python": "Python",
        "cli": "command line",
    }
    return " ".join(replacements.get(token, token) for token in tokens)


def detect_context(
    facts: _NormalizedFacts,
    action: _DetectedAction,
    detected_object: _DetectedObject,
) -> _DetectedContext:
    """Detect a useful context phrase for the intent sentence."""

    tokens = set(facts.all_tokens)
    raw_calls = " ".join(facts.raw_functions + facts.raw_methods)

    if action.verb == "Run" and (
        "cli" in tokens or "command" in tokens or "arg" in tokens
    ):
        return _DetectedContext(
            text="from the command line",
            score=20,
            evidence=("tokens: command args",),
        )

    if (
        "compare_responsibilities" in raw_calls
        or {"compare", "responsibility"} <= tokens
        or {"source", "code"} <= tokens
    ):
        return _DetectedContext(
            text="against detected source code",
            score=25,
            evidence=("calls: compare/source",),
        )

    if "drift" in tokens or "missing" in tokens or "undeclared" in tokens:
        return _DetectedContext(
            text="when blueprint drift is detected",
            score=20,
            evidence=("tokens: drift",),
        )

    if action.verb == "Write" and (
        "path" in tokens or "file" in tokens or "yaml" in tokens or "blueprint" in tokens
    ):
        return _DetectedContext(
            text="to disk",
            score=20,
            evidence=("tokens: write path",),
        )

    if action.verb == "Load" and (
        "path" in tokens or "file" in tokens or "yaml" in tokens or "read" in tokens
    ):
        return _DetectedContext(
            text="from disk",
            score=20,
            evidence=("tokens: load path",),
        )

    if "project" in tokens or "project_root" in raw_calls:
        return _DetectedContext(
            text="for a project",
            score=15,
            evidence=("tokens: project",),
        )

    if "lock" in tokens or "protect" in tokens or "os" in tokens:
        return _DetectedContext(
            text="with OS-level protection",
            score=15,
            evidence=("tokens: lock",),
        )

    if "responsibility" in tokens and "evidence" in tokens:
        return _DetectedContext(
            text="from responsibility evidence",
            score=20,
            evidence=("tokens: responsibility evidence",),
        )

    return _DetectedContext(text="", score=0, evidence=())


def detect_behavior(
    facts: _NormalizedFacts,
    action: _DetectedAction,
    detected_object: _DetectedObject,
) -> _DetectedBehavior:
    """Detect behavior signals used by deterministic templates."""

    tokens = set(facts.all_tokens)
    raw_calls = " ".join(facts.raw_functions + facts.raw_methods)

    if "load_blueprint" in raw_calls or (
        action.verb == "Load" and "blueprint" in tokens
    ):
        return _DetectedBehavior(
            text="reads authority from disk",
            score=20,
            evidence=("behavior: load blueprint",),
        )

    if "save_blueprint" in raw_calls or (
        action.verb == "Write" and "blueprint" in tokens
    ):
        return _DetectedBehavior(
            text="writes authority changes",
            score=20,
            evidence=("behavior: save blueprint",),
        )

    if "scan_python_project" in raw_calls or (
        action.verb == "Scan" and "python" in tokens
    ):
        return _DetectedBehavior(
            text="extracts Python source metadata",
            score=20,
            evidence=("behavior: scan python",),
        )

    if "compare_responsibilities" in raw_calls or (
        "compare" in tokens and "responsibility" in tokens
    ):
        return _DetectedBehavior(
            text="compares declared and detected code",
            score=20,
            evidence=("behavior: compare responsibilities",),
        )

    if {"duplicate", "intent"} <= tokens:
        return _DetectedBehavior(
            text="groups duplicate active responsibilities",
            score=20,
            evidence=("behavior: duplicate intents",),
        )

    if action.verb == "Block" or "block" in tokens or "deny" in tokens:
        return _DetectedBehavior(
            text="blocks execution",
            score=20,
            evidence=("behavior: block execution",),
        )

    if action.verb == "Protect" or "lock" in tokens or "protect" in tokens:
        return _DetectedBehavior(
            text="protects authority files",
            score=20,
            evidence=("behavior: protect authority",),
        )

    if action.verb == "Suggest" and {"intent", "evidence"} <= tokens:
        return _DetectedBehavior(
            text="produces ranked intent suggestions",
            score=20,
            evidence=("behavior: suggest intents",),
        )

    if action.verb == "Collect" and "evidence" in tokens:
        return _DetectedBehavior(
            text="collects responsibility evidence",
            score=15,
            evidence=("behavior: collect evidence",),
        )

    if action.verb == "Normalize" and "evidence" in tokens:
        return _DetectedBehavior(
            text="normalizes technical evidence",
            score=15,
            evidence=("behavior: normalize evidence",),
        )

    if action.verb == "Compose" and "candidate" in tokens:
        return _DetectedBehavior(
            text="composes intent candidates",
            score=15,
            evidence=("behavior: compose candidates",),
        )

    return _DetectedBehavior(text="", score=0, evidence=())


def compose_candidates(
    action: _DetectedAction,
    detected_object: _DetectedObject,
    context: _DetectedContext,
    behavior: _DetectedBehavior,
    facts: _NormalizedFacts,
    existing_intents: tuple[str, ...] = (),
) -> list[_Candidate]:
    """Compose deterministic intent sentence candidates."""

    candidates: list[_Candidate] = []
    base_score = action.score + detected_object.score + context.score + behavior.score
    evidence = action.evidence + detected_object.evidence + context.evidence + behavior.evidence

    template_text = _compose_blended_based_candidate(
        action=action,
        detected_object=detected_object,
        context=context,
        behavior=behavior,
        facts=facts,
    )
    if template_text:
        _append_candidate(
            candidates=candidates,
            text=template_text,
            score=base_score + 15,
            evidence=evidence + ("template: specific",),
            source="blended_based",
        )

    name_text = _compose_name_based_candidate(
        facts=facts,
        action=action,
    )
    if name_text:
        _append_candidate(
            candidates=candidates,
            text=name_text,
            score=base_score + 10,
            evidence=evidence + ("source: name_based",),
            source="name_based",
        )

    docstring_text = _compose_docstring_based_candidate(
        facts=facts,
        action=action,
    )
    if docstring_text:
        _append_candidate(
            candidates=candidates,
            text=docstring_text,
            score=base_score + 5,
            evidence=evidence + ("source: docstring_based",),
            source="docstring_based",
        )

    learned_text = _compose_learned_based_candidate(
        facts=facts,
    )
    if learned_text:
        _append_candidate(
            candidates=candidates,
            text=learned_text,
            score=base_score,
            evidence=evidence + ("source: learned_based",),
            source="learned_based",
        )

    existing_text = _compose_existing_intent_based_candidate(
        facts=facts,
        existing_intents=existing_intents,
    )
    if existing_text:
        _append_candidate(
            candidates=candidates,
            text=existing_text,
            score=base_score - 1,
            evidence=evidence + ("source: existing_intent_based",),
            source="existing_intent_based",
        )

    fallback_text = _compose_fallback(
        action=action,
        detected_object=detected_object,
        context=context,
    )
    if fallback_text:
        _append_candidate(
            candidates=candidates,
            text=fallback_text,
            score=base_score - 5,
            evidence=evidence + ("template: fallback",),
            source="blended_based",
        )

    _append_compact_backfill_candidates(
        candidates=candidates,
        action=action,
        facts=facts,
        base_score=base_score - 10,
        evidence=evidence + ("template: backfill",),
    )

    return candidates


def _append_compact_backfill_candidates(
    candidates: list[_Candidate],
    action: _DetectedAction,
    facts: _NormalizedFacts,
    base_score: int,
    evidence: tuple[str, ...],
) -> None:
    """Append compact deterministic fallbacks to keep three distinct options."""

    tokens = set(facts.all_tokens)
    object_tokens = _dedupe_tokens(
        [
            token
            for token in facts.symbol_tokens + facts.parameter_tokens + facts.docstring_tokens
            if token not in NOISE_TOKENS and token not in ACTION_WORDS and token not in ROLE_TO_ACTION
        ]
    )
    object_text = _humanize_object_tokens(object_tokens[:3]) if object_tokens else "data"
    backfills: list[str] = []

    backfills.extend(
        [
            f"{action.verb} {object_text}",
            f"{action.verb} {object_text} options",
            f"{action.verb} {object_text} candidates",
        ]
    )

    if "intent" in tokens and action.verb in {"Suggest", "Compose", "Normalize"}:
        backfills.extend(
            ["Suggest intent options", "Rank intent suggestions", "Build intent candidates"]
        )
    if "evidence" in tokens and action.verb in {"Collect", "Normalize"}:
        backfills.extend(["Collect evidence text", "Normalize evidence facts"])

    for index, text in enumerate(backfills):
        _append_candidate(
            candidates=candidates,
            text=text,
            score=base_score - index,
            evidence=evidence,
            source="blended_based",
        )


def _append_candidate(
    candidates: list[_Candidate],
    text: str,
    score: int,
    evidence: tuple[str, ...],
    source: str,
) -> None:
    """Append one candidate when it is non-empty, distinct, and useful."""

    cleaned = compact_intent_text(text)
    if not cleaned:
        return
    if len(cleaned.split()) < 2:
        return
    if cleaned.startswith(("Handle ", "Manage ", "Process ")):
        return

    normalized = " ".join(tokenize_evidence(cleaned))
    for candidate in candidates:
        if " ".join(tokenize_evidence(candidate.text)) == normalized:
            return
    candidates.append(
        _Candidate(
            text=cleaned,
            score=score,
            evidence=evidence + (f"source: {source}", f"score_breakdown: base={score}"),
            source=source,
        )
    )


def _compose_name_based_candidate(
    facts: _NormalizedFacts,
    action: _DetectedAction,
) -> str:
    symbol_tokens = [token for token in facts.symbol_tokens if token not in NOISE_TOKENS]
    symbol_tokens = [token for token in symbol_tokens if ACTION_WORDS.get(token) != action.verb]
    if not symbol_tokens:
        return ""
    return f"{action.verb} {_humanize_object_tokens(_dedupe_tokens(symbol_tokens)[:3])}"


def _compose_docstring_based_candidate(
    facts: _NormalizedFacts,
    action: _DetectedAction,
) -> str:
    doc_tokens = [
        token
        for token in facts.docstring_tokens
        if token not in NOISE_TOKENS and token not in LOW_WEIGHT_ROLES and token != action.matched_token
    ]
    if not doc_tokens:
        return ""
    return f"{action.verb} {_humanize_object_tokens(_dedupe_tokens(doc_tokens)[:3])}"


def _compose_learned_based_candidate(facts: _NormalizedFacts) -> str:
    """Return best historical learned intent that matches current context, if any."""

    context_text = " ".join(facts.all_tokens)
    learned = get_top_learned_intents(limit=15)
    best_text = ""
    best_score = 0
    for text, count in learned:
        overlap = score_phrase_context_match(text, context_text)
        score = overlap * 10 + min(count, 8)
        if score > best_score and overlap > 0:
            best_score = score
            best_text = text
    return best_text.title() if best_text else ""


def _compose_existing_intent_based_candidate(
    facts: _NormalizedFacts,
    existing_intents: tuple[str, ...],
) -> str:
    """Return best matching current-blueprint intent, if similarity is meaningful."""

    if not existing_intents:
        return ""
    context_tokens = set(facts.all_tokens)
    strong_context_tokens = {
        token
        for token in context_tokens
        if token not in NOISE_TOKENS and token not in LOW_WEIGHT_ROLES and len(token) > 3
    }
    best_intent = ""
    best_overlap = 0
    for intent in existing_intents:
        tokens = set(tokenize_evidence(intent))
        strong_intent_tokens = {
            token
            for token in tokens
            if token not in NOISE_TOKENS and token not in LOW_WEIGHT_ROLES and len(token) > 3
        }
        overlap = len(strong_intent_tokens & strong_context_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_intent = intent
    # Require meaningful similarity before reusing an existing intent.
    if best_overlap < 2:
        return ""
    return best_intent


def _compose_blended_based_candidate(
    action: _DetectedAction,
    detected_object: _DetectedObject,
    context: _DetectedContext,
    behavior: _DetectedBehavior,
    facts: _NormalizedFacts,
) -> str:
    template_text = _compose_template(action, detected_object, context, behavior, facts)
    if template_text:
        return template_text

    behavior_text = _compose_behavior_candidate(
        action=action,
        detected_object=detected_object,
        behavior=behavior,
        context=context,
        facts=facts,
    )
    if behavior_text:
        return behavior_text

    context_text = _compose_context_candidate(
        action=action,
        detected_object=detected_object,
        context=context,
    )
    if context_text:
        return context_text

    return _compose_fallback(
        action=action,
        detected_object=detected_object,
        context=context,
    )


def compact_intent_text(text: str) -> str:
    """Compact an intent suggestion into a short inspector-friendly phrase."""

    compacted = " ".join(text.split()).strip()
    if not compacted:
        return ""

    compacted = remove_low_value_context(compacted)
    compacted = remove_low_value_adjectives(compacted)
    compacted = apply_intent_compaction_rules(compacted)
    compacted = " ".join(compacted.split()).strip()
    compacted = limit_intent_words(compacted, max_words=MAX_INTENT_WORDS)
    if len(compacted) > MAX_INTENT_CHARACTERS:
        compacted = limit_intent_words(compacted, max_words=MAX_INTENT_WORDS - 1)
    if not compacted:
        return ""
    return compacted[0].upper() + compacted[1:]


def remove_low_value_context(text: str) -> str:
    """Remove low-value context phrases from an intent suggestion."""

    for phrase in LOW_VALUE_CONTEXT_PHRASES:
        suffix = f" {phrase}"
        if text.lower().endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


def remove_low_value_adjectives(text: str) -> str:
    """Remove weak adjectives that make intent suggestions noisy."""

    words = text.split()
    filtered: list[str] = []
    for word in words:
        normalized = word.strip(",. ").lower()
        if normalized in LOW_VALUE_ADJECTIVES:
            continue
        filtered.append(word)
    return " ".join(filtered)


def apply_intent_compaction_rules(text: str) -> str:
    """Apply known phrase-level compaction rules to intent text."""

    compacted = text
    for source, target in COMPACTION_REPLACEMENTS:
        if compacted.startswith(source):
            compacted = compacted.replace(source, target, 1)
    return compacted


def limit_intent_words(text: str, max_words: int = MAX_INTENT_WORDS) -> str:
    """Limit an intent suggestion to a maximum number of words."""

    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _compose_behavior_candidate(
    action: _DetectedAction,
    detected_object: _DetectedObject,
    behavior: _DetectedBehavior,
    context: _DetectedContext,
    facts: _NormalizedFacts,
) -> str:
    """Compose a behavior-oriented variant when behavior evidence exists."""

    if not behavior.text:
        return ""
    if "intent suggestion" in behavior.text:
        return "Produce ranked intent suggestions from responsibility evidence"
    if action.verb == "Write" and "authority" in detected_object.text:
        return "Persist blueprint authority changes to disk"
    if context.text:
        return f"{action.verb} {detected_object.text} {context.text}"
    return f"{action.verb} {detected_object.text}"


def _compose_context_candidate(
    action: _DetectedAction,
    detected_object: _DetectedObject,
    context: _DetectedContext,
) -> str:
    """Compose an action + object + context variant."""

    if not context.text:
        return ""
    return f"{action.verb} {detected_object.text} {context.text}"


def _compose_symbol_candidate(
    facts: _NormalizedFacts,
    action: _DetectedAction,
    detected_object: _DetectedObject,
) -> str:
    """Compose a shorter symbol-driven variant as a lower-priority option."""

    symbol_tokens = [token for token in facts.symbol_tokens if token not in NOISE_TOKENS]
    symbol_tokens = [token for token in symbol_tokens if ACTION_WORDS.get(token) != action.verb]
    if not symbol_tokens:
        return ""
    object_text = _humanize_object_tokens(_dedupe_tokens(symbol_tokens)[:3])
    if not object_text:
        return ""
    return f"{action.verb} {object_text}"


def _compose_template(
    action: _DetectedAction,
    detected_object: _DetectedObject,
    context: _DetectedContext,
    behavior: _DetectedBehavior,
    facts: _NormalizedFacts,
) -> str:
    """Compose a specific deterministic template when evidence is strong."""

    tokens = set(facts.all_tokens)

    if action.verb == "Validate" and (
        "compare" in tokens
        or behavior.text == "compares declared and detected code"
        or context.text == "against detected source code"
    ):
        return "Validate blueprint declarations against detected source code"

    if action.verb == "Load" and "blueprint" in tokens:
        return "Load blueprint authority from disk"

    if action.verb == "Write" and "blueprint" in tokens:
        return "Write blueprint authority changes to disk"

    if action.verb == "Scan" and ("python" in tokens or "source" in tokens):
        return "Scan Python source files for declared code units"

    if action.verb == "Detect" and {"duplicate", "intent"} <= tokens:
        return "Detect duplicate active responsibilities by intent"

    if action.verb == "Protect" and "authority" in tokens:
        return "Protect authority files from direct modification"

    if action.verb == "Run" and (
        "verify" in tokens or "verification" in tokens
    ) and ("command" in tokens or "cli" in tokens or "arg" in tokens):
        return "Run blueprint verification from the command line"

    if action.verb == "Suggest" and {"intent", "responsibility", "evidence"} <= tokens:
        return "Suggest natural-language intents from responsibility evidence"

    if action.verb == "Suggest" and "intent" in tokens:
        return "Suggest intent"

    if action.verb == "Collect" and "evidence" in tokens:
        return "Collect responsibility evidence"

    if action.verb == "Normalize" and "evidence" in tokens:
        return "Normalize technical evidence tokens"

    if action.verb == "Compose" and "candidate" in tokens:
        return "Compose intent sentence candidates"

    return ""


def _compose_fallback(
    action: _DetectedAction,
    detected_object: _DetectedObject,
    context: _DetectedContext,
) -> str:
    """Compose a high-evidence fallback sentence."""

    if context.text:
        return f"{action.verb} {detected_object.text} {context.text}"
    return f"{action.verb} {detected_object.text}"


def rank_suggestions(candidates: list[_Candidate]) -> list[IntentSuggestion]:
    """Legacy helper: convert candidates to suggestions without reordering by score."""

    suggestions: list[IntentSuggestion] = []
    for candidate in candidates:
        suggestions.append(
            IntentSuggestion(
                text=candidate.text,
                source=candidate.source,
                evidence=candidate.evidence,
            )
        )
    return deduplicate_suggestions(suggestions)[:5]


def _apply_source_quota(
    ranked_suggestions: list[IntentSuggestion],
    original_candidates: list[_Candidate],
    limit: int,
) -> list[IntentSuggestion]:
    """Keep at most one suggestion per source before filling remaining slots."""

    by_text_source: dict[str, str] = {}
    for candidate in original_candidates:
        normalized_key = " ".join(tokenize_evidence(candidate.text))
        # Keep first source seen for this normalized text to preserve
        # the primary channel ordering from candidate composition.
        if normalized_key not in by_text_source:
            by_text_source[normalized_key] = candidate.source
    chosen: list[IntentSuggestion] = []
    seen_sources: set[str] = set()
    leftovers: list[IntentSuggestion] = []
    for suggestion in ranked_suggestions:
        key = " ".join(tokenize_evidence(suggestion.text))
        source = by_text_source.get(key, "blended_based")
        if source not in seen_sources:
            chosen.append(suggestion)
            seen_sources.add(source)
        else:
            leftovers.append(suggestion)
    for suggestion in leftovers:
        if len(chosen) >= limit:
            break
        chosen.append(suggestion)
    return chosen[:limit]


def _intent_learning_boost(
    normalized_text: str,
    learning_scores: dict[str, int],
) -> int:
    """Return a bounded learning boost for one normalized phrase."""

    count = learning_scores.get(normalized_text, 0)
    if count <= 0:
        return 0
    return min(12, count * 2)


def _diversify_suggestions(
    suggestions: list[IntentSuggestion],
    limit: int,
) -> list[IntentSuggestion]:
    """Prefer high-scored suggestions with distinct compact semantics."""

    diversified: list[IntentSuggestion] = []
    seen_heads: set[str] = set()
    seen_text: set[str] = set()

    for suggestion in suggestions:
        normalized_tokens = tokenize_evidence(suggestion.text)
        if not normalized_tokens:
            continue
        normalized_text = " ".join(normalized_tokens)
        if normalized_text in seen_text:
            continue

        semantic_head = " ".join(normalized_tokens[:2])
        if semantic_head in seen_heads and len(diversified) >= max(2, limit - 2):
            continue

        diversified.append(suggestion)
        seen_text.add(normalized_text)
        seen_heads.add(semantic_head)
        if len(diversified) >= limit:
            break

    return diversified


def _fill_missing_with_synthetic_blends(
    suggestions: list[IntentSuggestion],
    limit: int,
) -> list[IntentSuggestion]:
    """Backfill missing slots by blending strong existing suggestions."""

    if len(suggestions) >= limit:
        return suggestions[:limit]
    if not suggestions:
        return suggestions

    existing_keys = {" ".join(tokenize_evidence(item.text)) for item in suggestions}
    seed_texts = [item.text for item in suggestions]
    verb = seed_texts[0].split()[0] if seed_texts[0].split() else "Define"

    token_pool: list[str] = []
    for text in seed_texts:
        tokens = [
            token
            for token in tokenize_evidence(text)
            if token not in NOISE_TOKENS and token not in LOW_WEIGHT_ROLES and token not in {"suggest", "create", "build", "define", "maintain"}
        ]
        for token in tokens:
            if token not in token_pool:
                token_pool.append(token)

    synthetic_candidates: list[str] = []
    if token_pool:
        primary = token_pool[0]
        synthetic_candidates.append(f"{verb} {primary} options")
        if len(token_pool) >= 2:
            synthetic_candidates.append(f"{verb} {token_pool[0]} {token_pool[1]}")
        synthetic_candidates.append(f"{verb} {primary} model")
    synthetic_candidates.extend(
        [
            f"{verb} domain options",
            f"{verb} domain metadata",
            f"{verb} domain structure",
        ]
    )

    filled = list(suggestions)
    for text in synthetic_candidates:
        compacted = compact_intent_text(text)
        normalized = " ".join(tokenize_evidence(compacted))
        if not compacted or normalized in existing_keys:
            continue
        existing_keys.add(normalized)
        filled.append(
            IntentSuggestion(
                text=compacted,
                source="synthetic_blended",
                evidence=("source: synthetic_blended",),
            )
        )
        if len(filled) >= limit:
            break

    return filled[:limit]


def deduplicate_suggestions(
    suggestions: list[IntentSuggestion],
) -> list[IntentSuggestion]:
    """Remove duplicate intent suggestions while preserving first occurrence."""

    by_text: dict[str, IntentSuggestion] = {}

    for suggestion in suggestions:
        normalized_text = " ".join(tokenize_evidence(suggestion.text))
        existing = by_text.get(normalized_text)
        if existing is None:
            by_text[normalized_text] = suggestion

    return list(by_text.values())
