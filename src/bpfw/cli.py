"""Command line interface for Blueprint Framework."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bpfw.core.engine import BlueprintEngine, build_command


SUPPORTED_COMMANDS = (
    "verify",
    "discover",
    "review",
    "apply",
    "status",
    "architecture",
    "composition",
    "runtime",
    "wiring",
)



def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for base BPFW commands."""

    parser = argparse.ArgumentParser(prog="bpfw")
    parser.add_argument("command", choices=SUPPORTED_COMMANDS)
    parser.add_argument("subcommand", nargs="?")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser



def normalize_command(command: str, subcommand: str | None) -> str:
    """Map CLI tokens into engine command names."""

    if command == "architecture":
        if subcommand != "check":
            raise ValueError("architecture command requires subcommand `check`")
        return "architecture_check"
    if command == "composition":
        if subcommand != "check":
            raise ValueError("composition command requires subcommand `check`")
        return "composition_check"
    if command == "runtime":
        if subcommand != "snapshot":
            raise ValueError("runtime command requires subcommand `snapshot`")
        return "runtime_snapshot"
    if command == "wiring":
        if subcommand != "check":
            raise ValueError("wiring command requires subcommand `check`")
        return "wiring_check"

    if subcommand is not None:
        raise ValueError(f"Command `{command}` does not accept subcommands")
    return command



def _build_payload(result) -> dict:  # noqa: ANN001
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
    print(f"Command: {payload['command_name']}")
    print(f"Status: {payload['status'].upper()}")
    if payload["message"]:
        print(f"Message: {payload['message']}")

    primary_step = payload.get("primary_step")
    if primary_step is None:
        return

    details = primary_step.get("details", {})
    if "error_code" in details:
        print(f"Error Code: {details['error_code']}")
    if "blueprint_path" in details:
        print(f"Blueprint: {details['blueprint_path']}")
    if "responsibility_count" in details:
        print(f"Responsibilities: {details['responsibility_count']}")
    if "architecture_profile_id" in details and details["architecture_profile_id"]:
        print(f"Architecture Profile: {details['architecture_profile_id']}")
    if "runtime_snapshot_human" in details:
        print("Runtime Snapshot:")
        print(details["runtime_snapshot_human"])
    if "active_bindings_count" in details:
        print(f"Active Bindings: {details['active_bindings_count']}")
    if "warning_count" in details:
        print(f"Runtime Warnings: {details['warning_count']}")
    if "wiring_issue_count" in details:
        print(f"Wiring Issues: {details['wiring_issue_count']}")
    if "duplication_total_count" in details:
        print(f"Duplication Findings: {details['duplication_total_count']}")
    if "duplication_block_count" in details:
        print(f"Duplication Blocks: {details['duplication_block_count']}")
    if "duplication_warning_count" in details:
        print(f"Duplication Warnings: {details['duplication_warning_count']}")
    if "duplication_findings_human" in details:
        print("Duplication Summary:")
        print(details["duplication_findings_human"])
    if "blueprint_mode_enabled" in details:
        print(f"Blueprint Mode Enabled: {details['blueprint_mode_enabled']}")
    if "blueprint_mode_operation_count" in details:
        print(f"Blueprint Mode Operations: {details['blueprint_mode_operation_count']}")
    if "blueprint_mode_issue_count" in details:
        print(f"Blueprint Mode Issues: {details['blueprint_mode_issue_count']}")

    affected_resources = primary_step.get("affected_resources", [])
    if affected_resources:
        print(f"Affected File: {affected_resources[0]}")

    suggested_actions = primary_step.get("suggested_actions", [])
    if suggested_actions:
        print(f"Recommendation: {suggested_actions[0]}")



def main() -> int:
    """Entry point for executable scaffold commands."""

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
    result = engine.run(
        build_command(
            command_name=normalized_command,
            project_root=Path(parsed_arguments.project_root).resolve(),
            arguments={},
        )
    )
    payload = _build_payload(result)
    if parsed_arguments.as_json:
        primary_step = payload.get("primary_step") or {}
        details = primary_step.get("details", {})
        runtime_snapshot_json = details.get("runtime_snapshot_json")
        if normalized_command == "runtime_snapshot" and isinstance(runtime_snapshot_json, str):
            print(runtime_snapshot_json)
        else:
            print(json.dumps(payload, indent=2))
    else:
        _print_human(payload)
    return 0 if result.status in {"OK", "INFO", "WARNING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
