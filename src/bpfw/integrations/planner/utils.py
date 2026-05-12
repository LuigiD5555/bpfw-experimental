"""Utility functions for the Planner integration."""

from pathlib import Path


def to_snake_case(value: object) -> str:
    """Convert a value to snake_case.

    Args:
        value: The value to convert.

    Returns:
        The value converted to snake_case, or an empty string when the value is empty.
    """
    if value is None:
        return ""

    value_text = str(value).strip()
    if not value_text:
        return ""

    result: list[str] = []
    for character in value_text:
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


def generate_box_id(domain: object, name: object) -> str:
    """Generate a box ID from domain and name.

    Args:
        domain: The domain of the box.
        name: The name of the box.

    Returns:
        A box ID in snake_case format.
    """
    domain_snake = to_snake_case(domain)
    name_snake = to_snake_case(name)

    if domain_snake and name_snake:
        return f"{domain_snake}_{name_snake}"
    if name_snake:
        return name_snake
    if domain_snake:
        return domain_snake
    return "unnamed_block"


def generate_box_path(source_root: object, domain: object, name: object) -> str:
    """Generate a suggested path for a box.

    Args:
        source_root: The source root directory, such as "src".
        domain: The domain of the box.
        name: The name of the box.

    Returns:
        A suggested file path.
    """
    source_root_text = str(source_root or "src").strip() or "src"
    domain_path = to_snake_case(domain) or "unassigned"
    name_snake = to_snake_case(name) or "unnamed_block"
    return f"{source_root_text}/{domain_path}/{name_snake}.py"


def generate_box_symbol(name: object) -> str:
    """Generate a symbol name from a box name.

    Args:
        name: The name of the box.

    Returns:
        A symbol name.
    """
    value = str(name or "").strip()
    if value:
        return value
    return "UnnamedBlock"


def generate_module_from_path(path: object) -> str:
    """Generate a module name from a file path.

    Args:
        path: The file path, such as "src/ingestion/invoice_parser.py".

    Returns:
        The module name, such as "src.ingestion.invoice_parser".
    """
    path_text = str(path or "").strip()
    if not path_text:
        return ""

    return path_text.replace(".py", "").replace("/", ".").replace("\\", ".")


def generate_qualified_name(module: object, symbol: object) -> str:
    """Generate a qualified name from module and symbol.

    Args:
        module: The module name.
        symbol: The symbol name.

    Returns:
        The qualified name.
    """
    module_text = str(module or "").strip()
    symbol_text = str(symbol or "").strip()
    if module_text and symbol_text:
        return f"{module_text}.{symbol_text}"
    return module_text or symbol_text


def normalize_purpose_for_duplicate_group(purpose: object) -> str:
    """Normalize purpose text for duplicate grouping.

    Args:
        purpose: The purpose text.

    Returns:
        Normalized purpose text suitable for duplicate grouping.
    """
    purpose_text = str(purpose or "").strip()
    if not purpose_text:
        return ""
    return " ".join(purpose_text.lower().split())


def detect_existing_source_roots(project_root: Path) -> list[str]:
    """Detect existing source roots in the project.

    Args:
        project_root: The project root directory.

    Returns:
        List of detected source roots.
    """
    source_roots: list[str] = []
    common_roots = ["src", "app", "lib", "core"]

    for root in common_roots:
        if (project_root / root).exists() and (project_root / root).is_dir():
            source_roots.append(root)

    return source_roots if source_roots else ["src"]


def get_project_defaults(project_root: Path) -> dict[str, object]:
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
