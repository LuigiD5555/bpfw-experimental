"""Tests for structural drift detection in draft authority."""

from bpfw.core.catalog.drift import compare_declared_to_discovered
from bpfw.core.catalog.models import AUTHORITY_STATE_DRAFT, DiscoveredCodeUnit


def test_draft_authority_still_detects_structural_drift() -> None:
    """Draft metadata must not hide missing and undeclared code drift."""
    blueprint_data = {
        "blocks": [
            {
                "id": "payments.PaymentValidator",
                "code": {
                    "path": "src/app/payments.py",
                    "symbol": "PaymentValidator",
                    "kind": "class",
                },
            }
        ]
    }
    discovered_units = [
        DiscoveredCodeUnit(
            path="src/app/refunds.py",
            module="src.app.refunds",
            symbol="RefundValidator",
            symbol_type="class",
            qualified_name="src.app.refunds.RefundValidator",
        )
    ]

    findings = compare_declared_to_discovered(
        blueprint_data=blueprint_data,
        discovered_units=discovered_units,
        authority_state=AUTHORITY_STATE_DRAFT,
    )

    assert {finding.code for finding in findings} == {"MISSING_DECLARED_CODE", "UNDECLARED_CODE"}
