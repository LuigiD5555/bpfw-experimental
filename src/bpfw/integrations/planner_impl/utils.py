"""Utility functions for the Planner integration."""

import re
from pathlib import Path


def to_snake_case(value: str) -> str:
    """Convert a string to snake_case.
    
    Args:
        value: The string to convert.
    
    Returns:
        The string converted to snake_case.
    """
    result = []
    for character in value:
        if character.isupper():
            if result and result[-1] != "_":
                result.append("_")
            result.append(character.lower())
        elif character in (" ", "-", "."):
            if result and result[-1] != "_":
                result.append("_")
        else:
            result.append(character)
    return "".join(result).strip("_")


def generate_box_id(domain: str, name: str) -> str:
    """Generate a unique box ID from domain and name.
    
    Args:
        domain: The domain of the box.
        name: The name of the box.
    
    Returns:
        A unique box ID in snake_case format.
    """
    domain_snake = to_snake_case(domain)
    name_snake = to_snake_case(name)
    return f"{domain_snake}_{name_snake}"


def generate_box_path(source_root: str, domain: str, name: str) -> str:
    """Generate a suggested path for a box.
    
    Args:
        source_root: The source root directory (e.g., "src").
        domain: The domain of the box.
        name: The name of the box.
    
    Returns:
        A suggested file path.
    """
    domain_path = to_snake_case(domain)
    name_snake = to_snake_case(name)
    return f"{source_root}/{domain_path}/{name_snake}.py"


def generate_box_symbol(name: str) -> str:
    """Generate a symbol name from a box name.
    
    Args:
        name: The name of the box.
    
    Returns:
        A symbol name (typically PascalCase).
    """
    return name


def generate_module_from_path(path: str) -> str:
    """Generate a module name from a file path.
    
    Args:
        path: The file path (e.g., "src/ingestion/invoice_parser.py").
    
    Returns:
        The module name (e.g., "src.ingestion.invoice_parser").
    """
    # Remove .py extension and convert slashes to dots
    module = path.replace(".py", "").replace("/", ".").replace("\\", ".")
    return module


def generate_qualified_name(module: str, symbol: str) -> str:
    """Generate a qualified name from module and symbol.
    
    Args:
        module: The module name.
        symbol: The symbol name.
    
    Returns:
        The qualified name (e.g., "src.ingestion.invoice_parser.InvoiceParser").
    """
    return f"{module}.{symbol}"


def normalize_intent_for_duplicate_group(intent: str) -> str:
    """Normalize intent text for duplicate group.
    
    Args:
        intent: The intent text.
    
    Returns:
        Normalized intent text suitable for duplicate grouping.
    """
    # Convert to lowercase and remove extra whitespace
    normalized = " ".join(intent.lower().split())
    return normalized


def detect_existing_source_roots(project_root: Path) -> list[str]:
    """Detect existing source roots in the project.
    
    Args:
        project_root: The project root directory.
    
    Returns:
        List of detected source roots.
    """
    source_roots = []
    
    common_roots = ["src", "app", "lib", "core"]
    
    for root in common_roots:
        if (project_root / root).exists() and (project_root / root).is_dir():
            source_roots.append(root)
    
    return source_roots if source_roots else ["src"]


def get_project_defaults(project_root: Path) -> dict:
    """Get default project configuration values.
    
    Args:
        project_root: The project root directory.
    
    Returns:
        Dictionary of default values.
    """
    return {
        "project_id": to_snake_case(project_root.name),
        "project_name": project_root.name,
        "language": "python",
        "source_roots": detect_existing_source_roots(project_root),
    }