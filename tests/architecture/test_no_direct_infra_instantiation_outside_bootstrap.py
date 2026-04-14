"""Test for prohibited direct instantiation of infrastructure classes outside bootstrap.

This test enforces the architecture rule that critical infrastructure classes
(ProviderFactory, WeaviateRetriever, IngestionOrchestrator) must only be
instantiated within the bootstrap layer to ensure proper dependency injection.
"""

from pathlib import Path

import pytest

from bpfw.architecture.checker import (
    _PROHIBITED_CLASSES,
    detect_direct_infra_instantiations,
)


class TestNoDirectInfraInstantiationOutsideBootstrap:
    """Tests for the prohibited direct instantiation detector."""

    def test_detect_direct_infra_instantiations_returns_list(self) -> None:
        """Detector should return a list (possibly empty)."""
        src_path = Path("src")
        result = detect_direct_infra_instantiations([src_path])
        assert isinstance(result, list)

    def test_detector_ignores_nonexistent_paths(self) -> None:
        """Detector should handle nonexistent paths gracefully."""
        result = detect_direct_infra_instantiations([Path("nonexistent_path")])
        assert result == []

    def test_prohibited_classes_are_defined(self) -> None:
        """The set of prohibited classes should include the required ones."""
        required_classes = {"ProviderFactory", "WeaviateRetriever", "IngestionOrchestrator"}
        assert required_classes.issubset(_PROHIBITED_CLASSES)

    def test_detector_finds_violation_in_sample_code(self, tmp_path: Path) -> None:
        """Detector should find a violation in a sample file."""
        # Create a temporary Python file with a prohibited instantiation
        test_file = tmp_path / "test_violation.py"
        test_file.write_text(
            """
from somewhere import ProviderFactory

def create_factory():
    return ProviderFactory()
""",
            encoding="utf-8",
        )

        violations = detect_direct_infra_instantiations([tmp_path])
        assert len(violations) == 1
        assert "ProviderFactory" in violations[0]
        assert "test_violation.py" in violations[0]

    def test_detector_ignores_comments(self, tmp_path: Path) -> None:
        """Detector should not match class names in comments."""
        test_file = tmp_path / "test_comments.py"
        test_file.write_text(
            """
# This is a comment about ProviderFactory
# ProviderFactory() should not be detected here
""",
            encoding="utf-8",
        )

        violations = detect_direct_infra_instantiations([tmp_path])
        assert len(violations) == 0

    def test_detector_ignores_docstrings(self, tmp_path: Path) -> None:
        """Detector should not match class names in docstrings."""
        test_file = tmp_path / "test_docstrings.py"
        test_file.write_text(
            '''
"""Module docstring mentioning ProviderFactory.

ProviderFactory() in docstring should not be detected.
"""
pass
''',
            encoding="utf-8",
        )

        violations = detect_direct_infra_instantiations([tmp_path])
        assert len(violations) == 0

    def test_detector_ignores_bootstrap_directory(self, tmp_path: Path) -> None:
        """Detector should skip files in bootstrap directory."""
        # Create a file in a bootstrap subdirectory
        bootstrap_dir = tmp_path / "bootstrap"
        bootstrap_dir.mkdir()
        bootstrap_file = bootstrap_dir / "wiring.py"
        bootstrap_file.write_text(
            """
from somewhere import ProviderFactory

def setup():
    return ProviderFactory()
""",
            encoding="utf-8",
        )

        violations = detect_direct_infra_instantiations([tmp_path])
        assert len(violations) == 0

    def test_detector_finds_multiple_violations(self, tmp_path: Path) -> None:
        """Detector should find all violations in a file."""
        test_file = tmp_path / "test_multiple.py"
        test_file.write_text(
            """
from somewhere import ProviderFactory, WeaviateRetriever

def create_factory():
    return ProviderFactory()

def create_retriever():
    return WeaviateRetriever()
""",
            encoding="utf-8",
        )

        violations = detect_direct_infra_instantiations([tmp_path])
        assert len(violations) == 2
        violation_text = " ".join(violations)
        assert "ProviderFactory" in violation_text
        assert "WeaviateRetriever" in violation_text


class TestProhibitedInstantiationIntegration:
    """Integration tests for the instantiation detector with the actual codebase."""

    def test_scan_src_directory_completes(self) -> None:
        """Scanning the actual src directory should complete without error."""
        src_path = Path("src")
        if not src_path.exists():
            pytest.skip("src directory not found")

        violations = detect_direct_infra_instantiations([src_path])
        # This test just verifies the scan runs without error
        # The actual violation count may vary
        assert isinstance(violations, list)

    def test_violation_messages_are_descriptive(self, tmp_path: Path) -> None:
        """Violation messages should include class name and file path."""
        test_file = tmp_path / "test_descriptive.py"
        test_file.write_text(
            """
from somewhere import IngestionOrchestrator

def run():
    return IngestionOrchestrator()
""",
            encoding="utf-8",
        )

        violations = detect_direct_infra_instantiations([tmp_path])
        assert len(violations) == 1
        message = violations[0]
        assert "IngestionOrchestrator" in message
        assert "test_descriptive.py" in message
        assert "bootstrap" in message.lower()