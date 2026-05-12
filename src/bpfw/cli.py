"""Command line interface for Blueprint Framework MVP Catalog Mode."""

import argparse
import json
from pathlib import Path

from bpfw.catalog.paths import CANONICAL_BLUEPRINT_FILE
from bpfw.catalog.verify import run_verify
from bpfw.catalog.writer import run_init
from bpfw.core.engine import BlueprintEngine, build_command
from bpfw.protection.authority import (
    MISSING_BLUEPRINT_STATUS,
    ProtectionResult,
    get_blueprint_lock_state,
    lock_authority,
    unlock_authority,
)
from bpfw.reports.status_report import run_status
from bpfw.reports.verify_report import render_verify_report


MVP_COMMANDS = (
    "init",
    "inspector",
    "editor",
    "planner",
    "verify",
    "lock",
    "unlock",
    "status",
)



def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for BPFW MVP commands."""

    parser = argparse.ArgumentParser(prog="bpfw")
    parser.add_argument("command", choices=MVP_COMMANDS)
    parser.add_argument("subcommand", nargs="?")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--ttl", default="10m")
    parser.add_argument("--accept-scan", action="store_true")
    parser.add_argument("--force-new", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser



def normalize_command(command: str, subcommand: str | None) -> str:
    """Map CLI tokens into engine command names for MVP."""

    if command == "lock":
        if subcommand is not None:
            raise ValueError("lock does not accept subcommands")
        return "lock"
    if command == "unlock":
        if subcommand is not None and subcommand != "blueprint":
            raise ValueError("unlock only supports blueprint resource in MVP. Usage: bpfw unlock [blueprint]")
        return "unlock"
    if command == "inspector":
        if subcommand is not None:
            raise ValueError("inspector does not accept subcommands")
        return "inspector"
    if command == "editor":
        if subcommand is not None:
            raise ValueError("editor does not accept subcommands")
        return "editor"
    if command == "planner":
        if subcommand is not None:
            raise ValueError("planner does not accept subcommands")
        return "planner"
    if command == "init":
        if subcommand is not None:
            raise ValueError("init does not accept subcommands")
        return "init"
    if command == "verify":
        if subcommand is not None:
            raise ValueError("verify does not accept subcommands")
        return "verify"
    if command == "status":
        if subcommand is not None:
            raise ValueError("status does not accept subcommands")
        return "status"

    raise ValueError(f"Unknown command: {command}")


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
    parsed_arguments = parser.parse_args()

    try:
        normalized_command = normalize_command(
            command=parsed_arguments.command,
            subcommand=parsed_arguments.subcommand,
        )
    except ValueError as error:
        parser.error(str(error))

    # init is handled directly by the catalog writer
    if normalized_command == "init":
        project_root = Path(parsed_arguments.project_root).resolve()
        _success, message, exit_code = run_init(project_root=project_root)
        print(message)
        return exit_code

    # verify is handled directly by the catalog verify pipeline
    if normalized_command == "verify":
        project_root = Path(parsed_arguments.project_root).resolve()
        report, exit_code = run_verify(project_root=project_root)
        output = render_verify_report(report)
        print(output)
        return exit_code

    # status is handled directly by the status report pipeline
    if normalized_command == "status":
        project_root = Path(parsed_arguments.project_root).resolve()
        output, exit_code = run_status(project_root=project_root)
        print(output)
        return exit_code

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
        current_lock_state = get_blueprint_lock_state(project_root=project_root)
        if current_lock_state == "unknown":
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

    # unlock keeps --ttl accepted for MVP compatibility; logical locks do not expire.
    if normalized_command == "unlock":
        command_arguments["resource_id"] = parsed_arguments.subcommand or "blueprint"
        command_arguments["ttl"] = parsed_arguments.ttl

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
