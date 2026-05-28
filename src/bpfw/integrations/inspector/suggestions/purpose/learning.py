"""PURPOSE purpose-specific incremental learning storage
DOMAIN  purpose suggestions
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

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


def learning_enabled() -> bool:
    """PURPOSE check whether purpose learning is enabled
    DOMAIN  purpose suggestions
    """

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("BPFW_LEARNING_MODE", "on").lower() != "off"


def record_purpose_phrase(text: str, increment: int = 1) -> None:
    """PURPOSE record one accepted purpose phrase
    DOMAIN  purpose suggestions
    """

    normalized = _normalize_phrase(text)
    if not normalized or not learning_enabled():
        return
    _update_counter(section="purpose_phrase_counts", key=normalized, increment=increment)


def get_learned_purposes() -> list[str]:
    """PURPOSE get learned purpose phrases in stable storage order
    DOMAIN  purpose suggestions
    """

    if not learning_enabled():
        return []
    data = _read_learning_data()
    bucket = data.get("purpose_phrase_counts", {})
    if not isinstance(bucket, dict):
        return []
    return [str(key) for key in bucket.keys()]


def _read_learning_data() -> dict[str, Any]:
    """PURPOSE read purpose learning data from disk
        DOMAIN  purpose suggestions

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
    """PURPOSE write purpose learning data to disk safely
        DOMAIN  purpose suggestions

    """

    LEARNING_ROOT.mkdir(parents=True, exist_ok=True)
    temp_path = LEARNING_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(LEARNING_PATH)


def _update_counter(section: str, key: str, increment: int) -> None:
    """PURPOSE update one named counter bucket
    DOMAIN  purpose suggestions
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
    """PURPOSE keep only top-N entries by count
    DOMAIN  purpose suggestions
    """

    if len(bucket) <= limit:
        return
    ordered = sorted(((key, _to_int(value)) for key, value in bucket.items()), key=lambda item: item[1], reverse=True)
    bucket.clear()
    for key, value in ordered[:limit]:
        bucket[key] = value


def _empty_learning_data() -> dict[str, Any]:
    """PURPOSE get an empty purpose learning data
        DOMAIN  purpose suggestions

    """

    return {
        "version": LEARNING_VERSION,
        "updated_at": None,
        "purpose_phrase_counts": {},
    }


def _to_int(value: Any) -> int:
    """PURPOSE convert a value to int
    DOMAIN  purpose suggestions
    """

    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_phrase(text: str) -> str:
    """PURPOSE clean purpose phrase text for storage
    DOMAIN  purpose suggestions
    """

    normalized = " ".join(str(text).strip().lower().split())
    tokens = [token for token in normalized.split() if len(token) >= MIN_TOKEN_LENGTH]
    if not tokens:
        return ""
    if all(token in IGNORED_TOKENS for token in tokens):
        return ""
    return " ".join(tokens)
