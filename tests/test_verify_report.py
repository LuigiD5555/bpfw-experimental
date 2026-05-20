from bpfw.catalog.models import VerificationReport
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding
from bpfw.reports.verify_report import render_verify_report


def test_render_verify_report_groups_blocked_findings_by_code() -> None:
    findings = [
        Finding(
            source="security",
            code="BLUEPRINT_SECRET_LIKE_VALUE",
            severity=FINDING_SEVERITY_BLOCK,
            message="The blueprint contains secret-like text.",
        ),
        Finding(
            source="security",
            code="BLUEPRINT_SECRET_LIKE_VALUE",
            severity=FINDING_SEVERITY_BLOCK,
            message="The blueprint contains secret-like text.",
        ),
        Finding(
            source="drift",
            code="MISSING_DECLARED_CODE",
            severity=FINDING_SEVERITY_BLOCK,
            message="The blueprint declares this code unit, but it was not found in the codebase.",
            path="src/demo/a.py",
            symbol="feature_a",
        ),
        Finding(
            source="drift",
            code="MISSING_DECLARED_CODE",
            severity=FINDING_SEVERITY_BLOCK,
            message="The blueprint declares this code unit, but it was not found in the codebase.",
            path="src/demo/b.py",
            symbol="feature_b",
        ),
    ]
    report = VerificationReport(
        authority_state="defined",
        allowed=False,
        findings=findings,
    )

    rendered = render_verify_report(report)

    assert "BPFW VERIFY BLOCKED" in rendered
    assert "Findings summary:" in rendered
    assert "  BLUEPRINT_SECRET_LIKE_VALUE: 2" in rendered
    assert "  MISSING_DECLARED_CODE: 2" in rendered
    assert "[BLUEPRINT_SECRET_LIKE_VALUE] count=2" in rendered
    assert "  - n/a::n/a" in rendered
    assert "[MISSING_DECLARED_CODE] count=2" in rendered
    assert "  - src/demo/a.py::feature_a" in rendered
    assert "  - src/demo/b.py::feature_b" in rendered
    assert "Execution:\n  BLOCKED" in rendered


def test_render_verify_report_limits_locations_per_group() -> None:
    findings = [
        Finding(
            source="drift",
            code="UNDECLARED_CODE",
            severity=FINDING_SEVERITY_BLOCK,
            message="This code unit exists but is not declared in bpfw/blueprint.yaml.",
            path=f"src/demo/file_{index}.py",
            symbol=f"symbol_{index}",
        )
        for index in range(10)
    ]
    report = VerificationReport(
        authority_state="defined",
        allowed=False,
        findings=findings,
    )

    rendered = render_verify_report(report)

    assert "[UNDECLARED_CODE] count=10" in rendered
    assert "  ... and 2 more" in rendered


def test_render_verify_report_applies_finding_filter() -> None:
    findings = [
        Finding(
            source="drift",
            code="UNDECLARED_CODE",
            severity=FINDING_SEVERITY_BLOCK,
            message="Undeclared unit.",
            path="src/demo/u.py",
            symbol="u",
        ),
        Finding(
            source="drift",
            code="MISSING_DECLARED_CODE",
            severity=FINDING_SEVERITY_BLOCK,
            message="Missing unit.",
            path="src/demo/m.py",
            symbol="m",
        ),
    ]
    report = VerificationReport(
        authority_state="defined",
        allowed=False,
        findings=findings,
    )

    rendered = render_verify_report(report, finding_codes=["UNDECLARED_CODE"])

    assert "Filter: UNDECLARED_CODE" in rendered
    assert "  UNDECLARED_CODE: 1" in rendered
    assert "MISSING_DECLARED_CODE" not in rendered


def test_render_verify_report_supports_all_details_mode() -> None:
    findings = [
        Finding(
            source="drift",
            code="UNDECLARED_CODE",
            severity=FINDING_SEVERITY_BLOCK,
            message="Undeclared unit.",
            path=f"src/demo/file_{index}.py",
            symbol=f"symbol_{index}",
        )
        for index in range(10)
    ]
    report = VerificationReport(
        authority_state="defined",
        allowed=False,
        findings=findings,
    )

    rendered = render_verify_report(report, max_items_per_group=0)

    assert "  ... and " not in rendered
    assert "  - src/demo/file_9.py::symbol_9" in rendered
