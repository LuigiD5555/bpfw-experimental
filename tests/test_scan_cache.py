"""Tests for incremental scan cache."""

from pathlib import Path

from bpfw.core.catalog.scan_cache import ScanCacheRepository, cached_scan_python_project


def test_cached_scan_reuses_unchanged_file_results(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """Unchanged files should be restored from scan cache instead of rescanned."""
    source_root = tmp_path / "src"
    source_root.mkdir()
    source_file = source_root / "example.py"
    source_file.write_text(
        "class ExampleService:\n"
        "    def process(self):\n"
        "        return True\n",
        encoding="utf-8",
    )

    first_scan = cached_scan_python_project(tmp_path, ["src"], [])
    assert any(unit.symbol == "ExampleService" for unit in first_scan.discovered_units)
    assert ScanCacheRepository(tmp_path).cache_path.exists()

    import bpfw.core.catalog.scan_cache as scan_cache_module

    def fail_scan(*_args, **_kwargs):  # noqa: ANN002, ANN003
        """Fail when cache unexpectedly scans an unchanged file."""
        raise AssertionError("file should have been restored from cache")

    monkeypatch.setattr(scan_cache_module, "_scan_python_file", fail_scan)

    second_scan = cached_scan_python_project(tmp_path, ["src"], [])

    assert any(unit.symbol == "ExampleService" for unit in second_scan.discovered_units)


def test_cached_scan_rescans_changed_file(tmp_path: Path) -> None:
    """Changed files should be rescanned and cache should update."""
    source_root = tmp_path / "src"
    source_root.mkdir()
    source_file = source_root / "example.py"
    source_file.write_text("class OldService:\n    def process(self):\n        return True\n", encoding="utf-8")
    first_scan = cached_scan_python_project(tmp_path, ["src"], [])

    source_file.write_text("class NewService:\n    def process(self):\n        return True\n", encoding="utf-8")
    second_scan = cached_scan_python_project(tmp_path, ["src"], [])

    assert any(unit.symbol == "OldService" for unit in first_scan.discovered_units)
    assert any(unit.symbol == "NewService" for unit in second_scan.discovered_units)
