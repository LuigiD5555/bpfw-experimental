"""Write-scope guard: block catalog mutations on external project roots by default."""

from pathlib import Path

from bpfw.catalog.authority import (
    install_hooks_command,
    lock_catalog_command,
    unlock_catalog_command,
)


def _configure_external_target(monkeypatch, workspace_root: Path) -> Path:
    external_root = workspace_root / "external-rag-project"
    external_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(workspace_root)
    monkeypatch.setenv("BPFW_PROJECT_ROOT", str(external_root))
    monkeypatch.delenv("BPFW_ALLOW_EXTERNAL_CATALOG_WRITES", raising=False)
    return external_root


def test_lock_command_blocks_external_target_by_default(monkeypatch, tmp_path: Path, capsys) -> None:
    _configure_external_target(monkeypatch, tmp_path)
    exit_code = lock_catalog_command()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "External catalog write blocked" in (captured.out + captured.err)


def test_unlock_command_blocks_external_target_by_default(monkeypatch, tmp_path: Path, capsys) -> None:
    _configure_external_target(monkeypatch, tmp_path)
    exit_code = unlock_catalog_command(require_sudo=False)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "External catalog write blocked" in (captured.out + captured.err)


def test_install_hooks_blocks_external_target_by_default(monkeypatch, tmp_path: Path, capsys) -> None:
    _configure_external_target(monkeypatch, tmp_path)
    exit_code = install_hooks_command(force=False)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "External catalog write blocked" in (captured.out + captured.err)


def test_unlock_without_sudo_is_rejected_even_for_internal_calls(monkeypatch, tmp_path: Path, capsys) -> None:
    catalog_root = tmp_path / "project"
    responsibilities = catalog_root / "src" / "catalog" / "responsibilities"
    responsibilities.mkdir(parents=True, exist_ok=True)
    (responsibilities / "001_example.yaml").write_text("responsibility_id: sample\n", encoding="utf-8")
    monkeypatch.chdir(catalog_root)
    monkeypatch.delenv("BPFW_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("BPFW_ALLOW_EXTERNAL_CATALOG_WRITES", raising=False)
    monkeypatch.setattr("os.geteuid", lambda: 1000)

    exit_code = unlock_catalog_command(require_sudo=False)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "unlock without sudo is prohibited" in (captured.out + captured.err)
