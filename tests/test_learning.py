from bpfw.catalog.learning import score_phrase_context_match


def test_score_phrase_context_match_detects_overlap() -> None:
    assert score_phrase_context_match("suggest intents", "suggest_intents function") > 0


def test_score_phrase_context_match_returns_zero_without_overlap() -> None:
    assert score_phrase_context_match("token issuer", "blueprint verification") == 0
