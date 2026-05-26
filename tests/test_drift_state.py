"""Tests for persistent pre-inspector drift state."""

from pathlib import Path

from bpfw.integrations.diff.models import CodeTarget, DiffActionLevel, DiffItem, DiffItemKind, DiffRisk
from bpfw.integrations.inspector.base import InspectIssue
from bpfw.integrations.inspector.base import InspectLoadResult
from bpfw.integrations.inspector.drift_gate import DriftGateResult, merge_drift_gate_into_session
from bpfw.integrations.inspector.drift_state import (
    DriftState,
    DriftStateRepository,
    build_drift_evidence_hash,
    build_drift_stable_id,
)


def _undeclared_item() -> DiffItem:
    """Build one undeclared-code drift item for state tests.

    Returns:
        Diff item.
    """
    return DiffItem(
        identifier="undeclared-code-1",
        kind=DiffItemKind.UNDECLARED_CODE,
        action_level=DiffActionLevel.HUMAN_DECISION,
        risk=DiffRisk.MEDIUM,
        reason="Code exists but no authority block declares it.",
        code_target=CodeTarget(
            path="src/app/payments.py",
            symbol="PaymentValidator",
            kind="class",
            start_line=10,
            end_line=20,
            qualified_name="src.app.payments.PaymentValidator",
        ),
    )


def test_stable_id_and_evidence_hash_are_stable() -> None:
    """Stable id and evidence hash should be deterministic for same item."""
    first = _undeclared_item()
    second = _undeclared_item()

    assert build_drift_stable_id(first) == build_drift_stable_id(second)
    assert build_drift_evidence_hash(first) == build_drift_evidence_hash(second)


def test_repository_input_signature_changes_when_source_changes(tmp_path: Path) -> None:
    """Input signature should change when relevant source files change."""
    source_dir = tmp_path / "src" / "app"
    source_dir.mkdir(parents=True)
    source_file = source_dir / "payments.py"
    source_file.write_text("class PaymentValidator:\n    pass\n", encoding="utf-8")
    repository = DriftStateRepository(tmp_path)

    first_signature = repository.build_input_signature()
    source_file.write_text("class PaymentValidator:\n    def validate(self):\n        return True\n", encoding="utf-8")
    second_signature = repository.build_input_signature()

    assert first_signature != second_signature


def test_repository_round_trips_state(tmp_path: Path) -> None:
    """Drift state repository should persist and restore decisions."""
    item = _undeclared_item()
    repository = DriftStateRepository(tmp_path)
    state = DriftState(input_signature="sig", pending_human_decisions=0)
    state.record_decision(
        item=item,
        status="ignored",
        decision="IGNORE_UNDECLARED_CODE",
        reason="internal helper",
    )

    repository.save(state)
    loaded = repository.load()
    record = loaded.current_record_for(item)

    assert record is not None
    assert record.status == "ignored"
    assert record.reason == "internal helper"


def test_drift_state_restores_approved_inspector_issue() -> None:
    """Approved drift decisions should be restorable as inspector issues."""
    item = _undeclared_item()
    issue = InspectIssue(
        issue_type="approved_new",
        block={"id": "payment_validator", "name": "PaymentValidator"},
        add_on_accept=True,
        context_lines=["Current item: approved experimental responsibility from Drift Gate."],
    )
    state = DriftState(input_signature="sig", pending_human_decisions=0)
    state.record_decision(
        item=item,
        status="approved_for_inspector",
        decision="APPROVED_EXPERIMENTAL",
        issue=issue,
    )

    restored = state.restored_inspector_issues()
    assert len(restored) == 1
    assert restored[0].issue_type == "approved_new"
    assert restored[0].block["id"] == "payment_validator"
    assert restored[0].context_lines == ["Current item: approved experimental responsibility from Drift Gate."]


def test_mark_approved_issue_resolved_updates_decision_status() -> None:
    """Saving approved inspector metadata should mark drift decision as resolved."""
    item = _undeclared_item()
    issue = InspectIssue(
        issue_type="approved_new",
        block={
            "id": "payment_validator",
            "code": {
                "path": "src/app/payments.py",
                "symbol": "PaymentValidator",
                "kind": "class",
            },
        },
        add_on_accept=True,
    )
    state = DriftState(input_signature="sig", pending_human_decisions=0)
    state.record_decision(
        item=item,
        status="approved_for_inspector",
        decision="APPROVED_EXPERIMENTAL",
        issue=issue,
    )

    changed = state.mark_approved_issue_resolved(issue.block)
    record = state.current_record_for(item)
    assert changed
    assert record is not None
    assert record.status == "resolved"


def test_cached_preflight_loads_metadata_only_session(tmp_path: Path) -> None:
    """Reusable drift state should avoid full inspector scan/verify loading."""
    from bpfw.integrations.inspector.session import _try_load_cached_preflight

    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "blocks:\n"
        "  - id: example\n"
        "    name: ExampleService\n"
        "    domain: ''\n"
        "    status: active\n"
        "    purpose: ''\n"
        "    code:\n"
        "      path: src/app/example.py\n"
        "      symbol: ExampleService\n"
        "      kind: class\n",
        encoding="utf-8",
    )
    source_path = tmp_path / "src" / "app" / "example.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("class ExampleService:\n    pass\n", encoding="utf-8")

    repository = DriftStateRepository(tmp_path)
    state = DriftState(
        input_signature=repository.build_input_signature(),
        pending_human_decisions=0,
    )
    state.record_decision(
        item=_undeclared_item(),
        status="approved_for_inspector",
        decision="APPROVED_EXPERIMENTAL",
        issue=InspectIssue(
            issue_type="approved_new",
            block={
                "id": "payment_validator",
                "code": {"path": "src/app/payments.py", "symbol": "PaymentValidator", "kind": "class"},
            },
            add_on_accept=True,
        ),
    )
    repository.save(state)

    cached = _try_load_cached_preflight(project_root=tmp_path)
    assert cached is not None
    session, drift_result = cached
    assert drift_result.cache_hit
    assert session.scan_result is None
    assert session.verify_report is None


def test_drift_state_reuses_pending_items_when_signature_matches() -> None:
    """Pending human decisions should be reusable when inputs are unchanged."""
    item = _undeclared_item()
    state = DriftState(input_signature="sig", pending_human_decisions=1)
    state.replace_pending_items([item])

    assert state.has_reusable_pending_items("sig")
    assert not state.is_reusable_for_signature("sig")
    assert state.restored_pending_items()[0].identifier == item.identifier


def test_repository_round_trips_pending_items(tmp_path: Path) -> None:
    """Drift state repository should persist pending Drift Gate items."""
    item = _undeclared_item()
    repository = DriftStateRepository(tmp_path)
    state = DriftState(input_signature="sig", pending_human_decisions=1)
    state.replace_pending_items([item])

    repository.save(state)
    loaded = repository.load()

    assert loaded.has_reusable_pending_items("sig")
    assert loaded.restored_pending_items()[0].code_target is not None
    assert loaded.restored_pending_items()[0].code_target.symbol == "PaymentValidator"


def test_cached_pending_preflight_uses_minimal_session(tmp_path: Path) -> None:
    """Pending Drift Gate cache should not load metadata before review."""
    from bpfw.integrations.inspector.session import _load_drift_preflight, _try_load_cached_pending_preflight

    source_path = tmp_path / "src" / "app" / "payments.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("class PaymentValidator:\n    pass\n", encoding="utf-8")

    repository = DriftStateRepository(tmp_path)
    state = DriftState(input_signature=repository.build_input_signature(), pending_human_decisions=1)
    state.replace_pending_items([_undeclared_item()])
    repository.save(state)

    preflight = _load_drift_preflight(tmp_path)
    cached = _try_load_cached_pending_preflight(project_root=tmp_path, preflight=preflight)

    assert cached is not None
    session, pending_items = cached
    assert session.authority_state == "cached_pending_drift"
    assert session.blueprint_data == {}
    assert session.scan_result is None
    assert session.verify_report is None
    assert len(pending_items) == 1


def test_startup_decision_prefers_resume_fast_with_valid_snapshot(tmp_path: Path) -> None:
    """Startup should choose resume fast route when snapshot signature matches."""
    from bpfw.integrations.inspector.session import (
        SignatureContext,
        _build_startup_decision,
        _load_drift_preflight,
    )
    from bpfw.integrations.inspector.inspector_state import (
        InspectorResumeState,
        InspectorStateRepository,
    )

    source_path = tmp_path / "src" / "app" / "payments.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("class PaymentValidator:\n    pass\n", encoding="utf-8")

    preflight = _load_drift_preflight(tmp_path)
    InspectorStateRepository(tmp_path).save(
        InspectorResumeState(
            input_signature=preflight.input_signature,
            current_index=0,
            mode_name="compact",
            issues=[],
            saved_at="2026-05-26T00:00:00+00:00",
        )
    )
    # Snapshot must include at least one issue to be reusable.
    snapshot_repository = InspectorStateRepository(tmp_path)
    snapshot = snapshot_repository.load()
    assert snapshot is not None
    snapshot.issues = [
        InspectIssue(
            issue_type="draft",
            block={"id": "example", "name": "Example", "domain": "", "status": "", "purpose": ""},
        )
    ]
    snapshot_repository.save(snapshot)

    decision = _build_startup_decision(
        project_root=tmp_path,
        preflight=preflight,
        signature_context=SignatureContext(
            input_signature=preflight.input_signature,
            authority_signature="authority-signature",
        ),
    )

    assert decision.route == "resume_fast"


def test_merge_skips_reinjection_for_completed_declared_blocks(tmp_path: Path) -> None:
    """Approved drift issues should not reappear when block is already complete."""
    completed_block = {
        "id": "payment_validator",
        "purpose": "validate payment",
        "name": "PaymentValidator",
        "domain": "payments",
        "status": "active",
        "code": {
            "path": "src/app/payments.py",
            "symbol": "PaymentValidator",
            "kind": "class",
        },
    }
    session = InspectLoadResult(
        project_root=tmp_path,
        blueprint_path=tmp_path / "bpfw" / "blueprint.yaml",
        blueprint_data={"blocks": [completed_block]},
        incomplete=[],
        issues=[],
        authority_state="defined",
    )
    incoming_issue = InspectIssue(
        issue_type="approved_new",
        block={
            "id": "payment_validator",
            "purpose": "",
            "name": "PaymentValidator",
            "domain": "",
            "status": "active",
            "code": {
                "path": "src/app/payments.py",
                "symbol": "PaymentValidator",
                "kind": "class",
            },
        },
        add_on_accept=True,
    )
    result = DriftGateResult(
        approved_count=1,
        inspector_issues=[incoming_issue],
    )

    merge_drift_gate_into_session(session=session, result=result)
    assert session.issues == []
