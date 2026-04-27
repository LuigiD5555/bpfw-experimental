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
    return parser



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
    payload = {
        "command_name": result.command_name,
        "status": result.status,
        "steps": [
            {
                "status": step.status,
                "message": step.message,
                "source": step.source,
                "details": step.details,
                "affected_resources": step.affected_resources,
                "suggested_actions": step.suggested_actions,
            }
            for step in result.steps
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if result.status in {"OK", "INFO", "WARNING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
