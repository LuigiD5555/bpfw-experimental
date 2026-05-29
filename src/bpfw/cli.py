"""Terminal commands for Blueprint Framework."""

import argparse
from collections import Counter
import json
from pathlib import Path

from bpfw.runner import run_command_after_verify
from bpfw.shared.text import normalize_text_command


MVP_COMMANDS = (
    "init",
    "inspector",
    "editor",
    "planner",
    "verify",
    "run",
    "watch",
    "lock",
    "unlock",
    "status",
)


MAIN_HELP_TEXT = """Blueprint Framework

Usage:
  bpfw <command> [options]

Commands:
  init        Create or update bpfw/blueprint.yaml from the current project.
  inspector   Review code blocks and assign purpose, domain, lifecycle, and metadata.
  editor      Edit existing blueprint authority entries.
  planner     Plan authority entries before code exists.
  verify      Check blueprint.yaml against the real code.
  run         Run a command only after bpfw verify passes.
  watch       Watch project changes and print drift feedback.
  lock        Lock protected authority files.
  unlock      Unlock protected authority files.
  status      Show project authority, drift, and lock status.

Global options:
  -h, --help              Show this help message.
  --project-root PATH     Run BPFW from a specific project root.
  --json                  Print machine-readable output when supported.

Inspector:
  bpfw inspector          Open compact view.
  bpfw inspector -a       Open full view with all panels.
  bpfw inspector --all    Open full view with all panels.

Examples:
  bpfw init
  bpfw inspector
  bpfw inspector --all
  bpfw verify
  bpfw verify undeclared
  bpfw verify --all
  bpfw run -- python app.py
  bpfw watch
  bpfw status

Verify filters:
  bpfw verify [all|undeclared|missing|duplicate|secret|invalid]
  bpfw verify --all
  bpfw verify --max N
"""


class BpfwArgumentParser(argparse.ArgumentParser):
    """Show BPFW help messages in the terminal."""

    def format_help(self) -> str:
        """Show the full BPFW help screen."""

        return f"{MAIN_HELP_TEXT}\n"

    def format_usage(self) -> str:
        """Show the short command format when input is wrong."""

        return "Usage:\n  bpfw <command> [options]\n"



def build_parser() -> argparse.ArgumentParser:
    """Build the command reader for BPFW terminal commands."""

    parser = BpfwArgumentParser(prog="bpfw")
    parser.add_argument("command", choices=MVP_COMMANDS)
    parser.add_argument("subcommand", nargs="?")
    parser.add_argument("--project-root", default=".", metavar="PATH")
    parser.add_argument("--accept-scan", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force-new", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--allow-unprotected",
        action="store_true",
        help="Allow init to complete without OS authority protection.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--once", action="store_true", dest="watch_once", help=argparse.SUPPRESS)
    parser.add_argument("--debounce-ms", type=int, default=800, dest="watch_debounce_ms", help=argparse.SUPPRESS)
    parser.add_argument("-a", "--all", action="store_true", dest="inspector_all", help=argparse.SUPPRESS)
    parser.add_argument("--max", type=int, default=8, dest="verify_max_items", help=argparse.SUPPRESS)
    return parser



def resolve_cli_command(command: str, subcommand: str | None) -> str:
    """Choose the engine command for the words typed by the user."""

    normalized_command = normalize_text_command(command)
    normalized_subcommand = normalize_text_command(subcommand) if subcommand is not None else None

    if normalized_command == "lock":
        if normalized_subcommand is not None:
            raise ValueError("lock does not accept subcommands")
        return "lock"
    if normalized_command == "unlock":
        if normalized_subcommand is not None and normalized_subcommand != "blueprint":
            raise ValueError("unlock only supports blueprint resource in MVP. Usage: bpfw unlock [blueprint]")
        return "unlock"
    if normalized_command == "inspector":
        if normalized_subcommand is not None:
            raise ValueError("inspector does not accept subcommands")
        return "inspector"
    if normalized_command == "editor":
        if normalized_subcommand is not None:
            raise ValueError("editor does not accept subcommands")
        return "editor"
    if normalized_command == "planner":
        if normalized_subcommand is not None:
            raise ValueError("planner does not accept subcommands")
        return "planner"
    if normalized_command == "init":
        if normalized_subcommand is not None:
            raise ValueError("init does not accept subcommands")
        return "init"
    if normalized_command == "verify":
        from bpfw.reports.verify_report import VERIFY_FINDING_FILTERS

        if normalized_subcommand is not None and normalized_subcommand not in VERIFY_FINDING_FILTERS:
            valid_filters = ", ".join(sorted(VERIFY_FINDING_FILTERS))
            raise ValueError(
                f"unknown verify filter: {normalized_subcommand}. "
                f"Supported filters: {valid_filters}"
            )
        return "verify"
    if normalized_command == "run":
        return "run"
    if normalized_command == "watch":
        if normalized_subcommand is not None:
            raise ValueError("watch does not accept subcommands")
        return "watch"
    if normalized_command == "status":
        if normalized_subcommand is not None:
            raise ValueError("status does not accept subcommands")
        return "status"
    raise ValueError(f"Unknown command: {normalized_command}")


def _format_protected_resources(result: "ProtectionResult") -> str:
    """Show protected resources in terminal output."""

    lines = []
    for resource in result.protected_resources:
        lines.append(f"  {resource.path}")
    for resource in result.skipped_resources:
        lines.append(f"  {resource.path} (skipped: missing)")
    return "\n".join(lines)



def _build_payload(result) -> dict:  # noqa: ANN001
    """Convert an engine result to data that can be printed as JSON."""

    severity_rank = {"ok": 0, "info": 1, "warning": 2, "block": 3, "critical": 4}
    serialized_steps = [
        {
            "status": str(step.status).lower(),
            "message": step.message,
            "source": step.source,
            "details": step.details,
            "affected_resources": step.affected_resources,
            "suggested_actions": step.suggested_actions,
        }
        for step in result.steps
    ]
    if serialized_steps:
        primary_step = max(serialized_steps, key=lambda step: severity_rank.get(step["status"], 0))
        primary_message = primary_step["message"]
    else:
        primary_step = None
        primary_message = ""

    return {
        "command_name": result.command_name,
        "status": str(result.status).lower(),
        "message": primary_message,
        "primary_step": primary_step,
        "steps": serialized_steps,
    }



def _print_human(payload: dict) -> None:
    """Print readable command output."""

    # verify: print OK on success, error message otherwise
    if payload["command_name"] == "verify":
        if payload.get("status") in {"ok", "info", "warning"}:
            print("OK")
            return
        if payload.get("message"):
            print(payload["message"])
            return
        print(payload.get("status", "").upper())
        return

    # init: print message directly
    if payload["command_name"] == "init":
        if payload["message"]:
            print(payload["message"])
        return

    if payload["command_name"] == "status":
        details = payload.get("primary_step", {}).get("details", {})
        print("BPFW STATUS")
        print(f"  lock: {details.get('lock', 'unknown')}")
        print(f"  blueprint: {details.get('blueprint_state', 'unknown')}")
        print(f"  drift: {details.get('drift_state', 'unknown')}")
        print(f"  status: {details.get('status_state', 'unknown')}")
        return

    if payload["command_name"] in {"inspector", "editor", "planner"} and not payload["message"]:
        return

    # lock, unlock, inspector, editor, planner: print message directly
    if payload["message"]:
        print(payload["message"])
        return

    print(payload.get("status", "").upper())


def _run_drift_manager_preflight(project_root: Path, command_name: str) -> int:
    """Print a non-blocking drift preflight summary for interactive commands."""

    from bpfw.integrations.diff.review import DiffReviewService

    snapshot = DiffReviewService(project_root=project_root).load()
    if not snapshot.items:
        return 0

    kind_counts = Counter(item.kind.value for item in snapshot.items)
    top_kinds = ", ".join(
        f"{kind}={count}"
        for kind, count in kind_counts.most_common(3)
    )

    print(f"Drift detected before '{command_name}': continuing with warning.")
    print(f"Drift preflight: total={len(snapshot.items)} top={top_kinds}")
    print("Use 'bpfw status' to inspect drift summary before resolving items in editor/inspector.")
    return 0


def _print_status_drift_preview(project_root: Path, show_all: bool) -> None:
    """Print drift findings preview for status without blocking execution."""

    from bpfw.integrations.diff.review import DiffReviewService

    snapshot = DiffReviewService(project_root=project_root).load()
    if not snapshot.items:
        print("Drift preview: no drift items found.")
        return

    print(f"Drift preview: {len(snapshot.items)} item(s) detected.")
    max_items = len(snapshot.items) if show_all else 8
    for item in snapshot.items[:max_items]:
        print(f"  - [{item.kind.value}] {item.reason}")
    remaining = len(snapshot.items) - max_items
    if remaining > 0:
        print(f"  - ... {remaining} more drift item(s)")


def _synchronize_authority_layout_for_status(project_root: Path) -> None:
    """Synchronize authority shards mechanically before rendering status."""

    from bpfw.core.authority import AuthorityRepository
    from bpfw.core.catalog.access_control import (
        authorize_blueprint_writes_for_tool,
        authorize_temporary_blueprint_unlock_for_tool,
    )
    from bpfw.core.errors import BlueprintLockedError

    try:
        repository = AuthorityRepository(project_root=project_root)
        document = repository.load()
    except FileNotFoundError:
        return
    except Exception as error:
        print(f"Shard sync skipped: could not load authority ({error}).")
        return

    try:
        with authorize_blueprint_writes_for_tool("status"):
            with authorize_temporary_blueprint_unlock_for_tool("status"):
                save_result = repository.save(document)
    except BlueprintLockedError as error:
        print(f"Shard sync skipped: {error}")
        return
    except Exception as error:
        print(f"Shard sync skipped: {error}")
        return

    if not save_result.created_shards and not save_result.removed_shards:
        print("Shard sync: no layout changes.")
        return

    print(
        "Shard sync:"
        f" created={len(save_result.created_shards)}"
        f" removed={len(save_result.removed_shards)}"
    )


def main() -> int:
    """Run the BPFW terminal command."""

    parser = build_parser()
    parsed_arguments, remaining_arguments = parser.parse_known_args()

    try:
        normalized_command = resolve_cli_command(
            command=parsed_arguments.command,
            subcommand=parsed_arguments.subcommand,
        )
    except ValueError as error:
        parser.error(str(error))

    # init is handled directly by the catalog writer
    if normalized_command == "init":
        from bpfw.core.catalog.writer import run_init
        from bpfw.core.protection.runtime_lease import runtime_blueprint_write_lease

        project_root = Path(parsed_arguments.project_root).resolve()
        try:
            with runtime_blueprint_write_lease(project_root=project_root, tool_name="init"):
                _success, message, exit_code = run_init(
                    project_root=project_root,
                    allow_unprotected=parsed_arguments.allow_unprotected,
                )
        except Exception as error:
            print(f"Init error: {error}")
            return 1
        print(message)
        return exit_code

    # verify is handled directly by the catalog verify pipeline
    if normalized_command == "verify":
        from bpfw.core.catalog.verify import run_verify
        from bpfw.reports.verify_report import VERIFY_FINDING_FILTERS, render_verify_report

        project_root = Path(parsed_arguments.project_root).resolve()
        selected_filter = normalize_text_command(parsed_arguments.subcommand) if parsed_arguments.subcommand else None
        selected_codes = None if selected_filter in {None, "all"} else sorted(VERIFY_FINDING_FILTERS[selected_filter])
        max_items = 0 if parsed_arguments.inspector_all else parsed_arguments.verify_max_items
        report, exit_code = run_verify(project_root=project_root)
        output = render_verify_report(
            report,
            finding_codes=selected_codes,
            max_items_per_group=max_items,
        )
        print(output)
        return exit_code

    # run is handled directly by verification gate plus subprocess execution
    if normalized_command == "run":
        project_root = Path(parsed_arguments.project_root).resolve()
        command: list[str] = []
        if parsed_arguments.subcommand is not None:
            command.append(parsed_arguments.subcommand)
        command.extend(remaining_arguments)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            print("Missing command.\n")
            print("Usage:")
            print("  bpfw run -- <command>")
            return 1
        return run_command_after_verify(project_root=project_root, command=command)

    if remaining_arguments:
        parser.error(f"unrecognized arguments: {' '.join(remaining_arguments)}")

    # watch is handled directly by the lightweight watch service
    if normalized_command == "watch":
        from bpfw.watch import WatchDependencyError, run_watch

        project_root = Path(parsed_arguments.project_root).resolve()
        try:
            return run_watch(
                project_root=project_root,
                debounce_ms=parsed_arguments.watch_debounce_ms,
                once=parsed_arguments.watch_once,
            )
        except WatchDependencyError as error:
            print(str(error))
            return 1

    # status is handled directly by the status report pipeline
    if normalized_command == "status":
        from bpfw.reports.status_report import run_status

        project_root = Path(parsed_arguments.project_root).resolve()
        _synchronize_authority_layout_for_status(project_root=project_root)
        _print_status_drift_preview(
            project_root=project_root,
            show_all=parsed_arguments.inspector_all,
        )
        output, exit_code = run_status(project_root=project_root)
        print(output)
        return exit_code

    # lock is handled directly by the protection authority
    if normalized_command == "lock":
        from bpfw.core.catalog.paths import CANONICAL_BLUEPRINT_FILE
        from bpfw.core.protection.authority import MISSING_BLUEPRINT_STATUS, lock_authority

        project_root = Path(parsed_arguments.project_root).resolve()
        lock_result = lock_authority(project_root=project_root)
        if lock_result.status == MISSING_BLUEPRINT_STATUS:
            print(
                "BPFW blueprint does not exist:\n"
                f"  {CANONICAL_BLUEPRINT_FILE}\n\n"
                "Run bpfw init first."
            )
            return 1
        if lock_result.status == "unsupported":
            print(
                "BPFW could not lock authority resources.\n\n"
                "Protected:\n"
                f"{_format_protected_resources(result=lock_result)}\n\n"
                "Status:\n"
                "  UNSUPPORTED\n\n"
                "Try running from a terminal where file permissions can be changed."
            )
            return 1
        if lock_result.status == "degraded":
            print(
                "Blueprint partially locked.\n\n"
                "Protected:\n"
                f"{_format_protected_resources(result=lock_result)}\n\n"
                "Status:\n"
                "  DEGRADED\n\n"
                "Reason:\n"
                "  Strong OS protection is unavailable, but read-only protection was applied."
            )
            return 0
        if lock_result.status != "locked":
            print(
                "BPFW authority protection is incomplete.\n\n"
                "Protected:\n"
                f"{_format_protected_resources(result=lock_result)}\n\n"
                "Status:\n"
                f"  {lock_result.status.upper()}"
            )
            return 1
        print(
            "Blueprint locked.\n\n"
            "Protected:\n"
            f"{_format_protected_resources(result=lock_result)}\n\n"
            "Status:\n"
            "  LOCKED"
        )
        return 0

    # unlock is handled directly by the protection authority
    if normalized_command == "unlock":
        from bpfw.core.catalog.paths import CANONICAL_BLUEPRINT_FILE
        from bpfw.core.protection.authority import (
            MISSING_BLUEPRINT_STATUS,
            get_authority_protection_status,
            unlock_authority,
        )

        project_root = Path(parsed_arguments.project_root).resolve()
        current_lock_state = get_authority_protection_status(project_root=project_root).status
        if current_lock_state == MISSING_BLUEPRINT_STATUS:
            print(
                "BPFW blueprint does not exist:\n"
                f"  {CANONICAL_BLUEPRINT_FILE}\n\n"
                "Run bpfw init first."
            )
            return 1
        unlock_result = unlock_authority(project_root=project_root)
        if unlock_result.status == "unsupported":
            print(
                "BPFW could not unlock authority resources.\n\n"
                "Protected:\n"
                f"{_format_protected_resources(result=unlock_result)}\n\n"
                "Status:\n"
                "  UNSUPPORTED\n\n"
                "Try running from a terminal where file permissions can be changed."
            )
            return 1
        print(
            "Blueprint unlocked.\n\n"
            "Protected:\n"
            f"{_format_protected_resources(result=unlock_result)}\n\n"
            "Status:\n"
            f"  {unlock_result.status.upper()}\n\n"
            "Reminder:\n"
            "  Run bpfw verify before locking again."
        )
        return 0

    from bpfw.core.engine import BlueprintEngine, build_command

    engine = BlueprintEngine()
    command_arguments: dict[str, str] = {}

    if normalized_command == "inspector" and parsed_arguments.inspector_all:
        command_arguments["view"] = "all"

    if normalized_command in {"inspector", "editor", "planner"}:
        project_root = Path(parsed_arguments.project_root).resolve()
        _synchronize_authority_layout_for_status(project_root=project_root)
        _run_drift_manager_preflight(
            project_root=project_root,
            command_name=normalized_command,
        )

    result = engine.run(
        build_command(
            command_name=normalized_command,
            project_root=Path(parsed_arguments.project_root).resolve(),
            arguments=command_arguments,
        )
    )
    payload = _build_payload(result)

    if parsed_arguments.as_json:
        print(json.dumps(payload, indent=2))
    else:
        _print_human(payload)

    return 0 if result.status in {"OK", "INFO", "WARNING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
