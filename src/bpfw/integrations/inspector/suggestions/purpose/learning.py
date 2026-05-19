"""Purpose-specific incremental learning storage."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
import re

LEARNING_VERSION = 1
LEARNING_ROOT = Path.home() / ".bpfw"
LEARNING_PATH = LEARNING_ROOT / "inspector_purpose_learning_v1.json"
MAX_ENTRIES_PER_SECTION = 400
MIN_TOKEN_LENGTH = 3
IGNORED_TOKENS = frozenset(
    {
        "the",
        "and",
        "for",
        "from",
        "with",
        "this",
        "that",
        "none",
        "null",
        "true",
        "false",
    }
)
COMPOUND_ERROR_SUFFIXES = ("error", "exception")
COMPOUND_ERROR_QUALIFIERS = (
    "missing",
    "invalid",
    "locked",
    "protected",
    "duplicate",
    "unknown",
    "unauthorized",
    "forbidden",
)


def learning_enabled() -> bool:
    """Return whether purpose learning is enabled.

    Returns:
        True when learning storage is enabled for the current process.
    """

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("BPFW_LEARNING_MODE", "on").lower() != "off"


def record_purpose_phrase(text: str, increment: int = 1) -> None:
    """Record one accepted purpose phrase.

    Args:
        text: Accepted purpose phrase text.
        increment: Counter increment amount.
    """

    normalized = _normalize_phrase(text)
    if not normalized or not learning_enabled():
        return
    _update_counter(section="purpose_phrase_counts", key=normalized, increment=increment)


def get_top_learned_purposes(limit: int = 20) -> list[tuple[str, int]]:
    """Return top learned purpose phrases with counts.

    Args:
        limit: Maximum number of records to return.

    Returns:
        Ordered list of ``(phrase, count)`` pairs.
    """

    if not learning_enabled():
        return []
    data = _read_learning_data()
    bucket = data.get("purpose_phrase_counts", {})
    if not isinstance(bucket, dict):
        return []
    ordered = sorted(((str(key), _to_int(value)) for key, value in bucket.items()), key=lambda item: item[1], reverse=True)
    return ordered[:max(1, limit)]


def score_phrase_context_match(phrase: str, context_text: str) -> int:
    """Score token overlap between one phrase and a context string.

    Args:
        phrase: Learned phrase candidate.
        context_text: Current block context text.

    Returns:
        Count of overlapping normalized tokens.
    """

    phrase_tokens = set(_tokenize_simple(phrase))
    context_tokens = set(_tokenize_simple(context_text))
    if not phrase_tokens or not context_tokens:
        return 0
    return len(phrase_tokens & context_tokens)


def _read_learning_data() -> dict[str, Any]:
    """Read purpose learning payload from disk.

    Returns:
        Parsed payload dictionary.
    """

    try:
        raw = LEARNING_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty_learning_data()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _empty_learning_data()
    if not isinstance(payload, dict):
        return _empty_learning_data()
    return payload


def _write_learning_data(payload: dict[str, Any]) -> None:
    """Write purpose learning payload to disk atomically.

    Args:
        payload: Purpose learning payload.
    """

    LEARNING_ROOT.mkdir(parents=True, exist_ok=True)
    temp_path = LEARNING_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(LEARNING_PATH)


def _update_counter(section: str, key: str, increment: int) -> None:
    """Update one named counter bucket.

    Args:
        section: Bucket section name.
        key: Counter key.
        increment: Counter increment amount.
    """

    payload = _read_learning_data()
    bucket = payload.get(section)
    if not isinstance(bucket, dict):
        bucket = {}
        payload[section] = bucket
    current = _to_int(bucket.get(key, 0))
    bucket[key] = current + max(1, increment)
    _trim_bucket(bucket, MAX_ENTRIES_PER_SECTION)
    payload["version"] = LEARNING_VERSION
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_learning_data(payload)


def _trim_bucket(bucket: dict[str, Any], limit: int) -> None:
    """Keep only top-N entries by count.

    Args:
        bucket: Mutable bucket dictionary.
        limit: Maximum entry count.
    """

    if len(bucket) <= limit:
        return
    ordered = sorted(((key, _to_int(value)) for key, value in bucket.items()), key=lambda item: item[1], reverse=True)
    bucket.clear()
    for key, value in ordered[:limit]:
        bucket[key] = value


def _empty_learning_data() -> dict[str, Any]:
    """Return an empty purpose learning payload.

    Returns:
        Empty payload dictionary.
    """

    return {
        "version": LEARNING_VERSION,
        "updated_at": None,
        "purpose_phrase_counts": {},
    }


def _to_int(value: Any) -> int:
    """Convert a value to int safely.

    Args:
        value: Input value.

    Returns:
        Converted integer or zero when conversion fails.
    """

    try:
        return int(value)
    except TypeError:
        return 0
    except ValueError:
        return 0


def _normalize_phrase(text: str) -> str:
    """Normalize purpose phrase text for storage.

    Args:
        text: Raw phrase text.

    Returns:
        Normalized phrase text or empty string.
    """

    normalized = " ".join(str(text).strip().lower().split())
    tokens = [token for token in normalized.split() if len(token) >= MIN_TOKEN_LENGTH]
    if not tokens:
        return ""
    if all(token in IGNORED_TOKENS for token in tokens):
        return ""
    return " ".join(tokens)


def _tokenize_simple(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric words.

    Args:
        text: Raw text.

    Returns:
        Token list for overlap matching.
    """

    tokens: list[str] = []
    for raw_token in re.findall(r"[A-Za-z][A-Za-z0-9]*", text):
        normalized_token = raw_token.lower()
        tokens.extend(_expand_compound_token(normalized_token))
    return tokens


def _expand_compound_token(token: str) -> list[str]:
    """Expand glued tokens such as ``blueprintmissingerror``.

    Args:
        token: Normalized token.

    Returns:
        Expanded token list.
    """

    for suffix in COMPOUND_ERROR_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix):
            root = token[: -len(suffix)]
            expanded_root = _split_known_qualifier(root)
            return expanded_root + [suffix]
    return [token]


def _split_known_qualifier(root: str) -> list[str]:
    """Split known error qualifiers from root tokens.

    Args:
        root: Root token without error suffix.

    Returns:
        Split token list.
    """

    for qualifier in COMPOUND_ERROR_QUALIFIERS:
        if root.endswith(qualifier) and len(root) > len(qualifier):
            head = root[: -len(qualifier)]
            if len(head) >= MIN_TOKEN_LENGTH:
                return [head, qualifier]
            return [qualifier]
    return [root]
