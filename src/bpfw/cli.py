"""Command line interface for Blueprint Framework MVP Catalog Mode."""

import argparse
import json
from pathlib import Path

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.catalog.verify import run_verify
from bpfw.catalog.writer import run_init
from bpfw.runner import run_command_after_verify
from bpfw.watch import WatchDependencyError, run_watch
from bpfw.core.engine import BlueprintEngine, build_command
from bpfw.protection.authority import (
    MISSING_BLUEPRINT_STATUS,
    ProtectionResult,
    get_authority_protection_status,
    lock_authority,
    unlock_authority,
)
from bpfw.reports.status_report import run_status
from bpfw.reports.verify_report import VERIFY_FINDING_FILTERS, render_verify_report
from bpfw.shared.text import normalize_text_command
from bpfw.protection.runtime_lease import runtime_blueprint_write_lease


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
    "reshard",
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
  reshard     Reshard is no longer a public workflow. Use bpfw verify to detect drift.

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
    """Argument parser that renders the curated BPFW command help."""

    def format_help(self) -> str:
        """Return the curated top-level BPFW help text."""

        return f"{MAIN_HELP_TEXT}\n"

    def format_usage(self) -> str:
        """Return concise command usage for parser errors."""

        return "Usage:\n  bpfw <command> [options]\n"



def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for BPFW MVP commands."""

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
    """Map CLI tokens into engine command names for MVP."""

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
    if normalized_command == "reshard":
        if normalized_subcommand is not None:
            raise ValueError("reshard does not accept subcommands")
        return "reshard"

    raise ValueError(f"Unknown command: {normalized_command}")


def _format_protected_resources(result: ProtectionResult) -> str:
    """Format protected resources for CLI output."""

    lines = []
    for resource in result.protected_resources:
        lines.append(f"  {resource.path}")
    for resource in result.skipped_resources:
        lines.append(f"  {resource.path} (skipped: missing)")
    return "\n".join(lines)



def _build_payload(result) -> dict:  # noqa: ANN001
    """Serialize engine result into a JSON-friendly payload dict."""

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
    """Print human-readable output for MVP commands."""

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


def main() -> int:
    """Entry point for BPFW MVP CLI."""

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
        project_root = Path(parsed_arguments.project_root).resolve()
        output, exit_code = run_status(project_root=project_root)
        print(output)
        return exit_code

    # reshard is no longer a public workflow
    if normalized_command == "reshard":
        print(
            "Reshard is no longer a public workflow. "
            "Use bpfw verify to detect drift."
        )
        return 1

    # lock is handled directly by the protection authority
    if normalized_command == "lock":
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

    engine = BlueprintEngine()
    command_arguments: dict[str, str] = {}

    if normalized_command == "inspector" and parsed_arguments.inspector_all:
        command_arguments["view"] = "all"

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
