"""Behavior and scalability regressions for project verification and history."""

import ast
from unittest.mock import patch

import yaml
from pytest_readable import readable

from bpfw.core.artifacts.resolver import ArtifactResolver
from bpfw.core.catalog.verify import scan_project_from_blueprint
from bpfw.core.catalog.drift import compare_declared_to_discovered
from bpfw.core.history.ledger import HistoryLedger, capture_artifact_state


@readable(
    intention="Resolve qualified Python methods without selecting another class.",
    steps=["Resolve two identically named methods with deliberately misleading stored locations."],
    criteria=["Each qualified method resolves to its actual source span."],
)
def test_qualified_python_methods_use_the_declared_owner(tmp_path):
    (tmp_path / "sample.py").write_text(
        "class First:\n    def save(self):\n        return 'first'\n\n"
        "class Second:\n    def save(self):\n        return 'second'\n"
    )
    resolver = ArtifactResolver(tmp_path)
    first = resolver.resolve({"path": "sample.py", "symbol": "First.save", "kind": "method", "start_line": 6})
    second = resolver.resolve({"path": "sample.py", "symbol": "Second.save", "kind": "method", "start_line": 2})
    missing = resolver.resolve({"path": "sample.py", "symbol": "Missing.save", "kind": "method"})
    assert (first.resolution, first.start_line, first.end_line) == ("EXACT", 2, 3)
    assert (second.resolution, second.start_line, second.end_line) == ("EXACT", 6, 7)
    assert missing.resolution == "UNRESOLVED"


@readable(
    intention="Parse a Python file once while resolving its distinct artifacts.",
    steps=["Resolve every function from a file with many functions."],
    criteria=["All functions resolve exactly and the parser runs once."],
)
def test_python_artifacts_share_one_parsed_file(tmp_path):
    (tmp_path / "sample.py").write_text("".join(
        f"def function_{number}():\n    return {number}\n" for number in range(80)
    ))
    resolver = ArtifactResolver(tmp_path)
    with patch("bpfw.core.catalog.source_repository.ast.parse", wraps=ast.parse) as parse:
        results = [resolver.resolve({"path": "sample.py", "symbol": f"function_{number}", "kind": "function"})
                   for number in range(80)]
    assert all(result.resolution == "EXACT" for result in results)
    assert [result.start_line for result in results] == list(range(1, 160, 2))
    assert parse.call_count == 1


@readable(
    intention="Share one grammar parse across the elements of an HTML template.",
    steps=["Resolve all extracted HTML symbols from the same template."],
    criteria=["Every element resolves exactly and extraction runs once."],
)
def test_html_artifacts_share_one_grammar_parse(tmp_path):
    from bpfw.core.source.tree_sitter_adapter import extract_units

    path = tmp_path / "sample.html"
    path.write_text("<section><h1>Title</h1><p>Body</p></section>")
    units, errors = extract_units("html", path, path.relative_to(tmp_path))
    assert not errors and len(units) > 1
    resolver = ArtifactResolver(tmp_path)
    with patch("bpfw.core.source.tree_sitter_adapter.extract_units", wraps=extract_units) as extract:
        results = [resolver.resolve({"path": "sample.html", "symbol": unit.symbol, "kind": unit.symbol_type})
                   for unit in units]
    assert all(result.resolution == "EXACT" for result in results)
    assert extract.call_count == 1


@readable(
    intention="Keep template branches with repeated HTML IDs addressable independently.",
    steps=["Extract repeated IDs and their descendants inside conditional template branches."],
    criteria=["Every unit has a unique identity and descendants retain the correct owner."],
)
def test_conditional_html_ids_have_distinct_native_identities(tmp_path):
    from bpfw.core.source.tree_sitter_adapter import extract_units

    path = tmp_path / "sample.html"
    path.write_text("<section>{% if ready %}<div id='action'><b>Ready</b></div>"
                    "{% else %}<div id='action'><b>Pending</b></div>{% endif %}</section>")
    units, errors = extract_units("html", path, path.relative_to(tmp_path))
    assert not errors
    assert len({unit.canonical_id for unit in units}) == len(units)
    containers = [unit for unit in units if unit.symbol.rsplit("/", 1)[-1].startswith("div#action[")]
    children = [unit for unit in units if unit.symbol.endswith("/b[1]")]
    assert len(containers) == len(children) == 2
    assert {unit.parent_unit_id for unit in children} == {unit.canonical_id for unit in containers}


@readable(
    intention="Honor explicit private and exception declarations without weakening missing-code checks.",
    steps=["Scan a catalog declaring a private function, exception, missing function and wrong symbol kind."],
    criteria=["Existing declarations resolve; missing and mismatched declarations still block."],
)
def test_explicit_filtered_python_declarations_are_discovered(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "sample.py").write_text(
        "class DomainError(ValueError):\n    pass\n\n"
        "def _private():\n    return 1\n\n"
        "def public():\n    return 2\n"
    )
    blueprint = {"project": {"source_roots": ["src"]}, "blocks": [
        {"id": symbol, "code": {"path": "src/sample.py", "symbol": symbol, "kind": kind}}
        for symbol, kind in [("DomainError", "class"), ("_private", "function"),
                             ("missing", "function"), ("public", "class")]
    ]}
    scan = scan_project_from_blueprint(tmp_path, blueprint)
    findings = compare_declared_to_discovered(blueprint, scan.discovered_units, "defined")
    assert {finding.symbol for finding in findings if finding.code == "MISSING_DECLARED_CODE"} == {"missing", "public"}
    assert {unit.symbol for unit in scan.discovered_units} >= {"DomainError", "_private", "public"}


@readable(
    intention="Do not expand the configured source scope for an explicit declaration.",
    steps=["Declare a private function from an ignored directory and one outside the source roots."],
    criteria=["Both remain missing from the permitted scan."],
)
def test_explicit_declarations_respect_source_scope(tmp_path):
    for directory in ("src/ignored", "outside"):
        path = tmp_path / directory
        path.mkdir(parents=True)
        (path / "sample.py").write_text("def _private():\n    return 1\n")
    blueprint = {"project": {"source_roots": ["src"], "ignored_paths": ["ignored"]}, "blocks": [
        {"code": {"path": directory + "/sample.py", "symbol": "_private", "kind": "function"}}
        for directory in ("src/ignored", "outside")
    ]}
    assert not scan_project_from_blueprint(tmp_path, blueprint).discovered_units


@readable(
    intention="Capture artifact history once per verification command.",
    steps=["Verify a project twice, exercising fresh and cached reports."],
    criteria=["Each command captures history exactly once and keeps its verification result."],
)
def test_verify_cli_captures_history_once(tmp_path, monkeypatch, capsys):
    import sys
    from bpfw.cli import main

    (tmp_path / "src").mkdir()
    (tmp_path / "src/sample.py").write_text("def run():\n    return 1\n")
    (tmp_path / ".bpfw").mkdir()
    (tmp_path / ".bpfw/blueprint.yaml").write_text(yaml.safe_dump({
        "version": 1, "project": {"name": "test", "source_roots": ["src"]},
        "blocks": [{"id": "run", "domain": "core", "purpose": "Return the sample value.", "status": "active",
                    "code": {"path": "src/sample.py", "symbol": "run", "kind": "function"}}],
    }))
    for _attempt in range(2):
        monkeypatch.setattr(sys, "argv", ["bpfw", "verify", "--project-root", str(tmp_path)])
        with patch("bpfw.core.history.ledger.capture_artifact_state", return_value=[]) as capture:
            assert main() == 0
        assert capture.call_count == 1
    assert "Traceback" not in capsys.readouterr().out


@readable(
    intention="Record artifact history with one Git snapshot per capture.",
    steps=["Capture several artifacts, then capture their unchanged state again."],
    criteria=["Every initial artifact is recorded, unchanged artifacts add no events and Git work is bounded."],
)
def test_history_capture_batches_git_context_and_keeps_all_events(tmp_path):
    (tmp_path / "sample.py").write_text("".join(
        f"def function_{number}():\n    return {number}\n" for number in range(12)
    ))
    blueprint = {"blocks": [
        {"id": f"block_{number}", "code": {"path": "sample.py", "symbol": f"function_{number}", "kind": "function"}}
        for number in range(12)
    ]}
    with patch.object(HistoryLedger, "git_context", return_value={"branch": "test"}) as context:
        events = capture_artifact_state(tmp_path, blueprint)
    assert len(events) == 12
    assert all(event["git"]["branch"] == "test" for event in events)
    assert context.call_count == 2
    with patch.object(HistoryLedger, "git_context", return_value={"branch": "test"}) as context:
        assert capture_artifact_state(tmp_path, blueprint) == []
    assert context.call_count == 1
