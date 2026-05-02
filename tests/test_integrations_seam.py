from pathlib import Path

from bpfw.integrations.registry import IntegrationRegistry


def test_empty_integration_registry_returns_empty_results(tmp_path: Path) -> None:
    registry = IntegrationRegistry()

    assert registry.list_integrations() == []
    result = registry.run(name="missing", project_root=tmp_path)
    assert result.success is False
