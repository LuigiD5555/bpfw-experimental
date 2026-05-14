"""Extract evidence from code blocks for keyword analysis."""

from typing import Any

from bpfw.catalog.keywords.models import KeywordEvidence
from bpfw.catalog.keywords.tokenizer import (
    tokenize_identifier,
    tokenize_path,
    tokenize_text,
)


# Evidence source weights (higher = more important)
EVIDENCE_WEIGHTS = {
    "symbol_name": 10.0,
    "docstring_summary": 8.0,
    "parameters": 5.0,
    "return_annotation": 5.0,
    "called_symbols": 5.0,
    "assigned_attributes": 4.0,
    "raised_exceptions": 4.0,
    "decorators": 3.0,
    "path": 3.0,
    "module": 3.0,
    "imports": 2.0,
    "methods": 3.0,
    "functions": 2.5,
}


def _resolve_block_info(block: dict[str, Any]) -> dict[str, Any]:
    """
    Extract block information from various possible structures.

    Blocks can have data in:
    - Top-level keys: symbol, path, module
    - Nested in "location": location.symbol, location.path, location.module
    - Nested in "code": code.symbol, code.path, code.module

    Args:
        block: Block dictionary from scanner.

    Returns:
        Dictionary with resolved symbol, path, module, symbol_type.
    """
    # Try nested structures first, then fall back to top-level
    info: dict[str, Any] = {}

    # Get symbol
    symbol = (
        block.get("location", {}).get("symbol")
        or block.get("code", {}).get("symbol")
        or block.get("symbol")
        or block.get("name")
        or ""
    )
    info["symbol"] = symbol

    # Get path
    path = (
        block.get("location", {}).get("path")
        or block.get("code", {}).get("path")
        or block.get("path")
        or ""
    )
    info["path"] = path

    # Get module
    module = (
        block.get("location", {}).get("module")
        or block.get("code", {}).get("module")
        or block.get("module")
        or ""
    )
    info["module"] = module

    # Get symbol_type
    symbol_type = (
        block.get("location", {}).get("symbol_type")
        or block.get("code", {}).get("symbol_type")
        or block.get("symbol_type")
        or ""
    )
    info["symbol_type"] = symbol_type

    return info


# Evidence source weights (higher = more important)
EVIDENCE_WEIGHTS = {
    "symbol_name": 10.0,
    "docstring_summary": 8.0,
    "parameters": 5.0,
    "return_annotation": 5.0,
    "called_symbols": 5.0,
    "assigned_attributes": 4.0,
    "raised_exceptions": 4.0,
    "decorators": 3.0,
    "path": 3.0,
    "module": 3.0,
    "imports": 2.0,
    "methods": 3.0,
    "functions": 2.5,
}


def extract_evidence_from_block(block: dict[str, Any]) -> list[KeywordEvidence]:
    """
    Extract keyword evidence from a single code block.

    Args:
        block: Block dictionary from scanner.

    Returns:
        List of KeywordEvidence items.
    """
    evidence: list[KeywordEvidence] = []

    # Resolve block information from various structures
    info = _resolve_block_info(block)

    # Extract symbol name
    symbol = info.get("symbol", "")
    if symbol:
        # Get just the last part (unqualified name)
        simple_name = symbol.split(".")[-1] if "." in symbol else symbol
        tokens = tokenize_identifier(simple_name)
        for token in tokens:
            evidence.append(
                KeywordEvidence(
                    raw_text=token,
                    source="symbol_name",
                    weight=EVIDENCE_WEIGHTS["symbol_name"],
                    location=symbol,
                )
            )

    # Extract path
    path = info.get("path", "")
    if path:
        tokens = tokenize_path(path)
        for token in tokens:
            evidence.append(
                KeywordEvidence(
                    raw_text=token,
                    source="path",
                    weight=EVIDENCE_WEIGHTS["path"],
                    location=path,
                )
            )

    # Extract module
    module = info.get("module", "")
    if module:
        tokens = tokenize_identifier(module)
        for token in tokens:
            evidence.append(
                KeywordEvidence(
                    raw_text=token,
                    source="module",
                    weight=EVIDENCE_WEIGHTS["module"],
                    location=module,
                )
            )

    # Extract from detected data
    detected = block.get("detected", {})
    if isinstance(detected, dict):
        # Docstring
        docstring = detected.get("docstring", "")
        if docstring:
            # Use only first sentence for summary
            summary = docstring.split(".")[0]
            tokens = tokenize_text(summary)
            for token in tokens:
                evidence.append(
                    KeywordEvidence(
                        raw_text=token,
                        source="docstring_summary",
                        weight=EVIDENCE_WEIGHTS["docstring_summary"],
                        location="docstring",
                    )
                )

        # Signature (parameters and return type)
        signature = detected.get("signature", "")
        if signature:
            # Extract parameter names
            import re
            param_match = re.search(r"\((.*?)\)", signature)
            if param_match:
                params = param_match.group(1)
                for param in params.split(","):
                    param_name = param.split(":")[0].strip()
                    if param_name and param_name not in ("self", "cls"):
                        tokens = tokenize_identifier(param_name)
                        for token in tokens:
                            evidence.append(
                                KeywordEvidence(
                                    raw_text=token,
                                    source="parameters",
                                    weight=EVIDENCE_WEIGHTS["parameters"],
                                    location=signature,
                                )
                            )

            # Extract return type
            return_match = re.search(r"->\s*([^)]+)", signature)
            if return_match:
                return_type = return_match.group(1).strip()
                tokens = tokenize_identifier(return_type)
                for token in tokens:
                    evidence.append(
                        KeywordEvidence(
                            raw_text=token,
                            source="return_annotation",
                            weight=EVIDENCE_WEIGHTS["return_annotation"],
                            location=signature,
                        )
                    )

        # Called symbols
        called_symbols = detected.get("called_symbols", [])
        if isinstance(called_symbols, list):
            for symbol in called_symbols:
                tokens = tokenize_identifier(symbol)
                for token in tokens:
                    evidence.append(
                        KeywordEvidence(
                            raw_text=token,
                            source="called_symbols",
                            weight=EVIDENCE_WEIGHTS["called_symbols"],
                            location=symbol,
                        )
                    )

        # Methods (for classes)
        methods = detected.get("methods", [])
        if isinstance(methods, list):
            for method in methods:
                simple_name = method.split(".")[-1] if "." in method else method
                tokens = tokenize_identifier(simple_name)
                for token in tokens:
                    evidence.append(
                        KeywordEvidence(
                            raw_text=token,
                            source="methods",
                            weight=EVIDENCE_WEIGHTS["methods"],
                            location=method,
                        )
                    )

        # Functions (for classes)
        functions = detected.get("functions", [])
        if isinstance(functions, list):
            for func in functions:
                simple_name = func.split(".")[-1] if "." in func else func
                tokens = tokenize_identifier(simple_name)
                for token in tokens:
                    evidence.append(
                        KeywordEvidence(
                            raw_text=token,
                            source="functions",
                            weight=EVIDENCE_WEIGHTS["functions"],
                            location=func,
                        )
                    )

        # Imports
        imports = detected.get("imports", [])
        if isinstance(imports, list):
            for import_name in imports:
                # Get last part of import path
                simple_name = import_name.split(".")[-1] if "." in import_name else import_name
                tokens = tokenize_identifier(simple_name)
                for token in tokens:
                    evidence.append(
                        KeywordEvidence(
                            raw_text=token,
                            source="imports",
                            weight=EVIDENCE_WEIGHTS["imports"],
                            location=import_name,
                        )
                    )

        # Decorators
        decorators = detected.get("decorators", [])
        if isinstance(decorators, list):
            for decorator in decorators:
                tokens = tokenize_identifier(decorator)
                for token in tokens:
                    evidence.append(
                        KeywordEvidence(
                            raw_text=token,
                            source="decorators",
                            weight=EVIDENCE_WEIGHTS["decorators"],
                            location=decorator,
                        )
                    )

    return evidence