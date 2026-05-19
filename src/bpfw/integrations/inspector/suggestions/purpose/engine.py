"""Deterministic semantic purpose suggestions with fixed slots."""

from collections.abc import Iterable
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from bpfw.integrations.inspector.suggestions.purpose.learning import get_learned_purposes
from bpfw.integrations.inspector.suggestions.purpose.models import PurposeSuggestion


def _load_json_payload(file_name: str) -> dict[str, Any]:
    """Load one sibling JSON object safely."""

    payload_path = Path(__file__).with_name(file_name)
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _load_purpose_semantics() -> tuple[set[str], list[str], set[tuple[str, str]]]:
    """Load purpose semantics from local JSON file with safe fallbacks."""

    payload = _load_json_payload("purpose_semantics.json")
    if not payload:
        return set(), [], set()

    raw_stopwords = payload.get("stopwords")
    stopwords: set[str] = set()
    if isinstance(raw_stopwords, list):
        normalized_stopwords = {item.strip().lower() for item in raw_stopwords if isinstance(item, str) and item.strip()}
        if normalized_stopwords:
            stopwords = normalized_stopwords

    raw_markers = payload.get("docstring_section_markers")
    markers: list[str] = []
    if isinstance(raw_markers, list):
        normalized_markers = [item.strip() for item in raw_markers if isinstance(item, str) and item.strip()]
        if normalized_markers:
            markers = normalized_markers

    raw_pairs = payload.get("incompatible_action_pairs")
    incompatible_pairs: set[tuple[str, str]] = set()
    if isinstance(raw_pairs, list):
        normalized_pairs: set[tuple[str, str]] = set()
        for pair in raw_pairs:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            left_raw, right_raw = pair
            if not isinstance(left_raw, str) or not isinstance(right_raw, str):
                continue
            left_action = left_raw.strip().lower()
            right_action = right_raw.strip().lower()
            if not left_action or not right_action:
                continue
            normalized_pairs.add((left_action, right_action))
        if normalized_pairs:
            incompatible_pairs = normalized_pairs

    return stopwords, markers, incompatible_pairs


def _load_action_aliases() -> dict[str, str]:
    """Load action aliases from local JSON file with safe fallback."""

    payload = _load_json_payload("action_aliases.json")
    if not payload:
        return {}

    normalized_aliases: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        source_action = key.strip().lower()
        canonical_action = value.strip().lower()
        if not source_action or not canonical_action:
            continue
        normalized_aliases[source_action] = canonical_action

    return normalized_aliases


_STOPWORDS, _DOCSTRING_SECTION_MARKERS, _INCOMPATIBLE_ACTION_PAIRS = _load_purpose_semantics()
_ACTION_ALIASES = _load_action_aliases()


@dataclass(frozen=True, slots=True)
class BlockPurposeInput:
    """Represent normalized purpose-related fields extracted from one block."""

    symbol: str
    symbol_type: str
    path: str
    docstring: str
    signature: str


@dataclass(frozen=True, slots=True)
class PurposeFacts:
    """Represent normalized semantic facts extracted from a code block."""

    action: str
    object_text: str
    qualifiers: tuple[str, ...]
    source: str


def compact_purpose_text(text: str) -> str:
    """Return normalized purpose text for display."""

    return " ".join(str(text).strip().lower().split())


def suggest_purposes(
    block: dict[str, Any],
    project_blocks: Iterable[dict[str, Any]] | None = None,
    existing_purposes: Iterable[str] | None = None,
    vocabulary: Any = None,
) -> list[PurposeSuggestion]:
    """Return six fixed purpose suggestion slots for one code block."""

    del vocabulary
    current_facts, symbol_facts, docstring_facts = extract_purpose_facts(block)

    existing_values = tuple(existing_purposes or ())
    if not existing_values and project_blocks is not None:
        existing_values = tuple(_collect_existing_purposes(project_blocks, block))

    automatic_suggestions = [
        suggest_existing_purpose(current_facts, existing_values),
        suggest_learned_purpose(current_facts, get_learned_purposes()),
        suggest_symbol_purpose(symbol_facts),
        suggest_docstring_purpose(docstring_facts),
        suggest_fallback_purpose(current_facts, symbol_facts, docstring_facts),
    ]

    deduplicated = deduplicate_suggestions(automatic_suggestions)
    return ensure_fixed_purpose_slots(deduplicated)


def _collect_existing_purposes(project_blocks: Iterable[dict[str, Any]], block: dict[str, Any]) -> list[str]:
    """Collect existing accepted purpose values preserving encounter order."""

    current_identifier = str(block.get("id", "")).strip()
    result: list[str] = []
    seen: set[str] = set()
    for candidate_block in project_blocks:
        candidate_identifier = str(candidate_block.get("id", "")).strip()
        if current_identifier and candidate_identifier == current_identifier:
            continue
        purpose_text = str(candidate_block.get("purpose", "")).strip()
        if not purpose_text or purpose_text == "-":
            continue
        normalized = compact_purpose_text(purpose_text)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(purpose_text)
    return result


def _placeholder(source: str) -> PurposeSuggestion:
    """Return one empty fixed-slot suggestion placeholder."""

    return PurposeSuggestion(text="-", source=source, evidence=(f"source: {source}",))


def _build_block_input(block: dict[str, Any]) -> BlockPurposeInput:
    """Build normalized block input from nested and top-level keys."""

    def _pick(*paths: tuple[str, ...]) -> str:
        for path in paths:
            value: Any = block
            valid = True
            for part in path:
                if not isinstance(value, dict):
                    valid = False
                    break
                value = value.get(part)
            if valid and isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    return BlockPurposeInput(
        symbol=_pick(
            ("symbol",),
            ("code", "symbol"),
            ("location", "symbol"),
            ("detected", "qualified_name"),
        ),
        symbol_type=_pick(
            ("symbol_type",),
            ("code", "symbol_type"),
            ("location", "symbol_type"),
            ("detected", "kind"),
            ("kind",),
        ),
        path=_pick(("path",), ("code", "path"), ("location", "path")),
        docstring=_pick(("detected", "docstring"), ("docstring",)),
        signature=_pick(("signature",), ("detected", "signature")),
    )


def _tokenize_identifier(text: str) -> list[str]:
    """Tokenize identifiers into lowercase semantic tokens."""

    if not text:
        return []
    preprocessed = re.sub(r"[\.-]", " ", text)
    preprocessed = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", preprocessed)
    tokens = re.findall(r"[A-Za-z0-9]+", preprocessed)
    return [token.lower() for token in tokens if token]


def _tokenize_sentence(sentence: str) -> list[str]:
    """Tokenize one sentence into lowercase word tokens."""

    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", sentence)]


def _extract_first_docstring_sentence(docstring: str) -> str:
    """Extract the first semantic docstring sentence before known sections."""

    if not docstring:
        return ""
    text = docstring.strip()
    cut_index = len(text)
    for marker in _DOCSTRING_SECTION_MARKERS:
        position = text.find(marker)
        if position != -1:
            cut_index = min(cut_index, position)
    text = text[:cut_index].strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    sentence = parts[0].strip()
    return sentence.rstrip(".?!").strip()


def _normalize_action(action: str) -> str:
    """Normalize one action token with canonical semantic aliases."""

    lowered = action.lower().strip()
    if not lowered:
        return ""
    return _ACTION_ALIASES.get(lowered, lowered)


def _is_meaningful(token: str) -> bool:
    """Return whether token is meaningful for action/object extraction."""

    return bool(token and token not in _STOPWORDS)


def _first_meaningful(tokens: Iterable[str]) -> str:
    """Return first meaningful token, or empty string."""

    for token in tokens:
        if _is_meaningful(token):
            return token
    return ""


def extract_primary_action(block_input: BlockPurposeInput) -> str:
    """Extract the primary operation performed by the code block."""

    symbol_action = ""
    if block_input.symbol:
        symbol_tail = block_input.symbol.split(".")[-1]
        symbol_tokens = _tokenize_identifier(symbol_tail)
        symbol_action = _first_meaningful(symbol_tokens)
    if symbol_action:
        return _normalize_action(symbol_action)

    first_sentence = _extract_first_docstring_sentence(block_input.docstring)
    sentence_tokens = _tokenize_sentence(first_sentence)
    sentence_action = _first_meaningful(sentence_tokens)
    return _normalize_action(sentence_action)


def _clean_object_tokens(tokens: list[str], action: str) -> list[str]:
    """Clean object tokens by removing grammar words and the action token."""

    normalized_action = _normalize_action(action)
    cleaned: list[str] = []
    for token in tokens:
        if token in _STOPWORDS:
            continue
        if _normalize_action(token) == normalized_action and normalized_action:
            continue
        cleaned.append(token)
    return cleaned


def extract_symbol_object(block_input: BlockPurposeInput, action: str) -> str:
    """Extract the object operated on by the symbol."""

    if not block_input.symbol:
        return ""

    symbol = block_input.symbol
    if "." in symbol:
        class_part, method_part = symbol.rsplit(".", 1)
        class_tokens = _tokenize_identifier(class_part.split(".")[-1])
        method_tokens = _tokenize_identifier(method_part)
        method_object = _clean_object_tokens(method_tokens, action)
        if method_object:
            combined = method_object + [token for token in class_tokens if token not in method_object]
            return " ".join(combined).strip()
        return " ".join(class_tokens).strip()

    function_tokens = _tokenize_identifier(symbol)
    function_object = _clean_object_tokens(function_tokens, action)
    return " ".join(function_object).strip()


def _extract_qualifiers(sentence: str) -> tuple[str, ...]:
    """Extract simple qualifiers from the first docstring sentence."""

    qualifiers: list[str] = []
    for match in re.finditer(r"\b(?:to|from|for|with|in|on)\s+([^,.;]+)", sentence, flags=re.IGNORECASE):
        phrase = match.group(1).strip().lower()
        tokens = [token for token in _tokenize_sentence(phrase) if token not in _STOPWORDS]
        if tokens:
            qualifiers.append(" ".join(tokens))
    return tuple(qualifiers)


def extract_docstring_facts(block_input: BlockPurposeInput) -> PurposeFacts:
    """Extract purpose facts from the first docstring sentence only."""

    sentence = _extract_first_docstring_sentence(block_input.docstring)
    tokens = _tokenize_sentence(sentence)
    action = _normalize_action(_first_meaningful(tokens))

    object_tokens: list[str] = []
    action_found = False
    qualifier_starters = {"to", "from", "for", "with", "in", "on"}
    for token in tokens:
        if action_found and token in qualifier_starters:
            break
        if not _is_meaningful(token):
            continue
        if not action_found and _normalize_action(token) == action and action:
            action_found = True
            continue
        if action_found:
            object_tokens.append(token)

    cleaned_object_tokens = [token for token in object_tokens if token not in _STOPWORDS]
    object_text = " ".join(cleaned_object_tokens).strip()
    qualifiers = _extract_qualifiers(sentence)
    return PurposeFacts(action=action, object_text=object_text, qualifiers=qualifiers, source="docstring")


def extract_purpose_facts(block: dict[str, Any]) -> tuple[PurposeFacts, PurposeFacts, PurposeFacts]:
    """Extract normalized semantic facts from a code block."""

    block_input = _build_block_input(block)
    symbol_action = extract_primary_action(
        BlockPurposeInput(
            block_input.symbol,
            block_input.symbol_type,
            block_input.path,
            "",
            block_input.signature,
        ),
    )
    symbol_object = extract_symbol_object(block_input, symbol_action)
    symbol_facts = PurposeFacts(action=symbol_action, object_text=symbol_object, qualifiers=(), source="symbol")

    docstring_facts = extract_docstring_facts(block_input)

    final_action = symbol_facts.action or docstring_facts.action
    final_object = symbol_facts.object_text or docstring_facts.object_text
    if _is_generic_object(symbol_facts.object_text) and docstring_facts.object_text:
        final_object = docstring_facts.object_text

    current_facts = PurposeFacts(
        action=final_action,
        object_text=final_object,
        qualifiers=docstring_facts.qualifiers,
        source="current",
    )
    return current_facts, symbol_facts, docstring_facts


def _is_generic_object(object_text: str) -> bool:
    """Return whether an object phrase is too generic to be preferred."""

    generic = {"data", "item", "value", "object", "result", "state", "context"}
    tokens = _tokenize_sentence(object_text)
    return len(tokens) <= 1 and any(token in generic for token in tokens)


def _parse_purpose_text(text: str, source: str) -> PurposeFacts:
    """Parse one purpose text into semantic facts for compatibility checks."""

    normalized = compact_purpose_text(text)
    if normalized in {"", "-", "write custom purpose"}:
        return PurposeFacts(action="", object_text="", qualifiers=(), source=source)

    tokens = _tokenize_sentence(normalized)
    action = _normalize_action(_first_meaningful(tokens))

    object_tokens: list[str] = []
    action_seen = False
    for token in tokens:
        if not _is_meaningful(token):
            continue
        if not action_seen and _normalize_action(token) == action and action:
            action_seen = True
            continue
        if action_seen:
            object_tokens.append(token)

    qualifiers = _extract_qualifiers(normalized)
    return PurposeFacts(
        action=action,
        object_text=" ".join(object_tokens).strip(),
        qualifiers=qualifiers,
        source=source,
    )


def _actions_compatible(left: str, right: str) -> bool:
    """Return whether two actions are semantically compatible."""

    if not left or not right:
        return False
    left_action = _normalize_action(left)
    right_action = _normalize_action(right)
    if (left_action, right_action) in _INCOMPATIBLE_ACTION_PAIRS:
        return False
    return left_action == right_action


def _objects_compatible(left: str, right: str) -> bool:
    """Return whether two object phrases are semantically compatible."""

    left_norm = compact_purpose_text(left)
    right_norm = compact_purpose_text(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True

    left_tokens = [token for token in _tokenize_sentence(left_norm) if token not in _STOPWORDS]
    right_tokens = [token for token in _tokenize_sentence(right_norm) if token not in _STOPWORDS]
    shorter = left_tokens if len(left_tokens) <= len(right_tokens) else right_tokens
    if len(shorter) < 2:
        return False

    left_phrase = " ".join(left_tokens)
    right_phrase = " ".join(right_tokens)
    return left_phrase in right_phrase or right_phrase in left_phrase


def _shared_object_tokens(left: str, right: str) -> int:
    """Return shared non-stopword token count between two object phrases."""

    left_tokens = {token for token in _tokenize_sentence(compact_purpose_text(left)) if token not in _STOPWORDS}
    right_tokens = {token for token in _tokenize_sentence(compact_purpose_text(right)) if token not in _STOPWORDS}
    return len(left_tokens.intersection(right_tokens))


def _is_lookup_action(action: str) -> bool:
    """Return whether action belongs to lookup/query family."""

    return _normalize_action(action) in {"get", "return", "load"}


def suggest_existing_purpose(current_facts: PurposeFacts, existing_purposes: Iterable[str]) -> PurposeSuggestion:
    """Suggest a compatible existing purpose."""

    for purpose_text in existing_purposes:
        if not isinstance(purpose_text, str):
            continue
        candidate_facts = _parse_purpose_text(purpose_text, source="existing_purpose")
        if _actions_compatible(
            current_facts.action,
            candidate_facts.action,
        ) and _objects_compatible(
            current_facts.object_text,
            candidate_facts.object_text,
        ):
            return PurposeSuggestion(
                text=compact_purpose_text(purpose_text),
                source="existing_purpose",
                evidence=("source: existing_purpose",),
            )

    # Relaxed fallback: surface a near lookup match by object overlap.
    if _is_lookup_action(current_facts.action):
        best_candidate_text = ""
        best_overlap = 0
        for purpose_text in existing_purposes:
            if not isinstance(purpose_text, str):
                continue
            candidate_facts = _parse_purpose_text(purpose_text, source="existing_purpose")
            if not _is_lookup_action(candidate_facts.action):
                continue
            overlap = _shared_object_tokens(current_facts.object_text, candidate_facts.object_text)
            if overlap >= 2 and overlap > best_overlap:
                best_overlap = overlap
                best_candidate_text = purpose_text
        if best_candidate_text:
            return PurposeSuggestion(
                text=compact_purpose_text(best_candidate_text),
                source="existing_purpose",
                evidence=("source: existing_purpose", "match: relaxed_object_overlap"),
            )
    return _placeholder("existing_purpose")


def suggest_learned_purpose(current_facts: PurposeFacts, learned_purposes: Iterable[str]) -> PurposeSuggestion:
    """Suggest a compatible learned purpose."""

    for purpose_text in learned_purposes:
        candidate_facts = _parse_purpose_text(purpose_text, source="learned_based")
        if _actions_compatible(
            current_facts.action,
            candidate_facts.action,
        ) and _objects_compatible(
            current_facts.object_text,
            candidate_facts.object_text,
        ):
            return PurposeSuggestion(
                text=compact_purpose_text(purpose_text),
                source="learned_based",
                evidence=("source: learned_based",),
            )

    # Relaxed fallback: surface a near lookup match by object overlap.
    if _is_lookup_action(current_facts.action):
        best_candidate_text = ""
        best_overlap = 0
        for purpose_text in learned_purposes:
            candidate_facts = _parse_purpose_text(purpose_text, source="learned_based")
            if not _is_lookup_action(candidate_facts.action):
                continue
            overlap = _shared_object_tokens(current_facts.object_text, candidate_facts.object_text)
            if overlap >= 2 and overlap > best_overlap:
                best_overlap = overlap
                best_candidate_text = purpose_text
        if best_candidate_text:
            return PurposeSuggestion(
                text=compact_purpose_text(best_candidate_text),
                source="learned_based",
                evidence=("source: learned_based", "match: relaxed_object_overlap"),
            )
    return _placeholder("learned_based")


def suggest_symbol_purpose(current_facts: PurposeFacts) -> PurposeSuggestion:
    """Suggest a purpose derived from symbol structure."""

    if not current_facts.action or not current_facts.object_text:
        return _placeholder("name_based")
    return PurposeSuggestion(
        text=compact_purpose_text(f"{current_facts.action} {current_facts.object_text}"),
        source="name_based",
        evidence=("source: name_based",),
    )


def suggest_docstring_purpose(docstring_facts: PurposeFacts) -> PurposeSuggestion:
    """Suggest a purpose derived from the first docstring sentence."""

    if not docstring_facts.action or not docstring_facts.object_text:
        return _placeholder("docstring_based")

    text = f"{docstring_facts.action} {docstring_facts.object_text}".strip()
    if docstring_facts.qualifiers:
        text = f"{text} to {docstring_facts.qualifiers[0]}".strip()

    return PurposeSuggestion(
        text=compact_purpose_text(text),
        source="docstring_based",
        evidence=("source: docstring_based",),
    )


def suggest_fallback_purpose(
    current_facts: PurposeFacts,
    symbol_facts: PurposeFacts,
    docstring_facts: PurposeFacts,
) -> PurposeSuggestion:
    """Suggest a deterministic fallback purpose without blended generation."""

    if symbol_facts.action and docstring_facts.object_text:
        text = f"{symbol_facts.action} {docstring_facts.object_text}"
    elif docstring_facts.action and symbol_facts.object_text:
        text = f"{docstring_facts.action} {symbol_facts.object_text}"
    elif current_facts.action and current_facts.object_text:
        text = f"{current_facts.action} {current_facts.object_text}"
    else:
        return _placeholder("blended_based")

    return PurposeSuggestion(
        text=compact_purpose_text(text),
        source="blended_based",
        evidence=("source: blended_based",),
    )


def deduplicate_suggestions(suggestions: list[PurposeSuggestion]) -> list[PurposeSuggestion]:
    """Replace semantically duplicate suggestions with placeholders preserving order."""

    seen_identities: set[tuple[str, str, tuple[str, ...]]] = set()
    result: list[PurposeSuggestion] = []

    for suggestion in suggestions:
        if suggestion.text == "-":
            result.append(suggestion)
            continue
        facts = _parse_purpose_text(suggestion.text, source=suggestion.source)
        identity = (
            _normalize_action(facts.action),
            compact_purpose_text(facts.object_text),
            tuple(sorted(set(facts.qualifiers))),
        )
        if identity in seen_identities:
            result.append(_placeholder(suggestion.source))
            continue
        seen_identities.add(identity)
        result.append(
            PurposeSuggestion(
                text=compact_purpose_text(suggestion.text),
                source=suggestion.source,
                evidence=suggestion.evidence,
            ),
        )

    return result


def ensure_fixed_purpose_slots(automatic_suggestions: list[PurposeSuggestion]) -> list[PurposeSuggestion]:
    """Return exactly six fixed slots, including the custom purpose slot."""

    slot_sources = ["existing_purpose", "learned_based", "name_based", "docstring_based", "blended_based"]
    by_source = {item.source: item for item in automatic_suggestions}

    result: list[PurposeSuggestion] = []
    for source in slot_sources:
        suggestion = by_source.get(source, _placeholder(source))
        if not suggestion.text.strip():
            suggestion = _placeholder(source)
        result.append(
            PurposeSuggestion(
                text=compact_purpose_text(suggestion.text) or "-",
                source=source,
                evidence=suggestion.evidence,
            ),
        )

    result.append(
        PurposeSuggestion(
            text="write custom purpose",
            source="custom_purpose",
            evidence=("source: custom_purpose",),
        ),
    )
    return result
