"""Tests for actionable architecture diagnostics."""

from unittest.mock import patch

from bpfw.architecture.checker import Severity
from bpfw.architecture.checker import Violation
from bpfw.architecture.checker import format_violations_report


def test_format_violations_report_includes_rule_specific_guidance() -> None:
    """Violation reports should explain what failed and what to verify next."""
    report = format_violations_report(
        [
            Violation(
                category="undeclared_module",
                message="Module 'src.shadow.feature' is not declared in any responsibility.",
                severity=Severity.ERROR,
                rule_id="UM002",
            )
        ]
    )

    assert "Architecture violations found:" in report
    assert "[UM002]" in report
    assert "What to verify:" in report
    assert "Declare the module in exactly one responsibility's allowed_components" in report


def test_validate_migration_prints_actionable_report_for_architecture_failures(
    capsys,
) -> None:
    """validate_migration should surface the formatted diagnostic report."""
    from bpfw.architecture.validate_migration import main

    violation = Violation(
        category="undeclared_module",
        message="Module 'src.shadow.feature' is not declared in any responsibility.",
        severity=Severity.ERROR,
        rule_id="UM002",
    )

    with (
        patch(
            "bpfw.catalog.runtime_snapshot.load_persisted_runtime_snapshot",
            return_value=object(),
        ),
        patch(
            "bpfw.architecture.checker.run_architecture_checks",
            return_value=[violation],
        ),
    ):
        exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "What to verify:" in captured.out
    assert "Declare the module in exactly one responsibility's allowed_components" in captured.out
