from pathlib import Path

from bpfw.watch import BpfwWatchFilter, _fingerprint_findings, build_verification_snapshot
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding


def test_watch_filter_accepts_relevant_project_files(tmp_path: Path) -> None:
    """The watch filter should accept source and authority files."""

    watch_filter = BpfwWatchFilter(project_root=tmp_path)
    python_file = tmp_path / "src" / "demo.py"
    yaml_file = tmp_path / "bpfw" / "blueprint.yaml"

    assert watch_filter(None, str(python_file)) is True
    assert watch_filter(None, str(yaml_file)) is True


def test_watch_filter_ignores_cache_and_build_files(tmp_path: Path) -> None:
    """The watch filter should ignore noisy generated directories."""

    watch_filter = BpfwWatchFilter(project_root=tmp_path)
    cache_file = tmp_path / ".bpfw" / "cache" / "index.json"
    pycache_file = tmp_path / "src" / "__pycache__" / "demo.pyc"
    dist_file = tmp_path / "dist" / "package.py"

    assert watch_filter(None, str(cache_file)) is False
    assert watch_filter(None, str(pycache_file)) is False
    assert watch_filter(None, str(dist_file)) is False


def test_finding_fingerprint_is_stable_regardless_of_order() -> None:
    """Finding fingerprints should stay stable when finding order changes."""

    first = Finding(
        source="bpfw",
        code="UNDECLARED_CODE",
        severity=FINDING_SEVERITY_BLOCK,
        message="Undeclared code.",
        path="src/a.py",
        symbol="A",
        evidence={"kind": "class"},
    )
    second = Finding(
        source="bpfw",
        code="MISSING_DECLARED_CODE",
        severity=FINDING_SEVERITY_BLOCK,
        message="Missing code.",
        path="src/b.py",
        symbol="B",
        evidence={"kind": "class"},
    )

    assert _fingerprint_findings([first, second]) == _fingerprint_findings([second, first])


def test_build_verification_snapshot_uses_existing_verify_pipeline(tmp_path: Path) -> None:
    """The watch snapshot should reuse the current verify pipeline."""

    snapshot = build_verification_snapshot(project_root=tmp_path)

    assert snapshot.allowed is True
    assert snapshot.exit_code == 0
    assert snapshot.finding_count >= 0
    assert snapshot.block_count == 0
    assert "BPFW VERIFY" in snapshot.report_text
