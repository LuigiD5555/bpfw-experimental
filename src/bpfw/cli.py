"""Command line interface for Blueprint Framework — MVP Catalog Mode."""

import argparse
import json
from pathlib import Path

from bpfw.core.engine import BlueprintEngine, build_command
from bpfw.enforcement.ci import ci_exit_code, render_ci_report


MVP_COMMANDS = (
    "init",
    "wizard",
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
    parser.add_argument("--scope", default="")
    parser.add_argument("--operation", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--ttl", default="10m")
    parser.add_argument("--accept-scan", action="store_true")
    parser.add_argument("--force-new", action="store_true")
    parser.add_argument("--ci", action="store_true", dest="ci_mode")
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--watch", action="store_true", dest="watch_mode")
    parser.add_argument("--no-os-lock", action="store_true", dest="no_os_lock")
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
    if command == "wizard":
        if subcommand is not None:
            raise ValueError("wizard does not accept subcommands")
        return "wizard"
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
        print(f"  lifecycle: {details.get('lifecycle_state', 'unknown')}")
        return

    # lock, unlock, wizard: print message directly
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

    engine = BlueprintEngine()
    command_arguments: dict[str, str] = {}

    # init flags
    if normalized_command == "init":
        if parsed_arguments.accept_scan:
            command_arguments["accept_scan"] = "true"
        if parsed_arguments.force_new:
            command_arguments["force_new"] = "true"
        if parsed_arguments.watch_mode:
            command_arguments["watch"] = "true"
        if parsed_arguments.no_os_lock:
            command_arguments["no_os_lock"] = "true"

    # verify flags
    if normalized_command == "verify":
        if parsed_arguments.ci_mode:
            command_arguments["ci"] = "true"
        if parsed_arguments.diagnostic:
            command_arguments["diagnostic"] = "true"

    # unlock args — resource comes from subcommand (2nd positional)
    if normalized_command == "unlock":
        command_arguments["resource_id"] = parsed_arguments.subcommand or "blueprint"
        command_arguments["scope"] = parsed_arguments.scope
        command_arguments["operation"] = parsed_arguments.operation
        command_arguments["reason"] = parsed_arguments.reason
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
        if normalized_command == "verify" and parsed_arguments.ci_mode:
            print(render_ci_report(payload=payload))

    if normalized_command == "verify" and parsed_arguments.ci_mode:
        return ci_exit_code(payload=payload)
    return 0 if result.status in {"OK", "INFO", "WARNING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
