"""Idle-based auto-lock daemon for BPFW authority files."""

from pathlib import Path
import json
import os
import subprocess
import sys
import time
import uuid

from bpfw.core.catalog.paths import CANONICAL_BLOCKS_DIR, CANONICAL_BLUEPRINT_FILE, CANONICAL_CACHE_DIR
from bpfw.core.protection.authority import (
    BLUEPRINT_RESOURCE_TYPE,
    SHARD_RESOURCE_TYPE,
    get_authority_protection_status,
    lock_authority,
    resolve_protected_resources,
)

_DEFAULT_IDLE_SECONDS = 30.0
_DEFAULT_POLL_SECONDS = 1.0
_STATE_FILE_NAME = "autolock.json"
_LOCKED_STATES = {"locked", "degraded"}
_AUTHORITY_RESOURCE_TYPES = {BLUEPRINT_RESOURCE_TYPE, SHARD_RESOURCE_TYPE}


def _resolve_state_path(project_root: Path) -> Path:
    """Return the project-local auto-lock state file path."""

    return project_root / CANONICAL_CACHE_DIR / _STATE_FILE_NAME


def _read_state(project_root: Path) -> dict[str, object]:
    """Read the current auto-lock state file, returning an empty state on failure."""

    state_path = _resolve_state_path(project_root=project_root)
    if not state_path.exists():
        return {}

    try:
        raw_data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_data, dict):
        return {}
    return raw_data


def _write_state(project_root: Path, state: dict[str, object]) -> None:
    """Write the auto-lock state file without failing the caller on I/O errors."""

    state_path = _resolve_state_path(project_root=project_root)
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        return


def _remove_state(project_root: Path, token: str) -> None:
    """Remove the auto-lock state file when it still belongs to this daemon token."""

    state = _read_state(project_root=project_root)
    if state.get("token") != token:
        return

    state_path = _resolve_state_path(project_root=project_root)
    try:
        state_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _token_is_current(project_root: Path, token: str) -> bool:
    """Return whether a daemon token still owns the current auto-lock session."""

    return _read_state(project_root=project_root).get("token") == token


def _authority_files(project_root: Path) -> list[Path]:
    """Return blueprint authority YAML files watched for inactivity."""

    files: list[Path] = []
    blueprint_path = project_root / CANONICAL_BLUEPRINT_FILE
    if blueprint_path.exists():
        files.append(blueprint_path)

    blocks_directory = project_root / CANONICAL_BLOCKS_DIR
    if blocks_directory.exists():
        files.extend(path for path in blocks_directory.glob("*.yaml") if path.is_file())

    for resource in resolve_protected_resources(project_root=project_root):
        if resource.resource_type not in _AUTHORITY_RESOURCE_TYPES:
            continue
        files.append(resource.path)
    return sorted(set(files))


def _snapshot_authority_files(project_root: Path) -> dict[str, tuple[int, int]]:
    """Return a lightweight mtime and size snapshot for watched authority files."""

    snapshot: dict[str, tuple[int, int]] = {}
    for authority_file in _authority_files(project_root=project_root):
        try:
            file_stat = authority_file.stat()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        snapshot[authority_file.resolve().as_posix()] = (
            file_stat.st_mtime_ns,
            file_stat.st_size,
        )
    return snapshot


def _build_state(project_root: Path, token: str, idle_seconds: float, deadline: float) -> dict[str, object]:
    """Build the persisted state payload for one auto-lock session."""

    return {
        "token": token,
        "pid": os.getpid(),
        "project_root": project_root.resolve().as_posix(),
        "idle_seconds": idle_seconds,
        "deadline_monotonic": deadline,
        "updated_at": time.time(),
    }


def _run_daemon(project_root: Path, token: str, idle_seconds: float, poll_seconds: float) -> int:
    """Lock authority after no watched authority file changes for the idle window."""

    previous_snapshot = _snapshot_authority_files(project_root=project_root)
    deadline = time.monotonic() + idle_seconds
    _write_state(
        project_root=project_root,
        state=_build_state(
            project_root=project_root,
            token=token,
            idle_seconds=idle_seconds,
            deadline=deadline,
        ),
    )

    while True:
        if not _token_is_current(project_root=project_root, token=token):
            return 0

        current_status = get_authority_protection_status(project_root=project_root).status
        if current_status in _LOCKED_STATES:
            _remove_state(project_root=project_root, token=token)
            return 0

        current_snapshot = _snapshot_authority_files(project_root=project_root)
        if current_snapshot != previous_snapshot:
            previous_snapshot = current_snapshot
            deadline = time.monotonic() + idle_seconds
            _write_state(
                project_root=project_root,
                state=_build_state(
                    project_root=project_root,
                    token=token,
                    idle_seconds=idle_seconds,
                    deadline=deadline,
                ),
            )

        if time.monotonic() >= deadline:
            lock_authority(project_root=project_root)
            _remove_state(project_root=project_root, token=token)
            return 0

        time.sleep(max(0.1, poll_seconds))


def _start_autolock_after_unlock(project_root: Path, idle_seconds: float = _DEFAULT_IDLE_SECONDS) -> bool:
    """Start a detached auto-lock daemon after an explicit unlock command."""

    if os.environ.get("BPFW_DISABLE_AUTOLOCK") == "1":
        return False

    if get_authority_protection_status(project_root=project_root).status in _LOCKED_STATES:
        return False

    token = uuid.uuid4().hex
    deadline = time.monotonic() + idle_seconds
    _write_state(
        project_root=project_root,
        state=_build_state(
            project_root=project_root,
            token=token,
            idle_seconds=idle_seconds,
            deadline=deadline,
        ),
    )

    command = [
        sys.executable,
        "-m",
        "bpfw.core.protection.autolock",
        "--project-root",
        project_root.resolve().as_posix(),
        "--token",
        token,
        "--idle-seconds",
        str(idle_seconds),
        "--poll-seconds",
        str(_DEFAULT_POLL_SECONDS),
    ]

    try:
        with open(os.devnull, "rb") as stdin_file:
            with open(os.devnull, "wb") as output_file:
                subprocess.Popen(
                    command,
                    stdin=stdin_file,
                    stdout=output_file,
                    stderr=output_file,
                    start_new_session=True,
                    close_fds=True,
                )
    except OSError:
        _remove_state(project_root=project_root, token=token)
        return False
    return True


def _parse_float_argument(value: str, fallback: float) -> float:
    """Parse a positive float command argument with a safe fallback."""

    try:
        parsed_value = float(value)
    except ValueError:
        return fallback
    if parsed_value <= 0:
        return fallback
    return parsed_value


def _main(argv: list[str] | None = None) -> int:
    """Run the auto-lock daemon command-line entrypoint."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    project_root = Path.cwd()
    token = ""
    idle_seconds = _DEFAULT_IDLE_SECONDS
    poll_seconds = _DEFAULT_POLL_SECONDS

    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--project-root" and index + 1 < len(arguments):
            project_root = Path(arguments[index + 1]).resolve()
            index += 2
            continue
        if argument == "--token" and index + 1 < len(arguments):
            token = arguments[index + 1]
            index += 2
            continue
        if argument == "--idle-seconds" and index + 1 < len(arguments):
            idle_seconds = _parse_float_argument(arguments[index + 1], _DEFAULT_IDLE_SECONDS)
            index += 2
            continue
        if argument == "--poll-seconds" and index + 1 < len(arguments):
            poll_seconds = _parse_float_argument(arguments[index + 1], _DEFAULT_POLL_SECONDS)
            index += 2
            continue
        index += 1

    if not token:
        return 2

    return _run_daemon(
        project_root=project_root,
        token=token,
        idle_seconds=idle_seconds,
        poll_seconds=poll_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(_main())
