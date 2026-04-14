"""Compatibility wrappers for catalog guard state file operations."""

import json
import tempfile
from pathlib import Path

from bpfw.catalog.state_file import (
    CatalogGuardInvalidStatePayloadError,
    CatalogGuardStateDecodeError,
    CatalogGuardStateFileNotFoundError,
)
from tools.catalog_protection.catalog_paths import get_repo_root

_VALID_STATUSES = {"locked", "unlocked", "relocking", "error"}
_REQUIRED_FIELDS = {"status", "opened_at", "watcher_active", "last_event", "last_error"}
_JSON_SAFE_TYPES = (str, bool, int, float, type(None))


def get_state_file_path() -> Path:
    return get_repo_root() / ".catalog" / "lockstate.json"


def validate_state_payload(state: dict[str, object]) -> None:
    missing = _REQUIRED_FIELDS - state.keys()
    if missing:
        raise CatalogGuardInvalidStatePayloadError(f"missing required fields: {missing}")
    status = state["status"]
    if status not in _VALID_STATUSES:
        raise CatalogGuardInvalidStatePayloadError(
            f"unknown status {status!r}; must be one of {_VALID_STATUSES}"
        )


def _assert_json_safe_values(state: dict[str, object]) -> None:
    for field, value in state.items():
        if not isinstance(value, _JSON_SAFE_TYPES):
            raise CatalogGuardInvalidStatePayloadError(
                f"field {field!r} has non-JSON-safe type {type(value).__name__!r}"
            )


def write_state_file(state: dict[str, object]) -> None:
    validate_state_payload(state)
    _assert_json_safe_values(state)
    state_path = get_state_file_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(state, indent=2)

    tmp_path: Path | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=state_path.parent,
            prefix=".lockstate_",
            suffix=".tmp",
        )
        tmp_path = Path(temp_name)
        with open(descriptor, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(encoded)
        tmp_path.replace(state_path)
        tmp_path = None
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def read_state_file() -> dict[str, object]:
    state_path = get_state_file_path()
    if not state_path.exists():
        raise CatalogGuardStateFileNotFoundError(state_path)
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as decode_error:
        raise CatalogGuardStateDecodeError(state_path, decode_error) from decode_error

    if not isinstance(raw, dict):
        raise CatalogGuardInvalidStatePayloadError(
            f"expected JSON object, got {type(raw).__name__}"
        )
    validate_state_payload(raw)
    return raw
