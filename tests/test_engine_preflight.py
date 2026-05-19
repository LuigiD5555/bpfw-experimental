from pathlib import Path

from bpfw.catalog.models import VerificationReport
from bpfw.core import registry as core_registry
from bpfw.core.engine import BlueprintEngine, build_command
from bpfw.core.result import ResultStatus
from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.registry import IntegrationRegistry
from bpfw.integrations.result import OptionalIntegrationResult


class RecordingIntegration(OptionalIntegration):
    """Integration test double that records whether it was executed."""

    name = "inspector"

    def __init__(self) -> None:
        """Initialize the integration execution flag."""

        self.was_run = False

    def is_available(self) -> bool:
        """Return that the integration is available for engine tests."""

        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        """Record execution and return a successful integration result."""

        self.was_run = True
        return OptionalIntegrationResult(message="integration ran", exit_code=0)


def test_inspector_runs_integration_without_verify_preflight(tmp_path: Path) -> None:
    """Verify inspector runs integration without verify preflight blocking."""

    (tmp_path / "bpfw").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "bpfw" / "blueprint.yaml").write_text(
        "version: 1\n"
        "project:\n"
        "  source_roots:\n"
        "    - src\n"
        "blocks:\n"
        "  - id: missing_service\n"
        "    purpose: missing service\n"
        "    name: MissingService\n"
        "    domain: catalog\n"
        "    status: active\n"
        "    code:\n"
        "      path: src/missing.py\n"
        "      symbol: MissingService\n"
        "      kind: class\n",
        encoding="utf-8",
    )

    integration = RecordingIntegration()
    registry = IntegrationRegistry()
    registry.register(integration)

    result = BlueprintEngine(integration_registry=registry).run(
        build_command(
            command_name="inspector",
            project_root=tmp_path,
            arguments={},
        )
    )

    assert result.status == ResultStatus.OK
    assert [step.source for step in result.steps] == ["integrations.inspector"]
    assert integration.was_run is True


def test_inspector_attempts_unlock_before_running_integration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify inspector auto-unlocks authority before integration execution."""

    def fake_verify(project_root: Path, precomputed_scan_result=None) -> tuple[VerificationReport, int]:
        return (
            VerificationReport(
                authority_state="defined",
                allowed=True,
                findings=[],
            ),
            0,
        )

    class UnlockResult:
        status = "unlocked"

    monkeypatch.setattr(core_registry, "run_verify", fake_verify)
    monkeypatch.setattr(core_registry, "get_authority_protection_status", lambda project_root: type("ProtectionStatus", (), {"status": "locked"})())
    monkeypatch.setattr(core_registry, "unlock_authority", lambda project_root: UnlockResult())

    integration = RecordingIntegration()
    registry = IntegrationRegistry()
    registry.register(integration)

    result = BlueprintEngine(integration_registry=registry).run(
        build_command(
            command_name="inspector",
            project_root=tmp_path,
            arguments={},
        )
    )

    assert result.status == ResultStatus.OK
    assert [step.source for step in result.steps] == ["catalog.verify", "integrations.inspector"]
    assert integration.was_run is True


def test_inspector_allows_draft_incomplete_preflight_without_blocking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify inspector is not blocked when verify only reports incomplete draft metadata."""

    def fake_verify(project_root: Path, precomputed_scan_result=None) -> tuple[VerificationReport, int]:
        return (
            VerificationReport(
                authority_state="draft",
                allowed=False,
                findings=[],
                missing_declared_count=0,
                undeclared_count=0,
                duplicate_active_purpose_count=0,
                invalid_lifecycle_count=0,
                incomplete_responsibility_count=12,
            ),
            1,
        )

    class LockState:
        status = "locked"

    monkeypatch.setattr(core_registry, "run_verify", fake_verify)
    monkeypatch.setattr(core_registry, "get_authority_protection_status", lambda project_root: LockState())
    monkeypatch.setattr(core_registry, "unlock_authority", lambda project_root: type("UnlockResult", (), {"status": "unlocked"})())

    integration = RecordingIntegration()
    registry = IntegrationRegistry()
    registry.register(integration)

    result = BlueprintEngine(integration_registry=registry).run(
        build_command(
            command_name="inspector",
            project_root=tmp_path,
            arguments={},
        )
    )

    assert result.status in {ResultStatus.OK, ResultStatus.WARNING}
    assert result.steps[0].source == "catalog.verify"
    assert result.steps[0].status == ResultStatus.WARNING
    assert result.steps[1].source == "integrations.inspector"
    assert integration.was_run is True
