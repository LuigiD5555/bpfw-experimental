"""Optional startup enforcement checks for runtime bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpfw.core.engine import BlueprintEngine, build_command
from bpfw.core.result import ResultStatus


@dataclass(slots=True)
class StartupCheckResult:
    """Startup check outcome for host applications."""

    status: str
    should_block: bool
    report: str


def run_startup_check(project_root: Path, fail_on: set[str] | None = None) -> StartupCheckResult:
    """Run optional startup enforcement.

    Default behavior only blocks on critical findings.
    """

    effective_fail_on = fail_on or {"critical"}
    normalized_fail_on = {item.upper() for item in effective_fail_on}

    engine = BlueprintEngine()
    result = engine.run(build_command(command_name="verify", project_root=project_root, arguments={}))
    should_block = result.status.name in normalized_fail_on

    lines = [
        "Startup Enforcement:",
        f"Status: {result.status.value}",
        f"Block Thresholds: {', '.join(sorted(normalized_fail_on))}",
        f"Startup Gate: {'BLOCK' if should_block else 'ALLOW'}",
    ]

    if result.steps:
        primary_step = result.steps[-1]
        for step in result.steps:
            if _status_priority(step.status) >= _status_priority(primary_step.status):
                primary_step = step
        lines.append(f"Primary Finding: {primary_step.message}")

    return StartupCheckResult(
        status=result.status.value,
        should_block=should_block,
        report="\n".join(lines),
    )


def _status_priority(status: ResultStatus) -> int:
    priorities: dict[ResultStatus, int] = {
        ResultStatus.OK: 0,
        ResultStatus.INFO: 1,
        ResultStatus.WARNING: 2,
        ResultStatus.BLOCK: 3,
        ResultStatus.CRITICAL: 4,
    }
    return priorities[status]
