"""Tests for deterministic semantic purpose suggestions."""

from typing import Any

from bpfw.integrations.inspector.suggestions.purpose.engine import suggest_purposes


def _responsibility(
    symbol: str,
    path: str,
    signature: str | None = None,
    symbol_type: str = "function",
    docstring: str | None = None,
) -> dict[str, Any]:
    detected: dict[str, Any] = {
        "qualified_name": symbol,
        "kind": symbol_type,
        "methods": [],
        "functions": [],
        "imports": [],
        "decorators": [],
    }
    if signature is not None:
        detected["signature"] = signature
    if docstring is not None:
        detected["docstring"] = docstring

    return {
        "name": symbol,
        "code": {
            "path": path,
            "module": path.removesuffix(".py").replace("/", "."),
            "symbol": symbol,
            "kind": symbol_type,
        },
        "detected": detected,
    }


def test_authority_index_save_semantic_slots() -> None:
    block = _responsibility(
        symbol="AuthorityIndex.save",
        path="src/bpfw/catalog/authority.py",
        signature="save(self, project_root: Path) -> None",
        docstring=(
            "Save the authority index to the project root. "
            "Args: project_root: The project root directory. "
            "Raises: InvalidAuthorityIndexError: If the index is invalid."
        ),
    )

    suggestions = suggest_purposes(block)
    texts = [item.text for item in suggestions]

    assert suggestions[2].text == "save authority index"
    assert suggestions[3].text == "save authority index to project root"
    assert all("invalid" not in text for text in texts)
    assert all("get project root" not in text for text in texts)
    assert all("load authority index" not in text for text in texts)


def test_existing_purpose_compatibility_reuses_matching_purpose() -> None:
    block = _responsibility(symbol="AuthorityIndex.save", path="src/bpfw/catalog/authority.py")
    suggestions = suggest_purposes(
        block,
        existing_purposes=("get project root", "load authority index", "save authority index"),
    )
    assert suggestions[0].text == "save authority index"


def test_existing_purpose_rejects_incompatible_action() -> None:
    block = _responsibility(symbol="AuthorityIndex.save", path="src/bpfw/catalog/authority.py")
    suggestions = suggest_purposes(block, existing_purposes=("load authority index",))
    assert suggestions[0].text == "-"


def test_existing_purpose_accepts_normalized_compatible_action() -> None:
    block = _responsibility(symbol="AuthorityIndex.save", path="src/bpfw/catalog/authority.py")
    suggestions = suggest_purposes(block, existing_purposes=("persist authority index",))
    assert suggestions[0].text == "persist authority index"


def test_symbol_method_uses_class_context() -> None:
    block = _responsibility(symbol="AuthorityIndex.save", path="src/bpfw/catalog/authority.py")
    suggestions = suggest_purposes(block)
    assert suggestions[2].text == "save authority index"


def test_symbol_function_uses_function_name() -> None:
    block = _responsibility(symbol="validate_blueprint_schema", path="src/bpfw/catalog/schema.py")
    suggestions = suggest_purposes(block)
    assert suggestions[2].text == "validate blueprint schema"


def test_docstring_uses_first_sentence_only() -> None:
    block = _responsibility(
        symbol="AuthorityIndex.save",
        path="src/bpfw/catalog/authority.py",
        docstring=(
            "Save the authority index to the project root. "
            "Raises: InvalidAuthorityIndexError: If the index is invalid."
        ),
    )
    suggestions = suggest_purposes(block)
    assert suggestions[3].text == "save authority index to project root"
    assert all("invalid" not in suggestion.text for suggestion in suggestions)


def test_learned_purpose_uses_compatibility_order(monkeypatch: Any) -> None:
    block = _responsibility(symbol="AuthorityIndex.save", path="src/bpfw/catalog/authority.py")
    monkeypatch.setattr(
        "bpfw.integrations.inspector.suggestions.purpose.engine.get_learned_purposes",
        lambda: ["load authority index", "persist authority index"],
    )
    suggestions = suggest_purposes(block)
    assert suggestions[1].text == "persist authority index"


def test_no_hardcoded_authority_example_behavior() -> None:
    block = _responsibility(
        symbol="CacheStore.persist",
        path="src/bpfw/cache/store.py",
        docstring="Persist the cache store to disk.",
    )
    suggestions = suggest_purposes(block)
    assert suggestions[2].text == "save cache store"
    assert suggestions[3].text == "save cache store to disk"


def test_symbol_alias_normalization_build_maps_to_create() -> None:
    block = _responsibility(symbol="BlueprintFactory.build", path="src/bpfw/factory.py")
    suggestions = suggest_purposes(block)
    assert suggestions[2].text == "create blueprint factory"


def test_docstring_alias_normalization_verify_maps_to_validate() -> None:
    block = _responsibility(
        symbol="SchemaInspector.inspect",
        path="src/bpfw/schema/inspector.py",
        docstring="Verify the blueprint schema for project compatibility.",
    )
    suggestions = suggest_purposes(block)
    assert suggestions[3].text == "validate blueprint schema to project compatibility"


def test_existing_purpose_accepts_modify_alias_from_update() -> None:
    block = _responsibility(symbol="BlueprintConfig.modify", path="src/bpfw/config.py")
    suggestions = suggest_purposes(block, existing_purposes=("update blueprint config",))
    assert suggestions[0].text == "update blueprint config"


def test_fixed_slots_and_custom_slot() -> None:
    block = _responsibility(symbol="Thing", path="src/example.py", symbol_type="class")
    suggestions = suggest_purposes(block)
    assert len(suggestions) == 6
    assert suggestions[5].text == "write custom purpose"


def test_deduplication_keeps_earliest_slot() -> None:
    block = _responsibility(symbol="AuthorityIndex.save", path="src/bpfw/catalog/authority.py")
    suggestions = suggest_purposes(block, existing_purposes=("save authority index",))
    assert suggestions[0].text == "save authority index"
    assert suggestions[2].text == "-"


def test_existing_purpose_relaxed_lookup_overlap_surfaces_near_match() -> None:
    block = _responsibility(
        symbol="AuthorityDocument.get_included_shard_paths",
        path="src/bpfw/authority/document.py",
    )
    suggestions = suggest_purposes(block, existing_purposes=("return all shard paths",))
    assert suggestions[0].text == "return all shard paths"


def test_learned_purpose_relaxed_lookup_overlap_surfaces_near_match(monkeypatch: Any) -> None:
    block = _responsibility(
        symbol="AuthorityDocument.get_included_shard_paths",
        path="src/bpfw/authority/document.py",
    )
    monkeypatch.setattr(
        "bpfw.integrations.inspector.suggestions.purpose.engine.get_learned_purposes",
        lambda: ["return list included shard paths"],
    )
    suggestions = suggest_purposes(block)
    assert suggestions[1].text == "return list included shard paths"
