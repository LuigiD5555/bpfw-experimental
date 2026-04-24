"""Catalog lock policy: strong filesystem enforcement is mandatory."""

from pathlib import Path
from unittest.mock import patch

from bpfw.catalog.file_permissions import CatalogLockEnforcementError
from bpfw.catalog.authority import lock_catalog_command


def test_lock_fails_when_strong_lock_cannot_be_enforced(capsys) -> None:
    with (
        patch("bpfw.catalog.authority.assert_catalog_write_scope"),
        patch("bpfw.catalog.authority._require_sudo"),
        patch("bpfw.catalog.authority.list_catalog_yaml_files", return_value=[Path("dummy.yaml")]),
        patch(
            "bpfw.catalog.authority.apply_strong_lock",
            side_effect=CatalogLockEnforcementError("Filesystem did not enforce write blocking after lock."),
        ),
        patch("bpfw.catalog.authority.write_state_file") as write_state_mock,
    ):
        exit_code = lock_catalog_command()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Filesystem did not enforce write blocking after lock." in (captured.out + captured.err)
    write_state_mock.assert_not_called()


def test_lock_persists_backend_when_strong_lock_succeeds(capsys) -> None:
    with (
        patch("bpfw.catalog.authority.assert_catalog_write_scope"),
        patch("bpfw.catalog.authority._require_sudo"),
        patch("bpfw.catalog.authority.list_catalog_yaml_files", return_value=[Path("dummy.yaml")]),
        patch("bpfw.catalog.authority.apply_strong_lock", return_value="linux_immutable"),
        patch("bpfw.catalog.authority.write_state_file") as write_state_mock,
    ):
        exit_code = lock_catalog_command()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "SUCCESS: catalog locked (linux_immutable)" in (captured.out + captured.err)
    write_state_mock.assert_called_once()
