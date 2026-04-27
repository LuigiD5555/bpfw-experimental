"""Command line interface for Blueprint Framework."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bpfw.core.engine import BlueprintEngine, build_command


SUPPORTED_COMMANDS = ("verify", "discover", "review", "apply", "status")



def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for base BPFW commands."""

    parser = argparse.ArgumentParser(prog="bpfw")
    parser.add_argument("command", choices=SUPPORTED_COMMANDS)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser



def _build_payload(result) -> dict:  # noqa: ANN001
    return {
        "command_name": result.command_name,
        "status": str(result.status).lower(),
        "message": result.steps[0].message if result.steps else "",
        "steps": [
            {
                "status": str(step.status).lower(),
                "message": step.message,
                "source": step.source,
                "details": step.details,
                "affected_resources": step.affected_resources,
                "suggested_actions": step.suggested_actions,
            }
            for step in result.steps
        ],
    }



def _print_human(payload: dict) -> None:
    print(f"Command: {payload['command_name']}")
    print(f"Status: {payload['status'].upper()}")
    if payload["message"]:
        print(f"Message: {payload['message']}")

    first_step = payload["steps"][0] if payload["steps"] else None
    if first_step is None:
        return

    details = first_step.get("details", {})
    if "error_code" in details:
        print(f"Error Code: {details['error_code']}")
    if "blueprint_path" in details:
        print(f"Blueprint: {details['blueprint_path']}")
    if "responsibility_count" in details:
        print(f"Responsibilities: {details['responsibility_count']}")

    affected_resources = first_step.get("affected_resources", [])
    if affected_resources:
        print(f"Affected File: {affected_resources[0]}")

    suggested_actions = first_step.get("suggested_actions", [])
    if suggested_actions:
        print(f"Recommendation: {suggested_actions[0]}")



def main() -> int:
    """Entry point for Prompt 0 executable scaffold."""

    parser = build_parser()
    parsed_arguments = parser.parse_args()

    engine = BlueprintEngine()
    result = engine.run(
        build_command(
            command_name=parsed_arguments.command,
            project_root=Path(parsed_arguments.project_root).resolve(),
            arguments={},
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
