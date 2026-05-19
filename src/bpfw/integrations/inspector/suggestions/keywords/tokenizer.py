"""Tokenizer for extracting words from identifiers."""

import re


def tokenize_identifier(identifier: str) -> list[str]:
    """
    Tokenize an identifier into component words.

    Supports:
    - snake_case
    - camelCase
    - PascalCase
    - UPPER_CASE
    - kebab-case
    - dot.case
    - mixed_CASE
    - Acronyms like HTTPResponseParser
    - Mixed cases like parseXMLHTTPRequest

    Examples:
        load_user_profile        -> ['load', 'user', 'profile']
        loadUserProfile          -> ['load', 'user', 'profile']
        LoadUserProfile          -> ['load', 'user', 'profile']
        LOAD_USER_PROFILE        -> ['load', 'user', 'profile']
        HTTPResponseParser       -> ['http', 'response', 'parser']
        parseXMLHTTPRequest      -> ['parse', 'xml', 'http', 'request']
        catalog.scanner          -> ['catalog', 'scanner']
    """
    if not identifier:
        return []

    # Step 1: Replace separators with spaces
    spaced = identifier.replace("_", " ").replace("-", " ").replace(".", " ").replace("/", " ")

    # Step 2: Separate camelCase and PascalCase
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", spaced)
    spaced = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", spaced)

    # Step 3: Separate acronyms (e.g., XMLHTTPRequest -> XML HTTP Request)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)

    # Step 4: Separate numbers from letters
    spaced = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", spaced)
    spaced = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", spaced)

    # Step 5: Extract tokens
    tokens = re.findall(r"[A-Za-z]+", spaced)

    # Step 6: Convert to lowercase
    tokens = [token.lower() for token in tokens]

    # Step 7: Remove empty tokens
    tokens = [token for token in tokens if token]

    return tokens


def tokenize_text(text: str) -> list[str]:
    """
    Tokenize free text into words.

    This is simpler than identifier tokenization since we don't need to
    handle camelCase or special separators.

    Args:
        text: Free text to tokenize.

    Returns:
        List of lowercase tokens.
    """
    if not text:
        return []

    # Extract words, ignoring punctuation and numbers
    tokens = re.findall(r"[A-Za-z][A-Za-z]*", text)
    tokens = [token.lower() for token in tokens if token]

    return tokens


def tokenize_path(path: str) -> list[str]:
    """
    Tokenize a file path into component parts.

    Examples:
        src/bpfw/catalog/scanner.py -> ['src', 'bpfw', 'catalog', 'scanner']
        app/services/users.py -> ['app', 'services', 'users']

    Args:
        path: File path to tokenize.

    Returns:
        List of path components as lowercase tokens.
    """
    if not path:
        return []

    # Normalize path separators
    normalized = path.replace("\\", "/")

    # Split by /
    parts = [part for part in normalized.split("/") if part]

    # Remove file extension
    if parts and "." in parts[-1]:
        parts[-1] = parts[-1].rsplit(".", 1)[0]

    # Convert to lowercase
    tokens = [part.lower() for part in parts if part]

    return tokens