"""CI enforcement helpers for BPFW verify command."""

from __future__ import annotations

from dataclasses import dataclass


_FAIL_STATUSES = {"block", "critical"}


@dataclass(slots=True)
class EnforcementSummary:
    """Aggregated severity counters for enforcement decisions."""

    total_steps: int
    warning_count: int
    block_count: int
    critical_count: int


def summarize_payload(payload: dict[str, object]) -> EnforcementSummary:
    """Count verify step severities from CLI payload."""

    steps = payload.get("steps", [])
    warning_count = 0
    block_count = 0
    critical_count = 0

    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            status = str(step.get("status", "")).lower()
            if status == "warning":
                warning_count += 1
            elif status == "block":
                block_count += 1
            elif status == "critical":
                critical_count += 1

    return EnforcementSummary(
        total_steps=len(steps) if isinstance(steps, list) else 0,
        warning_count=warning_count,
        block_count=block_count,
        critical_count=critical_count,
    )


def should_fail_ci(payload: dict[str, object]) -> bool:
    """Return True when CI gate must fail."""

    summary = summarize_payload(payload=payload)
    return summary.block_count > 0 or summary.critical_count > 0


def ci_exit_code(payload: dict[str, object]) -> int:
    """Map enforcement outcome to process exit code."""

    return 1 if should_fail_ci(payload=payload) else 0


def render_ci_report(payload: dict[str, object]) -> str:
    """Render a compact, human-readable CI report."""

    summary = summarize_payload(payload=payload)
    lines: list[str] = [
        "CI Enforcement Summary:",
        f"Total Steps: {summary.total_steps}",
        f"Warnings: {summary.warning_count}",
        f"Blocks: {summary.block_count}",
        f"Critical: {summary.critical_count}",
    ]

    failed_lines: list[str] = []
    steps = payload.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            status = str(step.get("status", "")).lower()
            if status not in _FAIL_STATUSES:
                continue
            source = str(step.get("source", "unknown"))
            message = str(step.get("message", ""))
            failed_lines.append(f"[{status.upper()}] {source}: {message}")

    if failed_lines:
        lines.append("Failing Steps:")
        lines.extend(failed_lines)

    gate_result = "FAIL" if should_fail_ci(payload=payload) else "PASS"
    lines.append(f"CI Gate: {gate_result}")
    return "\n".join(lines)
