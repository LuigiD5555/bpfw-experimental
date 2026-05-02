from pathlib import Path

from bpfw.core.registry import build_default_registry
from bpfw.integrations.base import OptionalIntegration
from bpfw.integrations.registry import (
    IntegrationRegistry,
    build_default_integration_registry,
)
from bpfw.integrations.result import OptionalIntegrationResult


class FakeIntegration(OptionalIntegration):
    name = "fake"

    def is_available(self) -> bool:
        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        return OptionalIntegrationResult(
            message=f"ran fake in {project_root.name}",
            exit_code=0,
        )


class SecondFakeIntegration(OptionalIntegration):
    name = "second"

    def is_available(self) -> bool:
        return True

    def run(self, project_root: Path) -> OptionalIntegrationResult:
        return OptionalIntegrationResult(message="ran second", exit_code=0)


class InvalidIntegration:
    name = "invalid"


class FakeEntryPoint:
    def __init__(self, loaded_value, should_fail: bool = False) -> None:
        self.loaded_value = loaded_value
        self.should_fail = should_fail

    def load(self):  # noqa: ANN201
        if self.should_fail:
            raise ImportError("entry point failed")
        return self.loaded_value


def test_empty_integration_registry_returns_empty_results(tmp_path: Path) -> None:
    registry = IntegrationRegistry()

    assert registry.list_integrations() == []
    result = registry.run(name="missing", project_root=tmp_path)
    assert result.success is False


def test_entry_point_registry_loads_valid_integrations(monkeypatch) -> None:
    monkeypatch.setattr(
        "bpfw.integrations.registry.entry_points",
        lambda group: [
            FakeEntryPoint(FakeIntegration),
            FakeEntryPoint(SecondFakeIntegration),
        ],
    )

    registry = build_default_integration_registry()

    assert registry.get("fake") is not None
    assert registry.get("second") is not None


def test_entry_point_registry_ignores_invalid_and_failed_plugins(monkeypatch) -> None:
    monkeypatch.setattr(
        "bpfw.integrations.registry.entry_points",
        lambda group: [
            FakeEntryPoint(InvalidIntegration),
            FakeEntryPoint(FakeIntegration, should_fail=True),
        ],
    )

    registry = build_default_integration_registry()

    assert registry.list_integrations() == []


def test_registry_runs_discovered_integration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "bpfw.integrations.registry.entry_points",
        lambda group: [FakeEntryPoint(FakeIntegration)],
    )
    registry = build_default_integration_registry()

    result = registry.run(name="fake", project_root=tmp_path)

    assert result.success is True
    assert result.message == f"ran fake in {tmp_path.name}"


def test_core_registry_builds_plugin_pipelines_from_registry() -> None:
    integration_registry = IntegrationRegistry()
    integration_registry.register(FakeIntegration())

    pipelines = build_default_registry(integration_registry=integration_registry)

    assert "fake" in pipelines
    assert pipelines["fake"].steps[0].name == "plugins.fake"
