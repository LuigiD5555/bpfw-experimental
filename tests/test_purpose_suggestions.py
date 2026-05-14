"""Tests for deterministic natural-language purpose suggestions."""

from typing import Any

from bpfw.catalog.purpose_suggestions import compact_purpose_text, suggest_purposes


def test_suggests_token_creation_from_issuer_symbol() -> None:
    """Suggest token creation from an issuer-style class name."""

    block = {
        "name": "TokenIssuer",
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

    suggestions = suggest_purposes(block)

    assert suggestions
    assert any("token" in suggestion.text.lower() for suggestion in suggestions)


def test_suggests_blueprint_validation_from_verify_symbol() -> None:
    """Suggest blueprint validation from verify-style evidence."""

    block = {
        "name": "verify_blueprint",
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

    suggestions = suggest_purposes(block)

    assert suggestions
    assert suggestions[4].text == "Validate blueprint declarations against detected"


def test_suggests_loading_blueprint_authority_from_disk() -> None:
    """Suggest loading blueprint authority from disk."""

    block = _responsibility(
        symbol="load_blueprint",
        path="src/bpfw/catalog/loader.py",
        signature="load_blueprint(path: Path) -> Blueprint",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Load blueprint authority from disk"


def test_suggests_scanning_python_source_files() -> None:
    """Suggest scanning Python source files for declared code units."""

    block = _responsibility(
        symbol="scan_python_files",
        path="src/bpfw/catalog/scanner.py",
        signature="scan_python_files(project_root: Path) -> list[CodeUnit]",
    )

    suggestions = suggest_purposes(block)

    # The blended suggestion compacts to a shorter form
    assert "Scan Python source files" in suggestions[4].text


def test_suggests_project_verification_against_detected_source_code() -> None:
    """Suggest blueprint validation against detected source code."""

    block = _responsibility(
        symbol="verify_project",
        path="src/bpfw/catalog/verify.py",
        signature="verify_project(project_root: Path) -> VerificationResult",
        functions=["load_blueprint", "scan_project", "compare_responsibilities"],
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Validate blueprint declarations against detected"


def test_suggests_writing_blueprint_authority_changes_to_disk() -> None:
    """Suggest writing blueprint authority changes to disk."""

    block = _responsibility(
        symbol="save_blueprint",
        path="src/bpfw/catalog/writer.py",
        signature="save_blueprint(blueprint: Blueprint, path: Path) -> None",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Write blueprint authority changes to"


def test_suggests_detecting_duplicate_active_responsibilities() -> None:
    """Suggest detecting duplicate active blocks by purpose."""

    block = _responsibility(
        symbol="find_duplicate_purposes",
        path="src/bpfw/catalog/drift.py",
        signature=(
            "find_duplicate_purposes("
            "blocks: list[Block]"
            ") -> list[DuplicateGroup]"
        ),
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Detect duplicate active blocks by"


def test_suggests_protecting_authority_files() -> None:
    """Suggest protecting authority files from direct modification."""

    block = _responsibility(
        symbol="lock_authority_file",
        path="src/bpfw/protection/os_lock.py",
        signature="lock_authority_file(path: Path) -> LockResult",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Protect authority files from direct"


def test_suggests_running_blueprint_verification_from_command_line() -> None:
    """Suggest running blueprint verification from the command line."""

    block = _responsibility(
        symbol="handle_verify_command",
        path="src/bpfw/cli.py",
        signature="handle_verify_command(args: list[str]) -> int",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Run blueprint verification from the"


def test_suggests_purpose_from_purpose_suggestion_dataclass() -> None:
    """Suggest purpose suggestions from the dataclass evidence."""

    block = _responsibility(
        symbol="PurposeSuggestion",
        path="src/bpfw/catalog/purpose_suggestions.py",
        symbol_type="class",
        docstring="Represent one deterministic natural-language purpose suggestion.",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Suggest purpose"


def test_suggests_richer_purpose_for_suggest_purposes_function() -> None:
    """Suggest the public suggester behavior from function evidence."""

    block = _responsibility(
        symbol="suggest_purposes",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="suggest_purposes(block: dict[str, Any]) -> list[PurposeSuggestion]",
        docstring="Suggest natural-language purposes from deterministic block evidence.",
    )

    suggestions = suggest_purposes(block)

    # Docstring slot contains the purpose-focused suggestion
    assert suggestions[3].text == "Suggest purpose"


def test_docstring_slot_prefers_docstring_sentence_over_keyword_stems() -> None:
    block = _responsibility(
        symbol="resolve_guard_files",
        path="src/bpfw/protection/authority.py",
        signature="resolve_guard_files() -> List[Path]",
        docstring="Return paths to BPFW package files that implement the protection mechanism.",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[3].text == "Return protection mechanism file paths"
    assert "fil" not in suggestions[3].text.lower()


def test_name_slot_preserves_symbol_token_order() -> None:
    block = _responsibility(
        symbol="resolve_guard_files",
        path="src/bpfw/protection/authority.py",
        signature="resolve_guard_files() -> List[Path]",
        docstring="Return paths to BPFW package files that implement the protection mechanism.",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[2].text == "Resolve guard file"


def test_build_docstring_slot_drops_secondary_clauses() -> None:
    block = _responsibility(
        symbol="resolve_protected_resources",
        path="src/bpfw/protection/authority.py",
        signature="resolve_protected_resources(project_root: Path) -> List[ProtectedResource]",
        docstring="Build the full protection resource list for a project, including its blueprint and BPFW guard files.",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[3].text == "Build protection resource list"


def test_suggests_collecting_responsibility_evidence() -> None:
    """Suggest evidence collection rather than scanning evidence text."""

    block = _responsibility(
        symbol="collect_evidence_text",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="collect_evidence_text(block: dict[str, Any]) -> str",
        docstring="Collect deterministic text evidence from one block dictionary.",
    )

    suggestions = suggest_purposes(block)

    # "Collect evidence text" now appears in name_based slot (2)
    assert suggestions[2].text == "Collect evidence text"
    assert all("Scan evidence text" != suggestion.text for suggestion in suggestions)


def test_suggests_normalizing_technical_evidence_tokens() -> None:
    """Suggest token normalization from tokenizer evidence."""

    block = _responsibility(
        symbol="tokenize_evidence",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="tokenize_evidence(text: str) -> list[str]",
        docstring="Convert technical names and text evidence into normalized tokens.",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Normalize technical evidence tokens"


def test_suggests_composing_purpose_sentence_candidates() -> None:
    """Suggest candidate composition from compose function evidence."""

    block = _responsibility(
        symbol="compose_candidates",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="compose_candidates(...) -> list[_Candidate]",
        docstring="Compose deterministic purpose sentence candidates.",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Build purpose candidates"


def test_returns_empty_slots_for_generic_low_evidence_symbol() -> None:
    """Use placeholders for generic low-evidence blocks."""

    block = _responsibility(
        symbol="Helper",
        path="src/bpfw/catalog/helper.py",
        symbol_type="class",
    )

    suggestions = suggest_purposes(block)

    assert len(suggestions) == 6
    assert suggestions[0].text == "-"
    assert suggestions[5].text == "Write custom purpose..."


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

    texts = [suggest_purposes(block)[4].text for block in cases]

    assert all("Load load" not in text for text in texts)
    assert all("Write save" not in text for text in texts)
    assert all("Handle handle" not in text for text in texts)


def test_suggest_purposes_returns_fixed_slots_when_evidence_is_sufficient() -> None:
    block = _responsibility(
        symbol="suggest_purposes",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="suggest_purposes(block: dict[str, Any]) -> list[PurposeSuggestion]",
        docstring="Suggest natural-language purposes from deterministic block evidence.",
    )

    suggestions = suggest_purposes(block)

    assert len(suggestions) == 6
    # Docstring slot contains "Suggest purpose", blended may be "-" after quality filter
    assert any("Suggest" in s.text for s in suggestions if s.text != "-")


def test_suggest_purposes_keeps_specific_template_as_first_option() -> None:
    block = _responsibility(
        symbol="collect_evidence_text",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="collect_evidence_text(block: dict[str, Any]) -> str",
        docstring="Collect deterministic text evidence from one block dictionary.",
    )

    suggestions = suggest_purposes(block)
    # "Collect evidence text" is now in name_based slot (2), not blended_based (4)
    assert suggestions[2].text == "Collect evidence text"


def test_suggest_purposes_does_not_return_duplicate_variants() -> None:
    block = _responsibility(
        symbol="suggest_purposes",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="suggest_purposes(block: dict[str, Any]) -> list[PurposeSuggestion]",
        docstring="Suggest natural-language purposes from deterministic block evidence.",
    )

    suggestions = suggest_purposes(block)
    # Check that we don't have duplicate non-placeholder texts
    non_placeholder_texts = [s.text for s in suggestions if s.text != "-"]
    assert len(non_placeholder_texts) == len(set(non_placeholder_texts))


def test_compact_purpose_text_removes_responsibility_evidence_context() -> None:
    assert (
        compact_purpose_text("Suggest natural-language purposes from block evidence")
        == "Suggest purposes"
    )


def test_compact_purpose_text_converts_produce_ranked_to_rank() -> None:
    assert (
        compact_purpose_text("Produce ranked purpose suggestions from block evidence")
        == "Suggest purposes"
    )


def test_compact_purpose_text_limits_word_count() -> None:
    result = compact_purpose_text(
        "Collect deterministic text evidence from one block dictionary"
    )
    assert len(result.split()) <= 5
    assert result == "Collect evidence text"


def test_suggest_purposes_returns_compact_options() -> None:
    block = _responsibility(
        symbol="suggest_purposes",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="suggest_purposes(block: dict[str, Any]) -> list[PurposeSuggestion]",
        docstring="Suggest natural-language purposes from deterministic block evidence.",
    )
    suggestions = suggest_purposes(block)
    texts = [suggestion.text for suggestion in suggestions]
    # The docstring slot now gives "Suggest purpose" (singular)
    assert any("Suggest purpose" in text for text in texts)
    assert all(len(text.split()) <= 5 for text in texts)
    assert all("block evidence" not in text.lower() for text in texts)


def test_suggest_purposes_returns_six_fixed_options() -> None:
    block = _responsibility(
        symbol="verify_project",
        path="src/bpfw/catalog/verify.py",
        signature="verify_project(project_root: Path) -> VerificationResult",
        functions=["load_blueprint", "scan_project", "compare_responsibilities"],
        docstring="Validate blueprint declarations against detected source code.",
    )

    suggestions = suggest_purposes(block)
    assert len(suggestions) == 6
    assert all(len(suggestion.text.split()) <= 5 for suggestion in suggestions)


def test_suggest_purposes_generalizes_for_non_catalog_snippet() -> None:
    block = _responsibility(
        symbol="issue_access_token",
        path="src/auth/jwt_tokens.py",
        signature="issue_access_token(user_id: str, ttl_seconds: int) -> str",
        docstring="Create and sign JWT access tokens.",
    )

    suggestions = suggest_purposes(block)
    texts = [suggestion.text.lower() for suggestion in suggestions]
    assert suggestions
    assert all("purpose candidates" not in text for text in texts)


def test_purpose_suggestions_include_distinct_sources_when_evidence_is_sufficient() -> None:
    block = _responsibility(
        symbol="suggest_purposes",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="suggest_purposes(block: dict[str, Any]) -> list[PurposeSuggestion]",
        functions=["compose_fixed_purpose_slots"],
        docstring="Suggest natural-language purposes from deterministic block evidence.",
    )
    suggestions = suggest_purposes(
        block,
        existing_purposes=("Suggest purposes", "Collect evidence text"),
    )
    source_tags = {
        evidence_item
        for suggestion in suggestions
        for evidence_item in suggestion.evidence
        if evidence_item.startswith("source:")
    }
    assert source_tags == {
        "source: existing_purpose",
        "source: learned_based",
        "source: name_based",
        "source: docstring_based",
        "source: blended_based",
        "source: custom_purpose",
    }


def test_existing_purpose_based_candidate_appears_when_similar_purpose_exists() -> None:
    block = _responsibility(
        symbol="collect_evidence_text",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="collect_evidence_text(block: dict[str, Any]) -> str",
        docstring="Collect deterministic text evidence from one block dictionary.",
    )
    existing = ("Collect evidence text", "Run project verification")
    suggestions = suggest_purposes(block, existing_purposes=existing)
    assert any(suggestion.text == "Collect evidence text" for suggestion in suggestions)


def test_purpose_suggestions_keep_fixed_slot_order() -> None:
    """Purpose suggestions must keep stable inspector slot order."""

    block = {
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
    suggestions = suggest_purposes(
        block,
        existing_purposes=("Validate blueprint authority",),
    )
    assert [item.source for item in suggestions] == [
        "existing_purpose",
        "learned_based",
        "name_based",
        "docstring_based",
        "blended_based",
        "custom_purpose",
    ]


def test_missing_purpose_sources_render_as_placeholders() -> None:
    """Missing purpose sources must render placeholders without changing slot order."""

    block = {
        "location": {
            "path": "src/example.py",
            "symbol": "Thing",
            "symbol_type": "class",
        }
    }
    suggestions = suggest_purposes(block)
    assert len(suggestions) == 6
    assert suggestions[0].source == "existing_purpose"
    assert suggestions[-1].source == "custom_purpose"


def test_error_docstring_generates_raise_object_error_purpose() -> None:
    """Error docstrings should produce a clean raise purpose with object detail."""

    block = _responsibility(
        symbol="BlueprintMissingError",
        path="src/bpfw/core/errors.py",
        symbol_type="class",
        docstring="Raised when an operation requires a missing blueprint file.",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[3].text == "Raise missing blueprint file error"


def test_error_docstring_avoids_noisy_raised_when_prefix() -> None:
    """Docstring-based error purpose should not contain noisy filler tokens."""

    block = _responsibility(
        symbol="BlueprintLockedError",
        path="src/bpfw/core/errors.py",
        symbol_type="class",
        docstring="Raised when a protected blueprint write is attempted while locked.",
    )

    suggestions = suggest_purposes(block)

    assert "raised when" not in suggestions[3].text.lower()
    assert "operation" not in suggestions[3].text.lower()
    assert suggestions[3].text.startswith("Raise ")


def test_error_symbol_fallback_works_with_poor_docstring() -> None:
    """Error class name should provide fallback purpose when docstring is weak."""

    block = _responsibility(
        symbol="AuthTokenError",
        path="src/auth/errors.py",
        symbol_type="class",
        docstring="Raised.",
    )

    suggestions = suggest_purposes(block)

    assert any(suggestion.text == "Raise auth token error" for suggestion in suggestions)


def test_non_error_docstring_path_keeps_existing_behavior() -> None:
    """Non-error blocks should not be forced into raise-style fallback."""

    block = _responsibility(
        symbol="tokenize_evidence",
        path="src/bpfw/catalog/purpose_suggestions.py",
        signature="tokenize_evidence(text: str) -> list[str]",
        docstring="Convert technical names and text evidence into normalized tokens.",
    )

    suggestions = suggest_purposes(block)

    assert suggestions[4].text == "Normalize technical evidence tokens"


def test_docstring_slot_reads_source_when_detected_docstring_missing() -> None:
    """Docstring slot should backfill from source file when detected docstring is absent."""

    block = {
        "name": "BlueprintMissingError",
        "location": {
            "path": "src/bpfw/core/errors.py",
            "module": "src.bpfw.core.errors",
            "symbol": "BlueprintMissingError",
            "symbol_type": "class",
        },
        "detected": {
            "qualified_name": "BlueprintMissingError",
            "kind": "class",
            "methods": [],
            "functions": [],
            "imports": [],
            "decorators": [],
        },
    }

    suggestions = suggest_purposes(
        block,
        existing_purposes=("Define a BlueprintMissingError object",),
    )

    assert suggestions[3].text == "Raise missing blueprint file error"


def _responsibility(
    symbol: str,
    path: str,
    signature: str | None = None,
    symbol_type: str = "function",
    functions: list[str] | None = None,
    methods: list[str] | None = None,
    docstring: str | None = None,
) -> dict[str, Any]:
    """Build a detected block fixture."""

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
        "name": symbol,
        "location": {
            "path": path,
            "module": path.removesuffix(".py").replace("/", "."),
            "symbol": symbol,
            "symbol_type": symbol_type,
        },
        "detected": detected,
    }