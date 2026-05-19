from bpfw.integrations.inspector.suggestions.purpose.learning import get_learned_purposes


def test_get_learned_purposes_returns_empty_when_learning_disabled(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    assert get_learned_purposes() == []
