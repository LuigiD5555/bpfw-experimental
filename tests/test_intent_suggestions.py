"""Tests for deterministic natural-language intent suggestions."""

from typing import Any

from bpfw.catalog.intent_suggestions import compact_intent_text, suggest_intents


def test_suggests_token_creation_from_issuer_symbol() -> None:
    """Suggest token creation from an issuer-style class name."""

    responsibility = {
        "canonical_name": "TokenIssuer",
        "location": {
            "path": "src/auth/token.py",
            "symbol": "TokenIssuer",
            "symbol_type": "class",
        },
        "detected": {
            "methods": ["issue_token"],
            "signature": "issue_token(self, user_id: str) -> str",
        },
    }

    suggestions = suggest_intents(responsibility)

    assert suggestions
    assert any("token" in suggestion.text.lower() for suggestion in suggestions)


def test_suggests_blueprint_validation_from_verify_symbol() -> None:
    """Suggest blueprint validation from verify-style evidence."""

    responsibility = {
        "canonical_name": "verify_blueprint",
        "location": {
            "path": "src/bpfw/catalog/verify.py",
            "symbol": "verify_blueprint",
            "symbol_type": "function",
        },
        "detected": {
            "signature": "verify_blueprint(project_root: Path) -> VerificationResult",
            "functions": ["load_blueprint", "scan_python_project", "compare_responsibilities"],
        },
    }

    suggestions = suggest_intents(responsibility)

    assert suggestions
    assert suggestions[4].text == "Validate blueprint declarations against detected"


def test_suggests_loading_blueprint_authority_from_disk() -> None:
    """Suggest loading blueprint authority from disk."""

    responsibility = _responsibility(
        symbol="load_blueprint",
        path="src/bpfw/catalog/loader.py",
        signature="load_blueprint(path: Path) -> Blueprint",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Load blueprint authority from disk"


def test_suggests_scanning_python_source_files() -> None:
    """Suggest scanning Python source files for declared code units."""

    responsibility = _responsibility(
        symbol="scan_python_files",
        path="src/bpfw/catalog/scanner.py",
        signature="scan_python_files(project_root: Path) -> list[CodeUnit]",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Scan Python source files for"


def test_suggests_project_verification_against_detected_source_code() -> None:
    """Suggest blueprint validation against detected source code."""

    responsibility = _responsibility(
        symbol="verify_project",
        path="src/bpfw/catalog/verify.py",
        signature="verify_project(project_root: Path) -> VerificationResult",
        functions=["load_blueprint", "scan_project", "compare_responsibilities"],
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Validate blueprint declarations against detected"


def test_suggests_writing_blueprint_authority_changes_to_disk() -> None:
    """Suggest writing blueprint authority changes to disk."""

    responsibility = _responsibility(
        symbol="save_blueprint",
        path="src/bpfw/catalog/writer.py",
        signature="save_blueprint(blueprint: Blueprint, path: Path) -> None",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Write blueprint authority changes to"


def test_suggests_detecting_duplicate_active_responsibilities() -> None:
    """Suggest detecting duplicate active responsibilities by intent."""

    responsibility = _responsibility(
        symbol="find_duplicate_intents",
        path="src/bpfw/catalog/drift.py",
        signature=(
            "find_duplicate_intents("
            "responsibilities: list[Responsibility]"
            ") -> list[DuplicateGroup]"
        ),
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Detect duplicate active responsibilities by"


def test_suggests_protecting_authority_files() -> None:
    """Suggest protecting authority files from direct modification."""

    responsibility = _responsibility(
        symbol="lock_authority_file",
        path="src/bpfw/protection/os_lock.py",
        signature="lock_authority_file(path: Path) -> LockResult",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Protect authority files from direct"


def test_suggests_running_blueprint_verification_from_command_line() -> None:
    """Suggest running blueprint verification from the command line."""

    responsibility = _responsibility(
        symbol="handle_verify_command",
        path="src/bpfw/cli.py",
        signature="handle_verify_command(args: list[str]) -> int",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Run blueprint verification from the"


def test_suggests_intent_from_intent_suggestion_dataclass() -> None:
    """Suggest intent suggestions from the dataclass evidence."""

    responsibility = _responsibility(
        symbol="IntentSuggestion",
        path="src/bpfw/catalog/intent_suggestions.py",
        symbol_type="class",
        docstring="Represent one deterministic natural-language intent suggestion.",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Suggest intent"


def test_suggests_richer_intent_for_suggest_intents_function() -> None:
    """Suggest the public suggester behavior from function evidence."""

    responsibility = _responsibility(
        symbol="suggest_intents",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="suggest_intents(responsibility: dict[str, Any]) -> list[IntentSuggestion]",
        docstring="Suggest natural-language intents from deterministic responsibility evidence.",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Suggest intents"


def test_suggests_collecting_responsibility_evidence() -> None:
    """Suggest evidence collection rather than scanning evidence text."""

    responsibility = _responsibility(
        symbol="collect_evidence_text",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="collect_evidence_text(responsibility: dict[str, Any]) -> str",
        docstring="Collect deterministic text evidence from one responsibility dictionary.",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Collect evidence text"
    assert all("Scan evidence text" != suggestion.text for suggestion in suggestions)


def test_suggests_normalizing_technical_evidence_tokens() -> None:
    """Suggest token normalization from tokenizer evidence."""

    responsibility = _responsibility(
        symbol="tokenize_evidence",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="tokenize_evidence(text: str) -> list[str]",
        docstring="Convert technical names and text evidence into normalized tokens.",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Normalize technical evidence tokens"


def test_suggests_composing_intent_sentence_candidates() -> None:
    """Suggest candidate composition from compose function evidence."""

    responsibility = _responsibility(
        symbol="compose_candidates",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="compose_candidates(...) -> list[_Candidate]",
        docstring="Compose deterministic intent sentence candidates.",
    )

    suggestions = suggest_intents(responsibility)

    assert suggestions[4].text == "Build intent candidates"


def test_returns_empty_slots_for_generic_low_evidence_symbol() -> None:
    """Use placeholders for generic low-evidence snippets."""

    responsibility = _responsibility(
        symbol="Helper",
        path="src/bpfw/catalog/helper.py",
        symbol_type="class",
    )

    suggestions = suggest_intents(responsibility)

    assert len(suggestions) == 6
    assert suggestions[0].text == "-"
    assert suggestions[5].text == "Write custom intent..."


def test_suggestions_do_not_duplicate_action_words() -> None:
    """Avoid duplicate action/object phrases."""

    cases = [
        _responsibility(
            symbol="load_blueprint",
            path="src/bpfw/catalog/loader.py",
            signature="load_blueprint(path: Path) -> Blueprint",
        ),
        _responsibility(
            symbol="save_blueprint",
            path="src/bpfw/catalog/writer.py",
            signature="save_blueprint(blueprint: Blueprint, path: Path) -> None",
        ),
        _responsibility(
            symbol="handle_verify_command",
            path="src/bpfw/cli.py",
            signature="handle_verify_command(args: list[str]) -> int",
        ),
    ]

    texts = [suggest_intents(responsibility)[4].text for responsibility in cases]

    assert all("Load load" not in text for text in texts)
    assert all("Write save" not in text for text in texts)
    assert all("Handle handle" not in text for text in texts)


def test_suggest_intents_returns_fixed_slots_when_evidence_is_sufficient() -> None:
    responsibility = _responsibility(
        symbol="suggest_intents",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="suggest_intents(responsibility: dict[str, Any]) -> list[IntentSuggestion]",
        docstring="Suggest natural-language intents from deterministic responsibility evidence.",
    )

    suggestions = suggest_intents(responsibility)

    assert len(suggestions) == 6
    assert suggestions[4].text == "Suggest intents"


def test_suggest_intents_keeps_specific_template_as_first_option() -> None:
    responsibility = _responsibility(
        symbol="collect_evidence_text",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="collect_evidence_text(responsibility: dict[str, Any]) -> str",
        docstring="Collect deterministic text evidence from one responsibility dictionary.",
    )

    suggestions = suggest_intents(responsibility)
    assert suggestions[4].text == "Collect evidence text"


def test_suggest_intents_does_not_return_duplicate_variants() -> None:
    responsibility = _responsibility(
        symbol="suggest_intents",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="suggest_intents(responsibility: dict[str, Any]) -> list[IntentSuggestion]",
        docstring="Suggest natural-language intents from deterministic responsibility evidence.",
    )

    suggestions = suggest_intents(responsibility)
    texts = [suggestion.text for suggestion in suggestions]
    assert len(texts) == len(set(texts))


def test_compact_intent_text_removes_responsibility_evidence_context() -> None:
    assert (
        compact_intent_text("Suggest natural-language intents from responsibility evidence")
        == "Suggest intents"
    )


def test_compact_intent_text_converts_produce_ranked_to_rank() -> None:
    assert (
        compact_intent_text("Produce ranked intent suggestions from responsibility evidence")
        == "Rank intent suggestions"
    )


def test_compact_intent_text_limits_word_count() -> None:
    result = compact_intent_text(
        "Collect deterministic text evidence from one responsibility dictionary"
    )
    assert len(result.split()) <= 5
    assert result == "Collect evidence text"


def test_suggest_intents_returns_compact_options() -> None:
    responsibility = _responsibility(
        symbol="suggest_intents",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="suggest_intents(responsibility: dict[str, Any]) -> list[IntentSuggestion]",
        docstring="Suggest natural-language intents from deterministic responsibility evidence.",
    )
    suggestions = suggest_intents(responsibility)
    texts = [suggestion.text for suggestion in suggestions]
    assert "Suggest intents" in texts
    assert all(len(text.split()) <= 5 for text in texts)
    assert all("responsibility evidence" not in text.lower() for text in texts)


def test_suggest_intents_returns_six_fixed_options() -> None:
    responsibility = _responsibility(
        symbol="verify_project",
        path="src/bpfw/catalog/verify.py",
        signature="verify_project(project_root: Path) -> VerificationResult",
        functions=["load_blueprint", "scan_project", "compare_responsibilities"],
        docstring="Validate blueprint declarations against detected source code.",
    )

    suggestions = suggest_intents(responsibility)
    assert len(suggestions) == 6
    assert all(len(suggestion.text.split()) <= 5 for suggestion in suggestions)


def test_suggest_intents_generalizes_for_non_catalog_snippet() -> None:
    responsibility = _responsibility(
        symbol="issue_access_token",
        path="src/auth/jwt_tokens.py",
        signature="issue_access_token(user_id: str, ttl_seconds: int) -> str",
        docstring="Create and sign JWT access tokens.",
    )

    suggestions = suggest_intents(responsibility)
    texts = [suggestion.text.lower() for suggestion in suggestions]
    assert suggestions
    assert all("intent candidates" not in text for text in texts)


def test_intent_suggestions_include_distinct_sources_when_evidence_is_sufficient() -> None:
    responsibility = _responsibility(
        symbol="suggest_intents",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="suggest_intents(responsibility: dict[str, Any]) -> list[IntentSuggestion]",
        functions=["compose_fixed_intent_slots"],
        docstring="Suggest natural-language intents from deterministic responsibility evidence.",
    )
    suggestions = suggest_intents(
        responsibility,
        existing_intents=("Suggest intents", "Collect evidence text"),
    )
    source_tags = {
        evidence_item
        for suggestion in suggestions
        for evidence_item in suggestion.evidence
        if evidence_item.startswith("source:")
    }
    assert source_tags == {
        "source: existing_intent",
        "source: learned_based",
        "source: name_based",
        "source: docstring_based",
        "source: blended_based",
        "source: custom_intent",
    }


def test_existing_intent_based_candidate_appears_when_similar_intent_exists() -> None:
    responsibility = _responsibility(
        symbol="collect_evidence_text",
        path="src/bpfw/catalog/intent_suggestions.py",
        signature="collect_evidence_text(responsibility: dict[str, Any]) -> str",
        docstring="Collect deterministic text evidence from one responsibility dictionary.",
    )
    existing = ("Collect evidence text", "Run project verification")
    suggestions = suggest_intents(responsibility, existing_intents=existing)
    assert any(suggestion.text == "Collect evidence text" for suggestion in suggestions)


def test_intent_suggestions_keep_fixed_slot_order() -> None:
    """Intent suggestions must keep stable inspector slot order."""

    responsibility = {
        "location": {
            "path": "src/bpfw/protection/authority.py",
            "symbol": "AuthorityValidator",
            "symbol_type": "class",
        },
        "detected": {
            "docstring": "Validate blueprint authority declarations.",
            "signature": "class AuthorityValidator",
        },
    }
    suggestions = suggest_intents(
        responsibility,
        existing_intents=("Validate blueprint authority",),
    )
    assert [item.source for item in suggestions] == [
        "existing_intent",
        "learned_based",
        "name_based",
        "docstring_based",
        "blended_based",
        "custom_intent",
    ]


def test_missing_intent_sources_render_as_placeholders() -> None:
    """Missing intent sources must render placeholders without changing slot order."""

    responsibility = {
        "location": {
            "path": "src/example.py",
            "symbol": "Thing",
            "symbol_type": "class",
        }
    }
    suggestions = suggest_intents(responsibility)
    assert len(suggestions) == 6
    assert suggestions[0].source == "existing_intent"
    assert suggestions[-1].source == "custom_intent"


def _responsibility(
    symbol: str,
    path: str,
    signature: str | None = None,
    symbol_type: str = "function",
    functions: list[str] | None = None,
    methods: list[str] | None = None,
    docstring: str | None = None,
) -> dict[str, Any]:
    """Build a detected responsibility fixture."""

    detected: dict[str, Any] = {
        "qualified_name": symbol,
        "kind": symbol_type,
        "methods": methods or [],
        "functions": functions or [],
        "imports": [],
        "decorators": [],
    }
    if signature is not None:
        detected["signature"] = signature
    if docstring is not None:
        detected["docstring"] = docstring

    return {
        "canonical_name": symbol,
        "location": {
            "path": path,
            "module": path.removesuffix(".py").replace("/", "."),
            "symbol": symbol,
            "symbol_type": symbol_type,
        },
        "detected": detected,
    }
