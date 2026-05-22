"""Tests for sharded authority verification in catalog verify."""

from pathlib import Path
from types import SimpleNamespace

from bpfw.core.catalog import verify


def test_validate_sharded_authority_ignores_unified_blocks_from_loader(monkeypatch, tmp_path: Path) -> None:
    """Do not flag root-level blocks when only unified loader data contains blocks."""

    load_result = SimpleNamespace(
        data={
            "authority": {"layout": "sharded"},
            "includes": ["bpfw/blocks/core.yaml"],
            "blocks": [{"id": "from_shard"}],
        }
    )

    monkeypatch.setattr(
        verify.AuthorityIndex,
        "load",
        classmethod(lambda _cls, _project_root: SimpleNamespace(
            data={
                "authority": {"layout": "sharded"},
                "includes": ["bpfw/blocks/core.yaml"],
            }
        )),
    )
    monkeypatch.setattr(verify, "AuthorityRepository", lambda _project_root: SimpleNamespace(load=lambda: object(), validate=lambda _document: []))
    monkeypatch.setattr(Path, "exists", lambda _path: True)

    findings = verify._validate_sharded_authority(project_root=tmp_path, load_result=load_result)

    assert not any(finding.code == "ROOT_LEVEL_BLOCKS_NOT_ALLOWED" for finding in findings)


def test_validate_sharded_authority_flags_blocks_in_root_index(monkeypatch, tmp_path: Path) -> None:
    """Flag root-level blocks when they are present in the raw root index."""

    load_result = SimpleNamespace(
        data={
            "authority": {"layout": "sharded"},
            "includes": ["bpfw/blocks/core.yaml"],
            "blocks": [{"id": "from_unified_loader"}],
        }
    )

    monkeypatch.setattr(
        verify.AuthorityIndex,
        "load",
        classmethod(lambda _cls, _project_root: SimpleNamespace(
            data={
                "authority": {"layout": "sharded"},
                "includes": ["bpfw/blocks/core.yaml"],
                "blocks": [{"id": "in_root"}],
            }
        )),
    )
    monkeypatch.setattr(verify, "AuthorityRepository", lambda _project_root: SimpleNamespace(load=lambda: object(), validate=lambda _document: []))
    monkeypatch.setattr(Path, "exists", lambda _path: True)

    findings = verify._validate_sharded_authority(project_root=tmp_path, load_result=load_result)

    assert any(finding.code == "ROOT_LEVEL_BLOCKS_NOT_ALLOWED" for finding in findings)
