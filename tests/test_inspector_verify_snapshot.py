"""Tests for inspector verify snapshot cache."""

from bpfw.core.catalog.models import VerificationReport
from bpfw.integrations.inspector.verify_snapshot import VerifySnapshotRepository
from bpfw.reports.finding import Finding


def test_verify_snapshot_round_trip(tmp_path) -> None:
    repository = VerifySnapshotRepository(tmp_path)
    report = VerificationReport(
        authority_state="defined",
        allowed=True,
        findings=[
            Finding(
                source="verify",
                code="UNDECLARED_CODE",
                severity="warning",
                message="undeclared",
                path="src/app.py",
                symbol="run",
                evidence={"kind": "function"},
            )
        ],
        declared_count=2,
        discovered_count=3,
        undeclared_count=1,
    )
    repository.save(
        input_signature="sig-input",
        authority_signature="sig-auth",
        report=report,
        saved_at="2026-05-26T00:00:00+00:00",
    )

    loaded = repository.load(input_signature="sig-input", authority_signature="sig-auth")

    assert loaded is not None
    assert loaded.report.undeclared_count == 1
    assert loaded.report.findings[0].code == "UNDECLARED_CODE"


def test_verify_snapshot_signature_mismatch_returns_none(tmp_path) -> None:
    repository = VerifySnapshotRepository(tmp_path)
    repository.save(
        input_signature="sig-input",
        authority_signature="sig-auth",
        report=VerificationReport(authority_state="defined", allowed=True, findings=[]),
        saved_at="2026-05-26T00:00:00+00:00",
    )

    assert repository.load(input_signature="sig-input", authority_signature="other") is None
