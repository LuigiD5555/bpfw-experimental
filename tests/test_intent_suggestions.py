"""Tests for deterministic natural-language intent suggestions."""

from bpfw.catalog.intent_suggestions import suggest_intents


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
    assert any("blueprint" in suggestion.text.lower() for suggestion in suggestions)