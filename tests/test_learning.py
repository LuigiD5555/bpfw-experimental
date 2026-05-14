from bpfw.catalog.learning import score_phrase_context_match


def test_score_phrase_context_match_detects_overlap() -> None:
    assert score_phrase_context_match("suggest purposes", "suggest_purposes function") > 0


def test_score_phrase_context_match_returns_zero_without_overlap() -> None:
    assert score_phrase_context_match("token issuer", "blueprint verification") == 0


def test_score_phrase_context_match_handles_compound_error_tokens() -> None:
    phrase = "define blueprintmissingerror object"
    context = "blueprint missing error raised when file is absent"
    assert score_phrase_context_match(phrase, context) >= 3
