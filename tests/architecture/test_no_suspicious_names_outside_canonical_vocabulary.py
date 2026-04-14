"""Test NAME001: no suspicious names outside canonical vocabulary.

Validates that detect_suspicious_names() responds observably to violations
and that the actual codebase contains no suspicious names in src/.
"""

from pathlib import Path

import pytest

from bpfw.architecture.checker import (
    _collect_suspicious_names_from_ast,
    detect_suspicious_names,
)
import ast


class TestSuspiciousNameDetectorObservability:
    """The detector must respond observably to synthetic violations."""

    def test_returns_list_for_empty_path_list(self) -> None:
        result = detect_suspicious_names([])
        assert isinstance(result, list)
        assert result == []

    def test_ignores_nonexistent_path(self) -> None:
        result = detect_suspicious_names([Path("nonexistent_xyz")])
        assert result == []

    def test_detects_manager_prefix_class(self, tmp_path: Path) -> None:
        # _SUSPICIOUS_NAME_PATTERNS matches names that start with the keyword at a word boundary.
        # "ManagerProxy" starts with "Manager" → detected.
        # "DocumentManager" does NOT start with "Manager" → not detected.
        (tmp_path / "bad.py").write_text(
            "class ManagerProxy:\n    pass\n", encoding="utf-8"
        )
        violations = detect_suspicious_names([tmp_path])
        assert any("ManagerProxy" in msg for msg in violations)

    def test_detects_unified_function(self, tmp_path: Path) -> None:
        (tmp_path / "bad.py").write_text(
            "def UnifiedSearch():\n    pass\n", encoding="utf-8"
        )
        violations = detect_suspicious_names([tmp_path])
        assert any("UnifiedSearch" in msg for msg in violations)

    def test_detects_smart_name(self, tmp_path: Path) -> None:
        (tmp_path / "bad.py").write_text(
            "class SmartRouter:\n    pass\n", encoding="utf-8"
        )
        violations = detect_suspicious_names([tmp_path])
        assert any("SmartRouter" in msg for msg in violations)

    def test_detects_enhanced_name(self, tmp_path: Path) -> None:
        (tmp_path / "bad.py").write_text(
            "class EnhancedPipeline:\n    pass\n", encoding="utf-8"
        )
        violations = detect_suspicious_names([tmp_path])
        assert any("EnhancedPipeline" in msg for msg in violations)

    def test_detects_mega_name(self, tmp_path: Path) -> None:
        (tmp_path / "bad.py").write_text(
            "class MegaProcessor:\n    pass\n", encoding="utf-8"
        )
        violations = detect_suspicious_names([tmp_path])
        assert any("MegaProcessor" in msg for msg in violations)

    def test_skips_infrastructure_support_paths(self, tmp_path: Path) -> None:
        support_dir = tmp_path / "support"
        support_dir.mkdir()
        (support_dir / "handler.py").write_text(
            "class SystemdManager:\n    pass\n", encoding="utf-8"
        )
        violations = detect_suspicious_names([tmp_path])
        assert violations == []

    def test_skips_tools_path(self, tmp_path: Path) -> None:
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "handler.py").write_text(
            "class BuildManager:\n    pass\n", encoding="utf-8"
        )
        violations = detect_suspicious_names([tmp_path])
        assert violations == []

    def test_violation_message_contains_file_path(self, tmp_path: Path) -> None:
        # Use a name that starts with a suspicious keyword (pattern matches at word boundary)
        (tmp_path / "mymodule.py").write_text(
            "class SmartCache:\n    pass\n", encoding="utf-8"
        )
        violations = detect_suspicious_names([tmp_path])
        assert len(violations) >= 1
        assert "mymodule.py" in violations[0]

    def test_each_unique_name_reported_once_per_file(self, tmp_path: Path) -> None:
        (tmp_path / "dup.py").write_text(
            "class ManagerFoo:\n    pass\nclass ManagerBar(ManagerFoo):\n    pass\n",
            encoding="utf-8",
        )
        violations = detect_suspicious_names([tmp_path])
        # Both ManagerFoo and ManagerBar are suspicious; each unique name once
        names_found = {msg.split("'")[1] for msg in violations}
        assert len(names_found) == len(violations)

    def test_clean_file_produces_no_violations(self, tmp_path: Path) -> None:
        (tmp_path / "clean.py").write_text(
            "class QueryOrchestrator:\n    pass\n", encoding="utf-8"
        )
        violations = detect_suspicious_names([tmp_path])
        assert violations == []


class TestCollectSuspiciousNamesFromAst:
    """Unit tests for the AST collection helper."""

    def _parse(self, source: str) -> ast.Module:
        return ast.parse(source)

    def test_finds_class_definition(self) -> None:
        tree = self._parse("class SmartHandler:\n    pass\n")
        found = _collect_suspicious_names_from_ast(tree)
        assert "SmartHandler" in found

    def test_finds_function_definition(self) -> None:
        tree = self._parse("def MegaProcess():\n    pass\n")
        found = _collect_suspicious_names_from_ast(tree)
        assert "MegaProcess" in found

    def test_finds_import_alias(self) -> None:
        tree = self._parse("import os as UnifiedOS\n")
        found = _collect_suspicious_names_from_ast(tree)
        assert "UnifiedOS" in found

    def test_ignores_string_literals(self) -> None:
        tree = self._parse('x = "DataManager"\n')
        found = _collect_suspicious_names_from_ast(tree)
        assert "DataManager" not in found

    def test_finds_all_export(self) -> None:
        tree = self._parse('__all__ = ["EnhancedRouter"]\n')
        found = _collect_suspicious_names_from_ast(tree)
        assert "EnhancedRouter" in found


class TestNameIntegration:
    """Integration: no suspicious names in the actual src/ codebase."""

    def test_src_has_no_suspicious_names(self) -> None:
        src_path = Path("src")
        if not src_path.exists():
            pytest.skip("src/ not found — run from repo root")
        violations = detect_suspicious_names([src_path])
        assert violations == [], (
            "NAME001 violations found in src/:\n" + "\n".join(f"  {v}" for v in violations)
        )
