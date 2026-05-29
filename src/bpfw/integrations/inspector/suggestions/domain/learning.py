"""Domain-specific incremental learning storage."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

LEARNING_VERSION = 1
LEARNING_ROOT = Path.home() / ".bpfw"
LEARNING_PATH = LEARNING_ROOT / "inspector_domain_learning_v1.json"
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
    """Return whether domain learning is enabled.

    Returns:
        True when learning storage is enabled for the current process.
    """

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("BPFW_LEARNING_MODE", "on").lower() != "off"


def get_last_domain_for_origin(origin_key: str) -> str:
    """Return the last accepted domain recorded for one code origin.

    Args:
        origin_key: Raw origin key from domain evidence.

    Returns:
        Normalized learned domain for that origin, or an empty string.
    """

    normalized_origin = _normalize_origin(origin_key)
    if not normalized_origin or not learning_enabled():
        return ""
    data = _read_learning_data()
    bucket = data.get("domain_origin_last", {})
    if not isinstance(bucket, dict):
        return ""
    value = bucket.get(normalized_origin)
    return _normalize_domain(value) if isinstance(value, str) else ""


def record_domain_for_origin(origin_key: str, domain: str) -> None:
    """Record the last accepted domain for one code origin.

    Args:
        origin_key: Raw origin key from domain evidence.
        domain: Accepted domain value.
    """

    normalized_origin = _normalize_origin(origin_key)
    normalized_domain = _normalize_domain(domain)
    if not normalized_origin or not normalized_domain or not learning_enabled():
        return
    payload = _read_learning_data()
    bucket = payload.get("domain_origin_last")
    if not isinstance(bucket, dict):
        bucket = {}
        payload["domain_origin_last"] = bucket
    bucket[normalized_origin] = normalized_domain
    payload["version"] = LEARNING_VERSION
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_learning_data(payload)


def record_domain_value(text: str, increment: int = 1) -> None:
    """Record one accepted domain value.

    Args:
        text: Accepted domain value.
        increment: Counter increment amount.
    """

    normalized = _normalize_domain(text)
    if not normalized or not learning_enabled():
        return
    _update_counter(section="domain_counts", key=normalized, increment=increment)


def _read_learning_data() -> dict[str, Any]:
    """Read domain learning data from disk."""

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
    """Write domain learning data to disk atomically."""

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
    """Get an empty domain learning data."""

    return {
        "version": LEARNING_VERSION,
        "updated_at": None,
        "domain_counts": {},
        "domain_origin_last": {},
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


def _normalize_domain(text: str) -> str:
    """Normalize domain text for storage.

    Args:
        text: Raw domain text.

    Returns:
        Normalized domain token or empty string.
    """

    normalized = str(text).strip().lower().replace("-", "_")
    if len(normalized) < MIN_TOKEN_LENGTH:
        return ""
    if normalized in IGNORED_TOKENS:
        return ""
    if normalized in {"-", "custom", "write_custom_domain", "general"}:
        return ""
    return normalized


def _normalize_origin(text: str) -> str:
    """Normalize a code origin key for storage.

    Args:
        text: Raw origin key.

    Returns:
        Normalized origin key.
    """

    normalized = str(text).strip().lower().replace("\\", "/")
    normalized = ".".join(part for part in normalized.split(".") if part)
    normalized = "/".join(part for part in normalized.split("/") if part)
    return normalized
