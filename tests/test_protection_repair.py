from pathlib import Path

import bpfw.protection.setup as protection_setup
from bpfw.protection.setup import ProtectionSetupResult, run_repair


def test_repair_blocks_when_blueprint_is_missing(tmp_path: Path) -> None:
    success, message, exit_code = run_repair(project_root=tmp_path)

    assert success is False
    assert exit_code == 1
    assert "missing: bpfw/blueprint.yaml" in message


def test_repair_uses_protection_setup_without_regenerating_blueprint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    blueprint_path = tmp_path / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text("version: 1\nresponsibilities: []\n", encoding="utf-8")
    original_content = blueprint_path.read_text(encoding="utf-8")

    def fake_setup(project_root: Path) -> ProtectionSetupResult:
        return ProtectionSetupResult(
            blueprint_exists=(project_root / "bpfw" / "blueprint.yaml").exists(),
            lock_state="locked",
        )

    monkeypatch.setattr(protection_setup, "run_protection_setup", fake_setup)

    success, message, exit_code = run_repair(project_root=tmp_path)

    assert success is True
    assert exit_code == 0
    assert "BPFW repair completed." in message
    assert blueprint_path.read_text(encoding="utf-8") == original_content
