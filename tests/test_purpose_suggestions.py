"""Tests for purpose suggestion quality, stability, and terminology.

Validates that the suggestion engine produces semantically correct suggestions,
filters bad ones, handles legacy fields, and remains stable on repeated calls.
"""

import pytest

from bpfw.catalog.intent_suggestions import (
    IntentSuggestion,
    _apply_quality_filters,
    _NormalizedFacts,
    suggest_intents,
)


def _make_facts(
    symbol: str = "",
    symbol_type: str = "",
    symbol_tokens: tuple[str, ...] = (),
    path_tokens: tuple[str, ...] = (),
    module_tokens: tuple[str, ...] = (),
    signature_tokens: tuple[str, ...] = (),
    parameter_tokens: tuple[str, ...] = (),
    return_tokens: tuple[str, ...] = (),
    method_tokens: tuple[str, ...] = (),
    function_tokens: tuple[str, ...] = (),
    docstring_tokens: tuple[str, ...] = (),
    import_tokens: tuple[str, ...] = (),
    decorator_tokens: tuple[str, ...] = (),
    raw_functions: tuple[str, ...] = (),
    raw_methods: tuple[str, ...] = (),
    all_tokens: tuple[str, ...] | None = None,
) -> _NormalizedFacts:
    """Build a _NormalizedFacts instance for testing."""
    if all_tokens is None:
        all_tokens = symbol_tokens + path_tokens + module_tokens + docstring_tokens
    return _NormalizedFacts(
        symbol=symbol,
        symbol_type=symbol_type,
        symbol_tokens=symbol_tokens,
        path_tokens=path_tokens,
        module_tokens=module_tokens,
        signature_tokens=signature_tokens,
        parameter_tokens=parameter_tokens,
        return_tokens=return_tokens,
        method_tokens=method_tokens,
        function_tokens=function_tokens,
        docstring_tokens=docstring_tokens,
        import_tokens=import_tokens,
        decorator_tokens=decorator_tokens,
        raw_functions=raw_functions,
        raw_methods=raw_methods,
        all_tokens=all_tokens,
    )


# ---------------------------------------------------------------------------
# Test 1: ensure_blueprint_can_be_written produces correct suggestions
# ---------------------------------------------------------------------------


class TestEnsureBlueprintCanBeWritten:
    """Suggestions for a normal function should use the function verb, not Raise."""

    @pytest.fixture
    def block(self) -> dict:
        return {
            "name": "ensure_blueprint_can_be_written",
            "code": {
                "path": "src/bpfw/protection/authority.py",
                "module": "bpfw.protection.authority",
                "symbol": "ensure_blueprint_can_be_written",
                "kind": "function",
            },
            "detected": {
                "docstring": "Raise BlueprintLockedError if the authority file is locked.",
                "kind": "function",
                "qualified_name": "ensure_blueprint_can_be_written",
            },
        }

    def test_includes_ensure_based_suggestion(self, block: dict) -> None:
        suggestions = suggest_intents(block)
        texts = [s.text for s in suggestions if s.text not in {"-", "Write custom purpose..."}]
        assert any(
            "ensure" in text.lower() for text in texts
        ), f"No 'ensure' suggestion found in: {texts}"

    def test_does_not_suggest_raise_blueprint_locked_error(self, block: dict) -> None:
        suggestions = suggest_intents(block)
        texts = [s.text for s in suggestions]
        for forbidden in [
            "Raise blueprint locked error",
            "Raise ensure blueprint can",
            "Raise ensure blueprint can be",
        ]:
            assert forbidden not in texts, f"Forbidden suggestion found: {forbidden}"

    def test_no_suggestion_starts_with_raise(self, block: dict) -> None:
        suggestions = suggest_intents(block)
        non_placeholder = [
            s for s in suggestions if s.text not in {"-", "Write custom purpose..."}
        ]
        for suggestion in non_placeholder:
            assert not suggestion.text.startswith("Raise"), (
                f"Non-error block should not have Raise suggestion: {suggestion.text}"
            )


# ---------------------------------------------------------------------------
# Test 2: BlueprintLockedError as a class
# ---------------------------------------------------------------------------


class TestErrorClassSuggestions:
    """Error classes may suggest Define/Represent, not force Raise on others."""

    @pytest.fixture
    def block(self) -> dict:
        return {
            "name": "BlueprintLockedError",
            "code": {
                "path": "src/bpfw/core/errors.py",
                "module": "bpfw.core.errors",
                "symbol": "BlueprintLockedError",
                "kind": "class",
            },
            "detected": {
                "docstring": "Exception raised when a locked blueprint is accessed.",
                "kind": "class",
            },
        }

    def test_error_class_may_have_raise_suggestion(self, block: dict) -> None:
        suggestions = suggest_intents(block)
        texts = [s.text for s in suggestions if s.text not in {"-", "Write custom purpose..."}]
        # Error classes are allowed to have Raise suggestions
        assert len(texts) >= 1, f"Expected at least one suggestion, got: {texts}"


# ---------------------------------------------------------------------------
# Test 3: New YAML fields (code, purpose)
# ---------------------------------------------------------------------------


class TestNewYamlFields:
    """Suggestions should work with new canonical YAML fields."""

    @pytest.fixture
    def block(self) -> dict:
        return {
            "name": "load_blueprint_authority",
            "purpose": "",
            "domain": "catalog",
            "status": "active",
            "code": {
                "path": "src/bpfw/catalog/loader.py",
                "module": "bpfw.catalog.loader",
                "symbol": "load_blueprint_authority",
                "kind": "function",
            },
        }

    def test_suggestions_are_generated(self, block: dict) -> None:
        suggestions = suggest_intents(block)
        non_placeholder = [
            s for s in suggestions if s.text not in {"-", "Write custom purpose..."}
        ]
        assert len(non_placeholder) >= 1, "Expected at least one real suggestion"

    def test_suggestions_contain_load(self, block: dict) -> None:
        suggestions = suggest_intents(block)
        texts = [s.text for s in suggestions if s.text not in {"-", "Write custom purpose..."}]
        assert any(
            "load" in text.lower() for text in texts
        ), f"Expected 'load' in suggestions: {texts}"


# ---------------------------------------------------------------------------
# Test 4: Legacy YAML fields (location, intent, symbol_type)
# ---------------------------------------------------------------------------


class TestLegacyYamlFields:
    """Suggestions should work through legacy fallback fields."""

    @pytest.fixture
    def block(self) -> dict:
        return {
            "name": "scan_python_source",
            "intent": "",
            "domain": "catalog",
            "lifecycle": "active",
            "location": {
                "path": "src/bpfw/catalog/scanner.py",
                "module": "bpfw.catalog.scanner",
                "symbol": "scan_python_source",
                "symbol_type": "function",
            },
        }

    def test_suggestions_are_generated_via_legacy(self, block: dict) -> None:
        suggestions = suggest_intents(block)
        non_placeholder = [
            s for s in suggestions if s.text not in {"-", "Write custom purpose..."}
        ]
        assert len(non_placeholder) >= 1, "Legacy fields should still produce suggestions"

    def test_suggestions_contain_scan(self, block: dict) -> None:
        suggestions = suggest_intents(block)
        texts = [s.text for s in suggestions if s.text not in {"-", "Write custom purpose..."}]
        assert any(
            "scan" in text.lower() for text in texts
        ), f"Expected 'scan' in suggestions: {texts}"


# ---------------------------------------------------------------------------
# Test 5: Quality filter rejects incomplete suggestions
# ---------------------------------------------------------------------------


class TestQualityFilter:
    """The quality filter should reject suggestions ending in incomplete words."""

    @pytest.fixture
    def facts(self) -> _NormalizedFacts:
        return _make_facts(
            symbol="ensure_blueprint_can_be_written",
            symbol_tokens=("ensure", "blueprint", "can", "be", "written"),
            docstring_tokens=("raise", "blueprint", "locked", "error"),
        )

    def test_rejects_ending_with_can(self, facts: _NormalizedFacts) -> None:
        suggestions = [
            IntentSuggestion(text="Ensure blueprint can", source="test", evidence=()),
            IntentSuggestion(text="Write custom purpose...", source="custom", evidence=()),
        ]
        filtered = _apply_quality_filters(suggestions, facts)
        texts = [s.text for s in filtered]
        assert "Ensure blueprint can" not in texts

    def test_rejects_ending_with_be(self, facts: _NormalizedFacts) -> None:
        suggestions = [
            IntentSuggestion(text="Ensure blueprint can be", source="test", evidence=()),
        ]
        filtered = _apply_quality_filters(suggestions, facts)
        texts = [s.text for s in filtered]
        assert "Ensure blueprint can be" not in texts

    def test_accepts_complete_suggestion(self, facts: _NormalizedFacts) -> None:
        suggestions = [
            IntentSuggestion(
                text="Ensure blueprint can be written", source="test", evidence=()
            ),
        ]
        filtered = _apply_quality_filters(suggestions, facts)
        assert len(filtered) == 1
        assert filtered[0].text == "Ensure blueprint can be written"

    def test_rejects_raise_for_non_error_block(self, facts: _NormalizedFacts) -> None:
        suggestions = [
            IntentSuggestion(
                text="Raise blueprint locked error", source="test", evidence=()
            ),
        ]
        filtered = _apply_quality_filters(suggestions, facts)
        texts = [s.text for s in filtered]
        assert "Raise blueprint locked error" not in texts

    def test_passes_through_placeholders(self, facts: _NormalizedFacts) -> None:
        suggestions = [
            IntentSuggestion(text="-", source="existing", evidence=()),
            IntentSuggestion(
                text="Write custom purpose...", source="custom", evidence=()
            ),
        ]
        filtered = _apply_quality_filters(suggestions, facts)
        texts = [s.text for s in filtered]
        assert "-" in texts
        assert "Write custom purpose..." in texts

    def test_rejects_duplicate_words(self, facts: _NormalizedFacts) -> None:
        suggestions = [
            IntentSuggestion(
                text="Ensure ensure blueprint written", source="test", evidence=()
            ),
        ]
        filtered = _apply_quality_filters(suggestions, facts)
        texts = [s.text for s in filtered]
        assert "Ensure ensure blueprint written" not in texts

    def test_rejects_short_suggestions(self, facts: _NormalizedFacts) -> None:
        suggestions = [
            IntentSuggestion(text="Validate", source="test", evidence=()),
            IntentSuggestion(text="Write code", source="test", evidence=()),
        ]
        filtered = _apply_quality_filters(suggestions, facts)
        texts = [s.text for s in filtered]
        assert "Validate" not in texts
        assert "Write code" not in texts


# ---------------------------------------------------------------------------
# Test 6: Stability - same block produces same suggestions
# ---------------------------------------------------------------------------


class TestSuggestionStability:
    """Repeated calls for the same block should return identical suggestions."""

    @pytest.fixture
    def block(self) -> dict:
        return {
            "name": "ensure_blueprint_can_be_written",
            "code": {
                "path": "src/bpfw/protection/authority.py",
                "module": "bpfw.protection.authority",
                "symbol": "ensure_blueprint_can_be_written",
                "kind": "function",
            },
            "detected": {
                "docstring": "Raise BlueprintLockedError if locked.",
                "kind": "function",
            },
        }

    def test_repeated_calls_return_same_suggestions(self, block: dict) -> None:
        first = suggest_intents(block)
        second = suggest_intents(block)
        first_texts = [s.text for s in first]
        second_texts = [s.text for s in second]
        assert first_texts == second_texts, (
            f"Suggestions changed between calls:\n  first:  {first_texts}\n  second: {second_texts}"
        )

    def test_suggestions_deterministic_across_instances(self, block: dict) -> None:
        results = [suggest_intents(block) for _ in range(5)]
        reference = [s.text for s in results[0]]
        for index, result in enumerate(results[1:], 1):
            texts = [s.text for s in result]
            assert texts == reference, (
                f"Call {index} differs from reference:\n  ref: {reference}\n  got: {texts}"
            )