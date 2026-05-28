"""PURPOSE utility functions for the Planner tool
DOMAIN  planner workflow
"""

from pathlib import Path

from bpfw.shared.text import to_snake_case


def generate_box_id(domain: object, name: object) -> str:
    """PURPOSE generate a box ID from domain and name
    DOMAIN  planner workflow
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
    """PURPOSE generate a suggested path for a box
    DOMAIN  planner workflow
    """
    source_root_text = str(source_root or "src").strip() or "src"
    domain_path = to_snake_case(domain) or "unassigned"
    name_snake = to_snake_case(name) or "unnamed_block"
    return f"{source_root_text}/{domain_path}/{name_snake}.py"


def generate_box_symbol(name: object) -> str:
    """PURPOSE generate a symbol name from a box name
    DOMAIN  planner workflow
    """
    value = str(name or "").strip()
    if value:
        return value
    return "UnnamedBlock"


def generate_module_from_path(path: object) -> str:
    """PURPOSE generate a module name from a file path
    DOMAIN  planner workflow
    """
    path_text = str(path or "").strip()
    if not path_text:
        return ""

    return path_text.replace(".py", "").replace("/", ".").replace("\\", ".")


def generate_qualified_name(module: object, symbol: object) -> str:
    """PURPOSE generate a qualified name from module and symbol
    DOMAIN  planner workflow
    """
    module_text = str(module or "").strip()
    symbol_text = str(symbol or "").strip()
    if module_text and symbol_text:
        return f"{module_text}.{symbol_text}"
    return module_text or symbol_text


def normalize_purpose_for_duplicate_group(purpose: object) -> str:
    """PURPOSE clean purpose text for duplicate grouping
    DOMAIN  planner workflow
    """
    purpose_text = str(purpose or "").strip()
    if not purpose_text:
        return ""
    return " ".join(purpose_text.lower().split())


def detect_existing_source_roots(project_root: Path) -> list[str]:
    """PURPOSE find source roots in the project
    DOMAIN  planner workflow
    """
    source_roots: list[str] = []
    common_roots = ["src", "app", "lib", "core"]

    for root in common_roots:
        if (project_root / root).exists() and (project_root / root).is_dir():
            source_roots.append(root)

    return source_roots if source_roots else ["src"]


def get_project_defaults(project_root: Path) -> dict[str, object]:
    """PURPOSE get default project configuration values
    DOMAIN  planner workflow
    """
    return {
        "project_id": to_snake_case(project_root.name),
        "project_name": project_root.name,
        "language": "python",
        "source_roots": detect_existing_source_roots(project_root),
    }
