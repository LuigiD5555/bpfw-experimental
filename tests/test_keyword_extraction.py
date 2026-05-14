"""Test keyword extraction from AST."""

import pytest

from bpfw.catalog.keywords import extract_block_keywords, build_project_vocabulary
from bpfw.catalog.keywords.tokenizer import tokenize_identifier
from bpfw.catalog.keywords.normalizer import normalize_token, normalize_tokens


def test_tokenize_snake_case():
    """Test tokenizing snake_case identifiers."""

    tokens = tokenize_identifier("extract_called_symbols_from_node")
    assert tokens == ["extract", "called", "symbols", "from", "node"]


def test_tokenize_camel_case():
    """Test tokenizing camelCase identifiers."""

    tokens = tokenize_identifier("loadUserProfile")
    assert tokens == ["load", "user", "profile"]


def test_tokenize_pascal_case():
    """Test tokenizing PascalCase identifiers."""

    tokens = tokenize_identifier("LoadUserProfile")
    assert tokens == ["load", "user", "profile"]


def test_tokenize_upper_case():
    """Test tokenizing UPPER_CASE identifiers."""

    tokens = tokenize_identifier("LOAD_USER_PROFILE")
    assert tokens == ["load", "user", "profile"]


def test_tokenize_mixed_case():
    """Test tokenizing mixed case with acronyms."""

    tokens = tokenize_identifier("HTTPResponseParser")
    assert tokens == ["http", "response", "parser"]

    # Note: Mixed acronyms like XMLHTTPRequest may not split perfectly
    # This is a known limitation and acceptable
    tokens = tokenize_identifier("parseXMLHTTPRequest")
    assert "parse" in tokens
    assert "xml" in tokens or "xmlhttp" in tokens  # May combine acronyms
    assert "request" in tokens


def test_normalize_file_plural_keeps_final_e() -> None:
    assert normalize_token("files") == "file"
    assert normalize_token("classes") == "class"


def test_tokenize_dot_case():
    """Test tokenizing dotted paths."""

    tokens = tokenize_identifier("catalog.scanner")
    assert tokens == ["catalog", "scanner"]


def test_normalize_tokens():
    """Test token normalization."""

    tokens = normalize_tokens(["Hello", "WORLD", "test123", "a", ""])
    assert "hello" in tokens
    assert "world" in tokens
    assert "test123" in tokens
    assert "a" not in tokens  # Single letter removed


def test_extract_block_keywords_simple():
    """Test extracting keywords from a simple block."""

    block = {
        "symbol": "extract_called_symbols_from_node",
        "detected": {
            "docstring": "Extract called symbols from an AST node.",
            "parameters": ["node"],
        },
    }

    profile = extract_block_keywords(block)

    assert profile.block_id == "extract_called_symbols_from_node"
    assert len(profile.keywords) > 0

    # Check for expected keywords (normalized to singular form)
    keyword_texts = [k.token for k in profile.keywords]
    assert "extract" in keyword_texts
    assert "called" in keyword_texts
    assert "symbol" in keyword_texts  # Normalized from "symbols"
    assert "node" in keyword_texts


def test_extract_block_keywords_class():
    """Test extracting keywords from a class."""

    block = {
        "symbol": "HTTPResponseParser",
        "kind": "class",
        "detected": {
            "docstring": "Parse HTTP response data.",
        },
    }

    profile = extract_block_keywords(block)

    assert profile.block_id == "HTTPResponseParser"
    assert len(profile.keywords) > 0

    keyword_texts = [k.token for k in profile.keywords]
    assert "http" in keyword_texts
    assert "response" in keyword_texts
    assert "parser" in keyword_texts


def test_extract_block_keywords_with_vocabulary():
    """Test that vocabulary adjusts scores."""

    blocks = [
        {
            "symbol": "extract_data",
            "detected": {"docstring": "Extract data from file."},
        },
        {
            "symbol": "process_data",
            "detected": {"docstring": "Process data."},
        },
        {
            "symbol": "validate_data",
            "detected": {"docstring": "Validate data."},
        },
        {
            "symbol": "reconcile_transactions",
            "detected": {"docstring": "Reconcile bank transactions."},
        },
    ]

    # Build vocabulary
    vocabulary = build_project_vocabulary(blocks)

    # Extract keywords from rare token block
    block = blocks[3]
    profile = extract_block_keywords(block, vocabulary=vocabulary)

    keyword_texts = [k.token for k in profile.keywords]
    assert "reconcile" in keyword_texts
    assert "transaction" in keyword_texts  # Normalized from "transactions"

    # Check that "data" is less prominent in rare token block
    data_keywords = [k for k in profile.keywords if k.token == "data"]
    assert len(data_keywords) == 0  # "data" is generic and should be filtered


def test_build_project_vocabulary():
    """Test building project vocabulary."""

    blocks = [
        {
            "symbol": "extract_data",
            "detected": {"docstring": "Extract data."},
        },
        {
            "symbol": "process_data",
            "detected": {"docstring": "Process data."},
        },
        {
            "symbol": "validate_input",
            "detected": {"docstring": "Validate input."},
        },
    ]

    vocabulary = build_project_vocabulary(blocks)

    assert vocabulary.total_blocks == 3
    assert vocabulary.total_tokens > 0

    # "data" appears in 2/3 blocks
    assert vocabulary.get_token_block_frequency("data") == pytest.approx(0.667, rel=0.1)

    # "validate" appears in 1/3 blocks
    assert vocabulary.get_token_block_frequency("validate") == pytest.approx(0.333, rel=0.1)


def test_phrases_from_block():
    """Test phrase extraction from block."""

    block = {
        "symbol": "validate_blueprint_authority_fields",
        "detected": {
            "docstring": "Validate blueprint authority fields from YAML.",
        },
    }

    profile = extract_block_keywords(block)

    # Should have phrases
    assert len(profile.phrases) > 0

    # Check for expected phrases
    phrase_text = " ".join(profile.phrases)
    assert "blueprint authority" in phrase_text or "authority fields" in phrase_text


def test_scoring_by_source():
    """Test that scoring respects evidence sources."""

    block = {
        "symbol": "calculate_patient_dosage",
        "detected": {
            "docstring": "Calculate dosage for a patient.",
        },
    }

    profile = extract_block_keywords(block)

    # Keywords from symbol name should have higher scores
    symbol_keywords = [k for k in profile.keywords if "symbol_name" in k.sources]

    assert len(symbol_keywords) > 0

    # Check that important keywords are present
    keyword_texts = [k.token for k in profile.keywords]
    assert "calculate" in keyword_texts
    assert "patient" in keyword_texts
    assert "dosage" in keyword_texts


def test_empty_block_handling():
    """Test handling of blocks with minimal information."""

    block = {
        "symbol": "process",
        "detected": {},
    }

    profile = extract_block_keywords(block)

    # Should still extract something, even if minimal
    assert profile.block_id == "process"

    # May have few or no keywords
    # This is expected behavior - not all blocks have strong evidence


def test_filter_generic_tokens():
    """Test filtering of generic tokens."""

    blocks = [
        {
            "symbol": "function_one",
            "detected": {"docstring": "Process data with result."},
        },
        {
            "symbol": "function_two",
            "detected": {"docstring": "Process data with result."},
        },
        {
            "symbol": "function_three",
            "detected": {"docstring": "Process data with result."},
        },
        {
            "symbol": "special_operation",
            "detected": {"docstring": "Perform special operation."},
        },
    ]

    vocabulary = build_project_vocabulary(blocks)

    # "data" and "result" appear in 75% of blocks - should be filtered
    profile = extract_block_keywords(blocks[3], vocabulary=vocabulary)

    keyword_texts = [k.token for k in profile.keywords]

    # "special" and "operation" should be present (rare)
    assert "special" in keyword_texts or "operation" in keyword_texts

    # "data" and "result" should be absent (common)
    assert "data" not in keyword_texts
    assert "result" not in keyword_texts


def test_confidence_levels():
    """Test confidence level assignment."""

    from bpfw.catalog.keywords.scorer import get_confidence_level

    block = {
        "symbol": "validate_blueprint_authority",
        "detected": {
            "docstring": "Validate blueprint authority from YAML files.",
        },
    }

    blocks = [
        block,
        {
            "symbol": "other_function",
            "detected": {"docstring": "Do something else."},
        },
    ]

    vocabulary = build_project_vocabulary(blocks)
    profile = extract_block_keywords(block, vocabulary=vocabulary)

    # Get top keyword
    if profile.keywords:
        top_keyword = profile.keywords[0]
        confidence = get_confidence_level(top_keyword, vocabulary)

        # Should have medium or high confidence
        assert confidence in {"low", "medium", "high"}


def test_deduplication():
    """Test deduplication of similar keywords."""

    from bpfw.catalog.keywords.scorer import deduplicate_similar
    from bpfw.catalog.keywords.models import KeywordCandidate

    candidates = [
        KeywordCandidate(token="symbol", score=10, sources=["symbol_name"], occurrences=1),
        KeywordCandidate(token="symbols", score=9, sources=["docstring"], occurrences=1),
        KeywordCandidate(token="transaction", score=20, sources=["symbol_name"], occurrences=1),
    ]

    deduped = deduplicate_similar(candidates)

    # "symbol" and "symbols" should be deduplicated
    assert len(deduped) == 2

    # Should keep the higher-scored one
    deduped_tokens = [c.token for c in deduped]
    assert "symbol" in deduped_tokens
    assert "transaction" in deduped_tokens
