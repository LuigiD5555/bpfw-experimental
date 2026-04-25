"""Visible state file for the catalog guard.

Canonical path: <repo_root>/.catalog/lockstate.json

Supported status values: locked | unlocked | relocking | error
"""

import json
import tempfile
from pathlib import Path

from bpfw.catalog.catalog_paths import get_repo_root

_VALID_STATUSES = {"locked", "unlocked", "relocking", "error"}
_REQUIRED_FIELDS = {"status", "opened_at", "watcher_active", "last_event", "last_error"}


class CatalogGuardStateFileNotFoundError(FileNotFoundError):
    """Raised when the guard state file does not exist."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Guard state file not found: {path}")


class CatalogGuardInvalidStatePayloadError(ValueError):
    """Raised when the state payload is structurally or semantically invalid."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Invalid state payload: {reason}")


class CatalogGuardStateDecodeError(ValueError):
    """Raised when the state file cannot be decoded as valid JSON."""

    def __init__(self, path: Path, cause: Exception) -> None:
        super().__init__(f"Cannot decode state file {path}: {cause}")


def get_state_file_path() -> Path:
    """Return the canonical path for the guard state file."""
    return get_repo_root() / ".catalog" / "lockstate.json"


def validate_state_payload(state: dict[str, object]) -> None:
    """Validate that *state* contains all required fields and a valid status.

    Raises:
        CatalogGuardInvalidStatePayloadError: If any required field is missing
            or the status value is not among the permitted set.
    """
    missing = _REQUIRED_FIELDS - state.keys()
    if missing:
        raise CatalogGuardInvalidStatePayloadError(
            f"missing required fields: {missing}"
        )

    status = state["status"]
    if status not in _VALID_STATUSES:
        raise CatalogGuardInvalidStatePayloadError(
            f"unknown status {status!r}; must be one of {_VALID_STATUSES}"
        )


_JSON_SAFE_TYPES = (str, bool, int, float, type(None))


def _assert_json_safe_values(state: dict[str, object]) -> None:
    """Raise CatalogGuardInvalidStatePayloadError if any value is not JSON-safe.

    Permitted value types: str, bool, int, float, None.
    """
    for field, value in state.items():
        if not isinstance(value, _JSON_SAFE_TYPES):
            raise CatalogGuardInvalidStatePayloadError(
                f"field {field!r} has non-JSON-safe type {type(value).__name__!r}"
            )


def write_state_file(state: dict[str, object]) -> None:
    """Atomically persist *state* to the canonical state file.

    Steps:
    1. Validate the payload.
    2. Create the parent directory if absent.
    3. Write to a sibling temporary file.
    4. Atomically replace the final file via Path.replace().
    5. Remove the temporary file on any failure.

    Raises:
        CatalogGuardInvalidStatePayloadError: If the payload fails validation.
    """
    validate_state_payload(state)
    _assert_json_safe_values(state)
    state_path = get_state_file_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    encoded = json.dumps(state, indent=2)
    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=state_path.parent,
            prefix=".lockstate_",
            suffix=".tmp",
        )
        tmp_path = Path(tmp_name)
        with open(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(encoded)
        tmp_path.replace(state_path)
        tmp_path = None  # replace() succeeded; no cleanup needed
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def read_state_file() -> dict[str, object]:
    """Read and return the current state from the state file.

    Raises:
        CatalogGuardStateFileNotFoundError: If the state file does not exist.
        CatalogGuardStateDecodeError: If the file content is not valid JSON.
        CatalogGuardInvalidStatePayloadError: If the parsed payload is invalid.
    """
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
