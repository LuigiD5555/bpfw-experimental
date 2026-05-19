"""Behavior-based domain matching for inspector domain suggestion slots."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from bpfw.integrations.inspector.suggestions.domain.tokenizer import tokenize_identifier

DOCSTRING_SECTION_HEADERS = (
    "args:",
    "arguments:",
    "parameters:",
    "returns:",
    "raises:",
    "examples:",
    "notes:",
    "attributes:",
    "yields:",
)

STRUCTURAL_NOISE_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "to",
        "from",
        "of",
        "in",
        "on",
        "for",
        "with",
        "by",
        "and",
        "or",
        "if",
        "when",
        "this",
        "that",
    }
)

INVALID_DOMAINS = frozenset({"-", "custom", "general"})

# Current block evidence weights by source.
SOURCE_WEIGHT_BY_KIND: dict[str, float] = {
    "docstring_summary": 4.0,
    "symbol": 3.0,
    "called_symbols": 2.0,
    "raised_exceptions": 2.0,
    "signature_parameters": 1.5,
    "imports": 1.0,
}

# Historical profile weights by source.
PROFILE_WEIGHT_BY_KIND: dict[str, float] = {
    "docstring_summary": 2.0,
    "symbol": 1.5,
    "called_symbols": 1.0,
    "raised_exceptions": 1.0,
    "signature_parameters": 0.8,
    "imports": 0.6,
}

MINIMUM_USEFUL_SCORE = 6.0


class BehaviorFingerprint:
    """Store weighted behavior evidence extracted from one block.

    Attributes:
        token_weights_by_source: Source-tagged token weight map.
        phrase2_weights: Two-word phrase weight map.
        phrase3_weights: Three-word phrase weight map.
    """

    def __init__(self) -> None:
        """Initialize an empty behavior fingerprint."""

        self.token_weights_by_source: dict[str, dict[str, float]] = defaultdict(dict)
        self.phrase2_weights: dict[str, float] = defaultdict(float)
        self.phrase3_weights: dict[str, float] = defaultdict(float)

    def add_tokens(self, source: str, tokens: list[str], weight: float) -> None:
        """Add weighted token and phrase evidence for one source.

        Args:
            source: Evidence source label.
            tokens: Normalized tokens from the source.
            weight: Weight to add per token and phrase.
        """

        if not tokens:
            return

        source_bucket = self.token_weights_by_source[source]
        for token in tokens:
            source_bucket[token] = source_bucket.get(token, 0.0) + weight

        for index in range(len(tokens) - 1):
            phrase2 = f"{tokens[index]} {tokens[index + 1]}"
            self.phrase2_weights[phrase2] += weight

        for index in range(len(tokens) - 2):
            phrase3 = f"{tokens[index]} {tokens[index + 1]} {tokens[index + 2]}"
            self.phrase3_weights[phrase3] += weight

    def merged_token_weights(self) -> dict[str, float]:
        """Return token weights merged across all sources."""

        merged: dict[str, float] = defaultdict(float)
        for source_bucket in self.token_weights_by_source.values():
            for token, weight in source_bucket.items():
                merged[token] += weight
        return dict(merged)


class DomainBehaviorProfile:
    """Store one historical domain behavior profile.

    Attributes:
        domain: Domain name.
        token_weights: Aggregated token weights.
        phrase2_weights: Aggregated two-word phrase weights.
        phrase3_weights: Aggregated three-word phrase weights.
        contributing_blocks: Number of accepted blocks used in the profile.
    """

    def __init__(self, domain: str) -> None:
        """Initialize one profile for a domain."""

        self.domain = domain
        self.token_weights: dict[str, float] = defaultdict(float)
        self.phrase2_weights: dict[str, float] = defaultdict(float)
        self.phrase3_weights: dict[str, float] = defaultdict(float)
        self.contributing_blocks = 0

    def absorb(self, fingerprint: BehaviorFingerprint) -> None:
        """Accumulate one block fingerprint into this profile.

        Args:
            fingerprint: Extracted behavior fingerprint from one accepted block.
        """

        for token, weight in fingerprint.merged_token_weights().items():
            self.token_weights[token] += weight
        for phrase, weight in fingerprint.phrase2_weights.items():
            self.phrase2_weights[phrase] += weight
        for phrase, weight in fingerprint.phrase3_weights.items():
            self.phrase3_weights[phrase] += weight
        self.contributing_blocks += 1


def suggest_behavior_domains(
    block: dict[str, Any],
    project_blocks: list[dict[str, Any]],
    current_identity: tuple[str, str, str],
) -> list[str]:
    """Return the top 3 existing domains that best match current block behavior.

    Args:
        block: Current block.
        project_blocks: Full project blocks used as historical accepted data.
        current_identity: Stable identity tuple for excluding the current block.

    Returns:
        Exactly three strings for inspector slots ``[q]``, ``[w]``, and ``[e]``.
    """

    current_fingerprint = extract_behavior_fingerprint(block, for_profile=False)
    profiles = _build_historical_profiles(
        project_blocks=project_blocks,
        current_identity=current_identity,
    )
    ranked_domains = _rank_profiles(current_fingerprint=current_fingerprint, profiles=profiles)

    slots = ranked_domains[:3]
    while len(slots) < 3:
        slots.append("-")
    return slots


def extract_behavior_fingerprint(block: dict[str, Any], for_profile: bool) -> BehaviorFingerprint:
    """Extract a behavior fingerprint from one block.

    Args:
        block: Block dictionary containing code and detected metadata.
        for_profile: Whether this fingerprint is for historical profile aggregation.

    Returns:
        Weighted behavior fingerprint.
    """

    fingerprint = BehaviorFingerprint()
    detected = block.get("detected")
    detected_dict = detected if isinstance(detected, dict) else {}

    docstring_tokens = _extract_docstring_summary_tokens(detected_dict.get("docstring"))
    symbol_tokens = _extract_symbol_tokens(block)
    called_tokens = _extract_called_symbol_tokens(detected_dict)
    raised_tokens = _extract_raised_exception_tokens(detected_dict)
    parameter_tokens = _extract_signature_parameter_tokens(detected_dict.get("signature"))
    import_tokens = _extract_import_tokens(detected_dict)

    source_weights = PROFILE_WEIGHT_BY_KIND if for_profile else SOURCE_WEIGHT_BY_KIND

    fingerprint.add_tokens("docstring_summary", docstring_tokens, source_weights["docstring_summary"])
    fingerprint.add_tokens("symbol", symbol_tokens, source_weights["symbol"])
    fingerprint.add_tokens("called_symbols", called_tokens, source_weights["called_symbols"])
    fingerprint.add_tokens("raised_exceptions", raised_tokens, source_weights["raised_exceptions"])
    fingerprint.add_tokens("signature_parameters", parameter_tokens, source_weights["signature_parameters"])
    fingerprint.add_tokens("imports", import_tokens, source_weights["imports"])

    return fingerprint


def extract_docstring_behavior_terms(docstring: Any) -> tuple[list[str], list[str], list[str]]:
    """Extract behavior token and phrase evidence from a raw docstring.

    Args:
        docstring: Raw docstring value.

    Returns:
        Tuple of ``(tokens, two_word_phrases, three_word_phrases)``.
    """

    tokens = _extract_docstring_summary_tokens(docstring)
    phrases2: list[str] = []
    phrases3: list[str] = []

    for index in range(len(tokens) - 1):
        phrases2.append(f"{tokens[index]} {tokens[index + 1]}")
    for index in range(len(tokens) - 2):
        phrases3.append(f"{tokens[index]} {tokens[index + 1]} {tokens[index + 2]}")

    return tokens, phrases2, phrases3


def _build_historical_profiles(
    project_blocks: list[dict[str, Any]],
    current_identity: tuple[str, str, str],
) -> dict[str, DomainBehaviorProfile]:
    """Build historical domain profiles from accepted project blocks."""

    profiles: dict[str, DomainBehaviorProfile] = {}

    for candidate_block in project_blocks:
        if not isinstance(candidate_block, dict):
            continue

        candidate_domain = _normalize_domain(candidate_block.get("domain"))
        if not candidate_domain:
            continue

        candidate_identity = _resolve_block_identity(candidate_block)
        if candidate_identity == current_identity:
            continue

        fingerprint = extract_behavior_fingerprint(candidate_block, for_profile=True)

        profile = profiles.get(candidate_domain)
        if profile is None:
            profile = DomainBehaviorProfile(candidate_domain)
            profiles[candidate_domain] = profile
        profile.absorb(fingerprint)

    return profiles


def _rank_profiles(
    current_fingerprint: BehaviorFingerprint,
    profiles: dict[str, DomainBehaviorProfile],
) -> list[str]:
    """Rank profiles by deterministic behavior overlap score."""

    scored_domains: list[tuple[float, int, str]] = []
    current_tokens_by_source = current_fingerprint.token_weights_by_source
    current_token_weights = current_fingerprint.merged_token_weights()

    for domain, profile in profiles.items():
        score = 0.0

        for phrase, current_weight in current_fingerprint.phrase3_weights.items():
            profile_weight = profile.phrase3_weights.get(phrase)
            if profile_weight:
                score += 8.0 * min(current_weight, profile_weight)

        for phrase, current_weight in current_fingerprint.phrase2_weights.items():
            profile_weight = profile.phrase2_weights.get(phrase)
            if profile_weight:
                score += 5.0 * min(current_weight, profile_weight)

        matched_sources: set[str] = set()
        strong_token_match_count = 0

        for token, current_weight in current_token_weights.items():
            profile_weight = profile.token_weights.get(token)
            if not profile_weight:
                continue

            overlap_weight = min(current_weight, profile_weight)
            token_score = 2.0 * overlap_weight
            if token in current_tokens_by_source.get("docstring_summary", {}):
                token_score += 2.0 * overlap_weight
            score += token_score

            source_names_for_token = {
                source_name
                for source_name, source_tokens in current_tokens_by_source.items()
                if token in source_tokens
            }
            matched_sources.update(source_names_for_token)
            if token_score >= 2.0:
                strong_token_match_count += 1

        if len(matched_sources) >= 2:
            score += 3.0

        if strong_token_match_count <= 1 and score < MINIMUM_USEFUL_SCORE:
            continue
        if score < MINIMUM_USEFUL_SCORE:
            continue

        scored_domains.append((score, profile.contributing_blocks, domain))

    scored_domains.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [domain for _score, _contributing_blocks, domain in scored_domains]


def _extract_docstring_summary_tokens(docstring: Any) -> list[str]:
    """Extract normalized tokens from the first behavior sentence in a docstring."""

    if not isinstance(docstring, str):
        return []

    lines = [line.strip() for line in docstring.splitlines()]
    meaningful_lines = [line for line in lines if line]
    if not meaningful_lines:
        return []

    summary_lines: list[str] = []
    for line in meaningful_lines:
        lowered_line = line.lower()
        if lowered_line in DOCSTRING_SECTION_HEADERS:
            break
        summary_lines.append(line)

    if not summary_lines:
        return []

    summary_text = " ".join(summary_lines)
    sentence_match = re.match(r"^(.*?)(?:\.\s+|\.$|$)", summary_text)
    if sentence_match:
        behavior_sentence = sentence_match.group(1).strip()
    else:
        behavior_sentence = summary_lines[0].strip()

    if not behavior_sentence:
        return []

    return _tokenize_behavior_text(behavior_sentence)


def _extract_symbol_tokens(block: dict[str, Any]) -> list[str]:
    """Extract normalized symbol tokens from block code metadata."""

    code = block.get("code")
    if not isinstance(code, dict):
        return []
    symbol = code.get("symbol")
    if not isinstance(symbol, str):
        return []
    return _normalize_tokens(tokenize_identifier(symbol))


def _extract_called_symbol_tokens(detected: dict[str, Any]) -> list[str]:
    """Extract normalized tokens from called symbol metadata."""

    called_symbols = detected.get("called_symbols", [])
    if not isinstance(called_symbols, list):
        return []

    tokens: list[str] = []
    for symbol in called_symbols:
        if not isinstance(symbol, str):
            continue
        tokens.extend(_normalize_tokens(tokenize_identifier(symbol)))
    return tokens


def _extract_raised_exception_tokens(detected: dict[str, Any]) -> list[str]:
    """Extract normalized tokens from raised exception metadata."""

    raised_exceptions = detected.get("raised_exceptions", [])
    if not isinstance(raised_exceptions, list):
        return []

    tokens: list[str] = []
    for exception_name in raised_exceptions:
        if not isinstance(exception_name, str):
            continue
        tokens.extend(_normalize_tokens(tokenize_identifier(exception_name)))
    return tokens


def _extract_signature_parameter_tokens(signature: Any) -> list[str]:
    """Extract normalized parameter-name tokens from a callable signature string."""

    if not isinstance(signature, str) or not signature.strip():
        return []

    parameter_match = re.search(r"\((.*?)\)", signature)
    if not parameter_match:
        return []

    parameter_section = parameter_match.group(1)
    tokens: list[str] = []
    for raw_parameter in parameter_section.split(","):
        name_candidate = raw_parameter.split(":", 1)[0].split("=", 1)[0].strip()
        name_candidate = name_candidate.lstrip("*")
        if name_candidate in {"self", "cls", ""}:
            continue
        tokens.extend(_normalize_tokens(tokenize_identifier(name_candidate)))
    return tokens


def _extract_import_tokens(detected: dict[str, Any]) -> list[str]:
    """Extract normalized tokens from import metadata."""

    import_entries = detected.get("imports", [])
    if not isinstance(import_entries, list):
        return []

    tokens: list[str] = []
    for import_entry in import_entries:
        if not isinstance(import_entry, str):
            continue
        import_tail = import_entry.split(".")[-1]
        tokens.extend(_normalize_tokens(tokenize_identifier(import_tail)))
    return tokens


def _tokenize_behavior_text(text: str) -> list[str]:
    """Tokenize free behavior text while preserving action words."""

    raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)
    split_tokens: list[str] = []
    for token in raw_tokens:
        split_tokens.extend(tokenize_identifier(token))
    return _normalize_tokens(split_tokens)


def _normalize_tokens(tokens: list[str]) -> list[str]:
    """Normalize tokens and drop only structural noise words."""

    normalized: list[str] = []
    for token in tokens:
        cleaned_token = token.strip().lower()
        if not cleaned_token:
            continue
        if cleaned_token in STRUCTURAL_NOISE_WORDS:
            continue
        normalized.append(cleaned_token)
    return normalized


def _resolve_block_identity(block: dict[str, Any]) -> tuple[str, str, str]:
    """Return stable identity tuple for one block."""

    code = block.get("code", {})
    block_id = block.get("id")
    path = code.get("path") if isinstance(code, dict) else ""
    symbol = code.get("symbol") if isinstance(code, dict) else ""
    return (
        str(block_id or "").strip(),
        str(path or "").replace("\\", "/").strip(),
        str(symbol or "").strip(),
    )


def _normalize_domain(value: Any) -> str:
    """Normalize domain and reject placeholders."""

    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower().replace("-", "_")
    if not normalized:
        return ""
    if normalized in INVALID_DOMAINS:
        return ""
    return normalized
