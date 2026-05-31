"""Tests for connected duplicate profile evidence."""

from pathlib import Path

from bpfw.core.catalog.duplicate_profile import (
    DuplicateProfileBuilder,
    code_unit_key_from_discovered_unit,
)
from bpfw.core.catalog.models import DiscoveredCodeUnit


def _unit(path: str, symbol: str, kind: str = "function") -> DiscoveredCodeUnit:
    """Create a minimal discovered unit for duplicate profile tests."""
    return DiscoveredCodeUnit(
        path=path,
        module=path.removesuffix(".py").replace("/", "."),
        symbol=symbol,
        symbol_type=kind,
        qualified_name=symbol,
        interface_inputs=[],
        interface_output={"type": "None"},
        calls=[],
    )


def test_wrapper_over_generic_file_writer_is_not_strong(tmp_path: Path) -> None:
    """Verify that wrappers over generic path writes do not block as strong duplicates."""
    source_path = tmp_path / "src" / "example.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "def save(path, text):\n"
        "    path.write_text(text)\n"
        "\n"
        "def run_save(path, text):\n"
        "    return save(path, text)\n",
        encoding="utf-8",
    )
    save_unit = _unit("src/example.py", "save")
    run_unit = _unit("src/example.py", "run_save")
    run_unit = DiscoveredCodeUnit(
        path=run_unit.path,
        module=run_unit.module,
        symbol=run_unit.symbol,
        symbol_type=run_unit.symbol_type,
        qualified_name=run_unit.qualified_name,
        interface_inputs=[],
        interface_output={"type": "None"},
        calls=[{"context": None, "name": "save"}],
    )

    profiles = DuplicateProfileBuilder(tmp_path, [save_unit, run_unit]).build()
    run_profile = profiles[code_unit_key_from_discovered_unit(run_unit)]

    assert run_profile.keys.hash_strength != "strong"


def test_attribute_provenance_prevents_bare_self_return_profile(tmp_path: Path) -> None:
    """Verify that return self.x can record where self.x is written."""
    source_path = tmp_path / "src" / "monitor.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "class Monitor:\n"
        "    def refresh(self):\n"
        "        self.ready = self.socket.is_connected()\n"
        "\n"
        "    def is_ready(self):\n"
        "        return self.ready\n",
        encoding="utf-8",
    )
    refresh_unit = _unit("src/monitor.py", "Monitor.refresh", "method")
    ready_unit = _unit("src/monitor.py", "Monitor.is_ready", "method")

    profiles = DuplicateProfileBuilder(tmp_path, [refresh_unit, ready_unit]).build()
    ready_profile = profiles[code_unit_key_from_discovered_unit(ready_unit)]

    assert "self.ready<-self.socket.is_connected()" in ready_profile.attributes.provenance
    assert ready_profile.keys.reason != "no useful duplicate signal"


def test_cache_entry_is_reused_when_fingerprint_matches(tmp_path: Path) -> None:
    """Verify that YAML cache can be reused after fingerprint validation."""
    source_path = tmp_path / "src" / "example.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("def save(path, text):\n    path.write_text(text)\n", encoding="utf-8")
    unit = _unit("src/example.py", "save")
    first_profiles = DuplicateProfileBuilder(tmp_path, [unit]).build()
    first_profile = first_profiles[code_unit_key_from_discovered_unit(unit)]
    cached_block = {
        "id": "save",
        "domain": "test",
        "status": "active",
        "code": {"path": unit.path, "symbol": unit.symbol, "kind": unit.symbol_type},
        "analysis": {"duplicate_profile": first_profile.to_dict()},
    }

    second_profiles = DuplicateProfileBuilder(tmp_path, [unit], blocks=[cached_block]).build()
    second_profile = second_profiles[code_unit_key_from_discovered_unit(unit)]

    assert second_profile.keys.duplicate_hash == first_profile.keys.duplicate_hash
    assert second_profile.source_fingerprint == first_profile.source_fingerprint


def _block(block_id: str, symbol: str, purpose: str) -> dict[str, object]:
    """Create a minimal active block for duplicate profile tests."""
    return {
        "id": block_id,
        "purpose": purpose,
        "domain": "test",
        "status": "active",
        "code": {"path": "src/example.py", "symbol": symbol, "kind": "function"},
    }


def test_identical_active_purposes_mark_blocks_as_duplicates(tmp_path: Path) -> None:
    """Verify that identical active purposes declare duplicate blocks."""
    source_path = tmp_path / "src" / "example.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "def first():\n"
        "    return 1\n"
        "\n"
        "def second():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    first_unit = _unit("src/example.py", "first")
    second_unit = _unit("src/example.py", "second")
    blocks = [
        _block("first", "first", "load configuration safely"),
        _block("second", "second", "load configuration safely"),
    ]

    profiles = DuplicateProfileBuilder(tmp_path, [first_unit, second_unit], blocks=blocks).build()
    first_profile = profiles[code_unit_key_from_discovered_unit(first_unit)]
    second_profile = profiles[code_unit_key_from_discovered_unit(second_unit)]

    assert first_profile.keys.duplicated == "yes"
    assert second_profile.keys.duplicated == "yes"
    assert first_profile.keys.hash_strength == "strong"
    assert first_profile.keys.reason == "two identical purposes"
    assert first_profile.keys.duplicate_hash == second_profile.keys.duplicate_hash


def test_identical_active_purposes_create_blocking_duplicate_finding(tmp_path: Path) -> None:
    """Verify that identical active purposes create a duplicate profile finding."""
    from bpfw.core.catalog.duplicate_profile import DuplicateActiveProfileRule

    source_path = tmp_path / "src" / "example.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "def first():\n"
        "    return 1\n"
        "\n"
        "def second():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    first_unit = _unit("src/example.py", "first")
    second_unit = _unit("src/example.py", "second")
    blocks = [
        _block("first", "first", "Load configuration safely"),
        _block("second", "second", "load   configuration safely"),
    ]

    profiles = DuplicateProfileBuilder(tmp_path, [first_unit, second_unit], blocks=blocks).build()
    findings = DuplicateActiveProfileRule().validate(blocks, profiles)

    assert len(findings) == 1
    assert findings[0].code == "DUPLICATE_ACTIVE_PROFILE"
    assert findings[0].evidence["reason"] == "two identical purposes"
    assert findings[0].evidence["duplicate_key"] == "purpose|load configuration safely"


def test_allowed_duplicate_profile_does_not_block(tmp_path: Path) -> None:
    """Verify that a declared false positive suppresses duplicate blocking."""
    from bpfw.core.catalog.duplicate_profile import DuplicateActiveProfileRule

    source_path = tmp_path / "src" / "example.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "def write_a(path, text):\n"
        "    path.write_text(text)\n"
        "\n"
        "def write_b(path, text):\n"
        "    path.write_text(text)\n",
        encoding="utf-8",
    )
    first_unit = _unit("src/example.py", "write_a")
    second_unit = _unit("src/example.py", "write_b")
    blocks = [
        _block("write_a", "write_a", "write first file"),
        _block("write_b", "write_b", "write second file"),
    ]

    profiles = DuplicateProfileBuilder(tmp_path, [first_unit, second_unit], blocks=blocks).build()
    first_profile = profiles[code_unit_key_from_discovered_unit(first_unit)]
    blocks[0]["duplicate_policy"] = {
        "allowed_active_duplicate_profiles": [
            {
                "duplicate_hash": first_profile.keys.duplicate_hash,
                "duplicate_key": first_profile.keys.duplicate_key,
                "reason": "separate write screens share the same technical pattern",
            }
        ]
    }

    findings = DuplicateActiveProfileRule().validate(blocks, profiles)
    enriched_profiles = DuplicateProfileBuilder(tmp_path, [first_unit, second_unit], blocks=blocks).build()
    enriched_profile = enriched_profiles[code_unit_key_from_discovered_unit(first_unit)]

    assert findings == []
    assert enriched_profile.keys.duplicated == "no"
    assert enriched_profile.keys.reason == "allowed duplicate profile"


def test_allowed_identical_purpose_does_not_block(tmp_path: Path) -> None:
    """Verify that allowed purpose duplicates do not block verification."""
    from bpfw.core.catalog.duplicate_profile import DuplicateActiveProfileRule

    source_path = tmp_path / "src" / "example.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "def first():\n"
        "    return 1\n"
        "\n"
        "def second():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    first_unit = _unit("src/example.py", "first")
    second_unit = _unit("src/example.py", "second")
    duplicate_key = "purpose|load configuration safely"
    blocks = [
        _block("first", "first", "load configuration safely"),
        _block("second", "second", "load configuration safely"),
    ]
    blocks[0]["duplicate_policy"] = {
        "allowed_active_duplicate_profiles": [
            {
                "duplicate_key": duplicate_key,
                "reason": "same purpose is intentional for this test",
            }
        ]
    }

    profiles = DuplicateProfileBuilder(tmp_path, [first_unit, second_unit], blocks=blocks).build()
    findings = DuplicateActiveProfileRule().validate(blocks, profiles)
    first_profile = profiles[code_unit_key_from_discovered_unit(first_unit)]

    assert findings == []
    assert first_profile.keys.duplicated == "no"
    assert first_profile.keys.reason == "allowed duplicate profile"


def test_weak_duplicate_profile_creates_review_warning(tmp_path: Path) -> None:
    """Verify that similar weak duplicate profiles warn without blocking."""
    from bpfw.core.catalog.duplicate_profile import DuplicateActiveProfileRule
    from bpfw.reports.finding import FINDING_SEVERITY_WARNING

    source_path = tmp_path / "src" / "example.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "def first(value):\n"
        "    return value + 1\n"
        "\n"
        "def second(value):\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    first_unit = _unit("src/example.py", "first")
    second_unit = _unit("src/example.py", "second")
    blocks = [
        _block("first", "first", "calculate first value"),
        _block("second", "second", "calculate second value"),
    ]

    profiles = DuplicateProfileBuilder(tmp_path, [first_unit, second_unit], blocks=blocks).build()
    findings = DuplicateActiveProfileRule().validate(blocks, profiles)

    assert len(findings) == 1
    assert findings[0].code == "DUPLICATE_PROFILE_REVIEW"
    assert findings[0].severity == FINDING_SEVERITY_WARNING
    assert findings[0].evidence["hash_strength"] == "weak"
