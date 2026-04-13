"""Architecture checker: validates structural constraints of the codebase."""

import ast
import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


def _find_repo_root(anchor: str = "CLAUDE.md") -> Path:
    """Walk up from this file until a directory containing *anchor* is found.

    Raises RuntimeError if the anchor is not found before reaching the filesystem root.
    This is robust to reorganisation of tools/ because it does not count parent levels.
    """
    explicit_root = os.environ.get("AIOA_PROJECT_ROOT")
    if explicit_root:
        candidate_root = Path(explicit_root).expanduser().resolve()
        marker = candidate_root / "src" / "catalog" / "responsibilities"
        if marker.exists() and marker.is_dir():
            return candidate_root
        raise RuntimeError(
            "AIOA_PROJECT_ROOT is set but does not contain "
            "src/catalog/responsibilities."
        )

    cwd_root = Path.cwd().resolve()
    cwd_marker = cwd_root / "src" / "catalog" / "responsibilities"
    if cwd_marker.exists() and cwd_marker.is_dir():
        return cwd_root

    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / anchor).exists():
            return current
        current = current.parent
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "src" / "catalog" / "responsibilities").exists():
            return current
        current = current.parent
    raise RuntimeError(
        f"Repository root not found: no '{anchor}' marker and no "
        "src/catalog/responsibilities marker were found."
    )


_REPO_ROOT = _find_repo_root()

from aioa.catalog.loader import (  # noqa: E402
    load_catalog_snapshot,
    load_extended_catalog_snapshot,
)
from aioa.catalog.models import CatalogSchemaError  # noqa: E402
from aioa.catalog.runtime_contract import (  # noqa: E402
    AmbiguousLifecycleOwnershipError,
    DuplicateActiveImplementationError,
    InactiveLifecycleRuntimeAlignmentError,
    OwnerLayerRuntimeAlignmentError,
    UndeclaredActiveComponentError,
    UndeclaredActiveImplementationError,
    UndeclaredPublicEntrypointError,
    validate_runtime_contract,
)
from aioa.catalog.runtime_snapshot import load_persisted_runtime_snapshot  # noqa: E402
from aioa.catalog.validator import (  # noqa: E402
    validate_catalog_snapshot,
    validate_extended_catalog_snapshot,
)
from aioa.catalog.wiring_verifier import verify_catalog_runtime_alignment  # noqa: E402


class Severity(str, Enum):
    """Severity level of an architecture violation."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Violation:
    """A single architecture violation with category, severity, rule ID, and message."""

    category: str
    message: str
    severity: Severity = field(default=Severity.ERROR)
    rule_id: str = field(default="")

    def __str__(self) -> str:
        prefix = f"[{self.rule_id}] " if self.rule_id else ""
        return f"{self.severity.value.upper()} {prefix}{self.category}: {self.message}"


# Classes that must not be instantiated directly outside of bootstrap
_PROHIBITED_CLASSES = frozenset([
    "ProviderFactory",
    "WeaviateRetriever",
    "IngestionOrchestrator",
])

# Pattern to match class instantiation: ClassName( with optional whitespace
_INSTANTIATION_PATTERN = re.compile(
    r"\b(" + "|".join(_PROHIBITED_CLASSES) + r")\s*\("
)


def _remove_comments(source: str) -> str:
    """Remove single-line and multi-line comments from Python source code."""
    # Remove multi-line strings (triple quotes) that act as docstrings/comments
    result = re.sub(r'"""[\s\S]*?"""', "", source)
    result = re.sub(r"'''[\s\S]*?'''", "", result)
    # Remove single-line comments
    result = re.sub(r"#.*$", "", result, flags=re.MULTILINE)
    return result


def detect_direct_infra_instantiations(paths: list[Path]) -> list[str]:
    """Detect direct instantiations of prohibited infrastructure classes outside bootstrap.

    Searches for direct construction calls (e.g., ProviderFactory(...)) in Python files
    located outside the src/bootstrap/ directory.

    Args:
        paths: List of directory paths to scan for violations.

    Returns:
        List of violation messages describing where prohibited instantiations were found.
    """
    violations: list[str] = []

    for base_path in paths:
        if not base_path.exists():
            continue

        for file_path in base_path.rglob("*.py"):
            # Skip files inside bootstrap directory
            if "bootstrap" in file_path.parts:
                continue

            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Remove comments to avoid false positives
            clean_source = _remove_comments(source)

            # Search for prohibited instantiations
            for match in _INSTANTIATION_PATTERN.finditer(clean_source):
                class_name = match.group(1)
                # Try to get relative path, fall back to absolute or as-is
                try:
                    display_path = file_path.relative_to(_REPO_ROOT)
                except ValueError:
                    # File is not under repo root (e.g., temp directory)
                    display_path = file_path
                violations.append(
                    f"Direct instantiation of {class_name} outside bootstrap: {display_path}"
                )

    return violations


_SUSPICIOUS_NAME_PATTERNS = re.compile(
    r"\b(Manager|Unified|Smart|Enhanced|Mega)\w*\b"
)

# Path segments that indicate system/infrastructure support code, not domain architecture.
# Names like SystemdManager in these paths are tolerable and should not trigger NAME001.
_INFRASTRUCTURE_SUPPORT_PATH_SEGMENTS = frozenset(["support", "tools"])

# Parts of paths that indicate utility/helper modules
_UTILITY_PATH_SEGMENTS = frozenset(["utils", "helpers", "common", "misc"])

# Heuristics for business logic in identifiers (class/function/variable names and call sites).
# Applied to definition names and call expressions — NOT to import module paths.
# "domain" is intentionally excluded here because module-path evaluation uses prefix matching
# instead (see _is_allowed_domain_import and _is_prohibited_domain_import below).
_BUSINESS_LOGIC_INDICATORS = re.compile(
    r"\b(orchestrat|use_case|service|repository|aggregate|entity|pipeline|workflow)\b",
    re.IGNORECASE,
)

# Import module-path prefixes that are cross-cutting infrastructure tolerated from utils/helpers.
# Imports whose full dotted module path starts with any of these are not flagged as utility creep.
_ALLOWED_DOMAIN_IMPORT_PREFIXES: tuple[str, ...] = (
    "src.domain.observability",
    "src.domain.exceptions",
    "src.domain.contracts",
    "src.application.contracts",
)

# Import module-path prefixes that represent business domain logic.
# Imports from these sub-trees inside a utility module are flagged as utility creep.
_PROHIBITED_DOMAIN_IMPORT_PREFIXES: tuple[str, ...] = (
    "src.domain.use_cases",
    "src.domain.services",
    "src.domain.policies",
    "src.domain.workflows",
    "src.domain.repositories",
    "src.application.use_cases",
    "src.application.services",
    "src.application.orchestrat",
)


def _is_allowed_domain_import(module_path: str) -> bool:
    """Return True if the full dotted import path is cross-cutting infrastructure.

    These imports are tolerated inside utility modules and do not constitute utility creep.
    """
    return any(module_path.startswith(prefix) for prefix in _ALLOWED_DOMAIN_IMPORT_PREFIXES)


def _is_prohibited_domain_import(module_path: str) -> bool:
    """Return True if the full dotted import path belongs to a business-domain sub-tree.

    These imports inside utility modules are flagged as utility creep regardless of
    the specific symbol imported.
    """
    return any(module_path.startswith(prefix) for prefix in _PROHIBITED_DOMAIN_IMPORT_PREFIXES)


def _collect_suspicious_names_from_ast(tree: ast.Module) -> set[str]:
    """Return the set of suspicious names found in semantic AST positions.

    Inspects:
    - Class, function, and async function definition names
    - Import aliases (import X as Alias → Alias)
    - Module-level annotated assignments (constants/globals: MyManager: Type = ...)
    - Names exported via __all__

    Deduplicates: each unique suspicious name is returned at most once per file.
    """
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if _SUSPICIOUS_NAME_PATTERNS.search(node.name):
                found.add(node.name)

        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                target = alias.asname or alias.name.split(".")[-1]
                if _SUSPICIOUS_NAME_PATTERNS.search(target):
                    found.add(target)

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and _SUSPICIOUS_NAME_PATTERNS.search(target.id):
                    found.add(target.id)
                # __all__ = [...] — check exported string names
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for element in node.value.elts:
                            if (
                                isinstance(element, ast.Constant)
                                and isinstance(element.value, str)
                                and _SUSPICIOUS_NAME_PATTERNS.search(element.value)
                            ):
                                found.add(element.value)

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and _SUSPICIOUS_NAME_PATTERNS.search(node.target.id):
                found.add(node.target.id)

    return found


def detect_suspicious_names(paths: list[Path]) -> list[str]:
    """Detect names that suggest non-canonical, inflated responsibilities.

    Uses AST inspection to match names only in semantically meaningful positions:
    class/function definitions, import aliases, module-level assignments, and
    __all__ exports. String literals in other positions are not inspected.

    Skips files under infrastructure support paths (e.g. support/tools) where
    system-management names like SystemdManager are architecturally tolerable.

    Flags names matching Manager, Unified, Smart, Enhanced, or Mega patterns.
    Each unique suspicious name is reported at most once per file.

    Args:
        paths: List of directory paths to scan.

    Returns:
        List of violation messages with file path and matched name.
    """
    violations: list[str] = []

    for base_path in paths:
        if not base_path.exists():
            continue

        for file_path in base_path.rglob("*.py"):
            if any(segment in file_path.parts for segment in _INFRASTRUCTURE_SUPPORT_PATH_SEGMENTS):
                continue

            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            try:
                tree = ast.parse(source, filename=str(file_path))
            except SyntaxError:
                continue

            try:
                display_path = file_path.relative_to(_REPO_ROOT)
            except ValueError:
                display_path = file_path

            for name in sorted(_collect_suspicious_names_from_ast(tree)):
                violations.append(f"Suspicious name '{name}' in {display_path}")

    return violations


# Parts that, when adjacent to a business-logic term inside a compound identifier,
# indicate the identifier refers to system/infrastructure concerns rather than domain logic.
# Example: 'service' in 'get_service_status' or '_update_service_file' → system context.
_SYSTEM_IDENTIFIER_PARTS = frozenset({
    "file", "files", "status", "unit", "units", "socket", "sockets",
    "systemd", "systemctl", "daemon", "update", "install", "restart",
    "enable", "disable", "stop", "start", "reload", "check", "verify",
    "active", "enabled", "installed", "manager", "handler", "notify",
    "timeout", "log", "logs", "alert",
})


def _is_system_compound_identifier(parts: list[str], indicator_index: int) -> bool:
    """Return True if the indicator at parts[indicator_index] is part of a system identifier.

    An indicator is considered system-context when any adjacent part (before or after)
    belongs to _SYSTEM_IDENTIFIER_PARTS.
    """
    adjacent_indices = [indicator_index - 1, indicator_index + 1]
    return any(
        0 <= idx < len(parts) and parts[idx].lower() in _SYSTEM_IDENTIFIER_PARTS
        for idx in adjacent_indices
    )


def _indicator_parts_from_name(name: str) -> list[tuple[int, str, list[str]]]:
    """Split a compound identifier and return (index, part, all_parts) for each part."""
    parts = [p for p in re.split(r"[\W_]+", name) if p]
    return [(idx, part, parts) for idx, part in enumerate(parts)]


def _check_candidate(name: str, found: set[str]) -> None:
    """Add any business-logic indicator terms from name to found, excluding system context."""
    for idx, part, parts in _indicator_parts_from_name(name):
        if not _BUSINESS_LOGIC_INDICATORS.fullmatch(part):
            continue
        if _is_system_compound_identifier(parts, idx):
            continue
        found.add(part.lower())


def _annotation_names(annotation: ast.expr | None) -> list[str]:
    """Extract flat identifier names from a type annotation node."""
    if annotation is None:
        return []
    names: list[str] = []
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
    return names


def _collect_import_violations_from_ast(tree: ast.Module) -> list[str]:
    """Return import module paths that violate the utility-module policy.

    Two-layer evaluation for imports:
    1. If the full dotted module path starts with an allowed cross-cutting prefix
       (observability, exceptions, contracts), the import is tolerated regardless of
       any indicator term it might contain.
    2. If the path starts with a prohibited business-domain prefix (use_cases, services,
       policies, workflows, repositories, orchestrat*), the full path is flagged.
    3. For all other imports, individual snake_case parts are checked against
       _BUSINESS_LOGIC_INDICATORS using fullmatch, excluding system-context compounds.

    Returns the list of triggering import paths (one entry per flagged import statement),
    preserving duplicates so the caller can report exact sources.
    """
    flagged: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_allowed_domain_import(module):
                continue
            if _is_prohibited_domain_import(module):
                flagged.append(module)
                continue
            # Fall back to token-level check for non-domain imports
            candidate_found: set[str] = set()
            _check_candidate(module, candidate_found)
            for alias in node.names:
                _check_candidate(alias.name, candidate_found)
            if candidate_found:
                flagged.append(module)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if _is_allowed_domain_import(module):
                    continue
                if _is_prohibited_domain_import(module):
                    flagged.append(module)
                    continue
                candidate_found = set()
                _check_candidate(module, candidate_found)
                if candidate_found:
                    flagged.append(module)

    return flagged


def _collect_definition_violations_from_ast(tree: ast.Module) -> list[str]:
    """Return indicator terms found in definition names, call sites, and annotations.

    Inspects class/function definition names, base classes, decorators, call expressions,
    and type annotations. Import paths are handled separately by
    _collect_import_violations_from_ast and are not re-evaluated here.

    Returns sorted unique indicator terms found.
    """
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            _check_candidate(node.name, found)
            for base in node.bases:
                for name in _annotation_names(base):
                    _check_candidate(name, found)
            for decorator in node.decorator_list:
                for name in _annotation_names(decorator):
                    _check_candidate(name, found)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_candidate(node.name, found)
            for decorator in node.decorator_list:
                for name in _annotation_names(decorator):
                    _check_candidate(name, found)
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                for name in _annotation_names(arg.annotation):
                    _check_candidate(name, found)
            for name in _annotation_names(node.returns):
                _check_candidate(name, found)

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                _check_candidate(node.target.id, found)
            for name in _annotation_names(node.annotation):
                _check_candidate(name, found)

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                _check_candidate(node.func.id, found)
            elif isinstance(node.func, ast.Attribute):
                _check_candidate(node.func.attr, found)

    return sorted(found)


def _extract_business_logic_indicators_via_ast(tree: ast.Module) -> set[str]:
    """Return the set of business-logic indicator terms found in semantic AST nodes.

    Compatibility shim used by unit tests. Evaluates definition names and call sites
    only (import paths are now handled by _collect_import_violations_from_ast).
    """
    return set(_collect_definition_violations_from_ast(tree))


def detect_business_logic_in_utility_modules(paths: list[Path]) -> list[str]:
    """Detect business logic inside utility/helper/common/misc modules.

    Uses two complementary checks per file:

    Import-path check (primary):
        Evaluates the full dotted module path of every import statement.
        - Imports from cross-cutting infrastructure prefixes (observability, exceptions,
          contracts) are explicitly allowed and never flagged.
        - Imports from business-domain prefixes (use_cases, services, policies,
          workflows, repositories, orchestrat*) are always flagged.
        - Other imports fall back to token-level indicator matching.
        Violation message includes the exact triggering import path.

    Definition/call check (secondary):
        Evaluates class/function definition names, call sites, and annotations for
        indicator terms (orchestrat*, use_case, service, repository, aggregate, entity,
        pipeline, workflow). Import paths are not re-checked here.

    Args:
        paths: List of directory paths to scan.

    Returns:
        List of violation messages with file path and the exact import or indicator
        that triggered each violation.
    """
    violations: list[str] = []

    for base_path in paths:
        if not base_path.exists():
            continue

        for file_path in base_path.rglob("*.py"):
            if not any(segment in file_path.parts for segment in _UTILITY_PATH_SEGMENTS):
                continue

            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            try:
                tree = ast.parse(source, filename=str(file_path))
            except SyntaxError:
                continue

            try:
                display_path = file_path.relative_to(_REPO_ROOT)
            except ValueError:
                display_path = file_path

            for import_path in _collect_import_violations_from_ast(tree):
                violations.append(
                    f"Business logic import '{import_path}' in utility module {display_path}"
                )

            for indicator in _collect_definition_violations_from_ast(tree):
                violations.append(
                    f"Business logic indicator '{indicator}' in utility module {display_path}"
                )

    return violations


def _check_catalog_loads() -> list[Violation]:
    """Verify the catalog loads and validates without errors.

    Load errors and schema errors are reported as separate categories
    for diagnostic precision.
    """
    try:
        snapshot = load_catalog_snapshot()
    except FileNotFoundError as exc:
        return [Violation(category="catalog_load_file", message=str(exc), rule_id="CAT001")]
    except Exception as exc:  # loader does not yet declare a typed load error
        return [Violation(category="catalog_load_error", message=str(exc), rule_id="CAT001")]

    try:
        validate_catalog_snapshot(snapshot)
    except CatalogSchemaError as exc:
        return [Violation(category="catalog_schema", message=str(exc), rule_id="CAT002")]

    return []


def _check_extended_blueprint_catalog() -> list[Violation]:
    """Validate extended blueprint catalog consistency."""
    try:
        load_catalog_snapshot()
    except Exception as exc:
        return [
            Violation(
                category="blueprint_catalog_load_error",
                message=str(exc),
                rule_id="BPC001",
            )
        ]

    try:
        extended_snapshot = load_extended_catalog_snapshot()
        validate_extended_catalog_snapshot(extended_snapshot)
    except CatalogSchemaError as exc:
        return [
            Violation(
                category="blueprint_catalog_schema",
                message=str(exc),
                rule_id="BPC002",
            )
        ]
    except Exception as exc:
        return [
            Violation(
                category="blueprint_catalog_validation_error",
                message=str(exc),
                rule_id="BPC002",
            )
        ]

    return []


def _check_no_direct_instantiation() -> list[Violation]:
    """Check for prohibited direct instantiation of infrastructure classes."""
    src_path = _REPO_ROOT / "src"
    violations = detect_direct_infra_instantiations([src_path])
    return [
        Violation(
            category="direct_instantiation",
            message=msg,
            rule_id="INST001",
        )
        for msg in violations
    ]


def _check_suspicious_names() -> list[Violation]:
    """Check for class/function names that indicate inflated or non-canonical responsibilities."""
    src_path = _REPO_ROOT / "src"
    violations = detect_suspicious_names([src_path])
    return [
        Violation(
            category="suspicious_name",
            message=msg,
            severity=Severity.WARNING,
            rule_id="NAME001",
        )
        for msg in violations
    ]


def _check_utility_creep() -> list[Violation]:
    """Check for business logic hidden inside utility/helper/common/misc modules."""
    src_path = _REPO_ROOT / "src"
    violations = detect_business_logic_in_utility_modules([src_path])
    return [
        Violation(
            category="utility_creep",
            message=msg,
            severity=Severity.WARNING,
            rule_id="UTIL001",
        )
        for msg in violations
    ]


_LAYER_IMPORT_RULES: dict[str, tuple[str, list[str]]] = {
    "Domain -> Application/Infrastructure/Public": (
        "src.domain",
        ["src.application", "src.infrastructure", "src.public"],
    ),
    "Application -> Infrastructure": (
        "src.application",
        ["src.infrastructure"],
    ),
    "Public -> Infrastructure": (
        "src.public",
        ["src.infrastructure"],
    ),
}


def _collect_imports_from_file(file_path: Path) -> list[tuple[str, int]]:
    """Return all (dotted_module_path, lineno) pairs imported by the given Python file."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []

    modules: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append((node.module, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.append((alias.name, node.lineno))
    return modules


def report_forbidden_layer_imports() -> dict[str, list[str]]:
    """Scan the codebase and return layer import violations grouped by category.

    Categories:
    - ``Domain -> Application/Infrastructure/Public``: domain code importing from
      application, infrastructure, or public layers.
    - ``Application -> Infrastructure``: application code importing from
      infrastructure.
    - ``Public -> Infrastructure``: public code importing from infrastructure.

    Returns a dict mapping each category name to a list of violation strings
    of the form ``"<relative_path>:<lineno>: imports <module>"``.
    The dict always contains all three category keys (possibly with empty lists).
    """
    src_path = _REPO_ROOT / "src"
    report: dict[str, list[str]] = {category: [] for category in _LAYER_IMPORT_RULES}

    for file_path in src_path.rglob("*.py"):
        try:
            display_path = file_path.relative_to(_REPO_ROOT)
        except ValueError:
            display_path = file_path

        file_module = ".".join(file_path.relative_to(_REPO_ROOT).with_suffix("").parts)

        for category, (owner_prefix, forbidden_prefixes) in _LAYER_IMPORT_RULES.items():
            if not file_module.startswith(owner_prefix):
                continue

            for imported_module, lineno in _collect_imports_from_file(file_path):
                if any(imported_module.startswith(prefix) for prefix in forbidden_prefixes):
                    report[category].append(
                        f"{display_path}:{lineno}: imports {imported_module}"
                    )

    return report


def _write_layer_import_report(report: dict[str, list[str]]) -> None:
    """Write the expanded layer import report to docs/architecture/."""
    report_path = _REPO_ROOT / "docs" / "architecture" / "layer_import_report_expanded.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Layer Import Report — Expanded",
        "",
        "_Generated by `tools/architecture/check_architecture.py`_",
        "",
    ]

    total = sum(len(violations) for violations in report.values())
    lines.append(f"**Total violations: {total}**")
    lines.append("")

    for category, violations in report.items():
        lines.append(f"## {category}")
        lines.append("")
        if violations:
            for violation in violations:
                lines.append(f"- {violation}")
        else:
            lines.append("_No violations found._")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def _check_forbidden_layer_imports() -> list[Violation]:
    """Check for forbidden cross-layer imports and write the expanded report."""
    report = report_forbidden_layer_imports()
    _write_layer_import_report(report)

    violations: list[Violation] = []
    for category, occurrences in report.items():
        for occurrence in occurrences:
            violations.append(
                Violation(
                    category="forbidden_layer_import",
                    message=f"[{category}] {occurrence}",
                    severity=Severity.ERROR,
                    rule_id="LAYER001",
                )
            )
    return violations


def _check_runtime_contract() -> list[Violation]:
    """Validate the last known bootstrap runtime state against the catalog contract.

    Loads the persisted runtime snapshot written by BootstrapContainer.create()
    after a successful assembly. If no snapshot exists (bootstrap has never run or
    the artifact was deleted), the check is skipped — absence is not a violation.

    A present snapshot represents the last verified assembled state. Any drift
    between that state and the catalog (undeclared component, forbidden
    implementation, undeclared entrypoint) surfaces as a RC001 violation.
    """
    try:
        catalog_snapshot = load_catalog_snapshot()
    except Exception as exc:
        return [Violation(category="runtime_contract_load", message=str(exc), rule_id="RC001")]

    runtime_snapshot = load_persisted_runtime_snapshot()
    if runtime_snapshot is None:
        return []

    return _check_runtime_contract_alignment(catalog_snapshot, runtime_snapshot)


def _check_runtime_contract_alignment(
    catalog_snapshot: object,
    runtime_snapshot: object,
) -> list[Violation]:
    """Validate runtime contract and map typed failures to RC00X violations."""
    runtime_state: dict[str, object] = {
        "active_components": list(getattr(runtime_snapshot, "active_components", ())),
        "active_implementations": list(getattr(runtime_snapshot, "active_implementations", ())),
        "public_entrypoints": list(getattr(runtime_snapshot, "public_entrypoints", ())),
        "active_providers": list(getattr(runtime_snapshot, "active_providers", ())),
    }

    runtime_rule_map: tuple[tuple[type[Exception], str], ...] = (
        (UndeclaredActiveComponentError, "RC001"),
        (DuplicateActiveImplementationError, "RC002"),
        (UndeclaredActiveImplementationError, "RC003"),
        (UndeclaredPublicEntrypointError, "RC004"),
        (InactiveLifecycleRuntimeAlignmentError, "RC005"),
        (AmbiguousLifecycleOwnershipError, "RC006"),
        (OwnerLayerRuntimeAlignmentError, "RC007"),
        (TypeError, "RC008"),
    )
    try:
        validate_runtime_contract(catalog_snapshot, runtime_state)  # type: ignore[arg-type]
    except Exception as exc:
        rule_id = "RC999"
        for exception_type, mapped_rule_id in runtime_rule_map:
            if isinstance(exc, exception_type):
                rule_id = mapped_rule_id
                break
        return [
            Violation(
                category="runtime_contract_violation",
                message=str(exc),
                rule_id=rule_id,
            )
        ]
    return []


def _check_wiring_verifier() -> list[Violation]:
    """Verify bidirectional catalog ↔ runtime alignment against the persisted snapshot.

    Loads the runtime snapshot written by BootstrapContainer.create() after a
    successful assembly. If no snapshot exists, the check is skipped.

    A present snapshot is the canonical evidence of the last assembled state.
    Any bidirectional misalignment — undeclared active components, missing
    declared entrypoints, undeclared runtime entrypoints, lateral wiring paths,
    or ambiguous implementation ownership — surfaces as a WV001 violation.
    """
    try:
        catalog_snapshot = load_catalog_snapshot()
    except Exception as exc:
        return [Violation(category="wiring_verifier_load", message=str(exc), rule_id="WV001")]

    runtime_snapshot = load_persisted_runtime_snapshot()
    if runtime_snapshot is None:
        return []

    try:
        verify_catalog_runtime_alignment(catalog_snapshot, runtime_snapshot)
    except Exception as exc:
        return [Violation(category="wiring_verifier", message=str(exc), rule_id="WV001")]

    return []


_FORBIDDEN_WIRING_IMPORT_PREFIXES: tuple[str, ...] = (
    "src.infrastructure",
    "src.persistence",
)
_ALLOWED_BOOTSTRAP_IMPORT_PREFIXES: tuple[str, ...] = (
    "src.bootstrap",
    "src.bootstrap.__init__",
)


def _is_bootstrap_internal_import(module_path: str) -> bool:
    """Return True when module_path targets bootstrap internals."""
    if not module_path.startswith("src.bootstrap"):
        return False
    if module_path in _ALLOWED_BOOTSTRAP_IMPORT_PREFIXES:
        return False
    module_parts = module_path.split(".")
    return "internal" in module_parts


def _check_forbidden_wiring_paths(paths: list[Path]) -> list[str]:
    """Detect forbidden wiring imports from application code."""
    violations: list[str] = []
    for base_path in paths:
        if not base_path.exists():
            continue
        for file_path in base_path.rglob("*.py"):
            if "bootstrap" in file_path.parts:
                continue
            try:
                source = file_path.read_text(encoding="utf-8")
                ast.parse(source, filename=str(file_path))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue

            try:
                display_path = file_path.relative_to(_REPO_ROOT)
            except ValueError:
                display_path = file_path

            for module_path, line_number in _collect_imports_from_file(file_path):
                if any(
                    module_path.startswith(prefix)
                    for prefix in _FORBIDDEN_WIRING_IMPORT_PREFIXES
                ):
                    violations.append(
                        f"{display_path}:{line_number}: imports {module_path} "
                        "(application must depend on abstractions wired via bootstrap)."
                    )
                    continue
                if _is_bootstrap_internal_import(module_path):
                    violations.append(
                        f"{display_path}:{line_number}: imports {module_path} "
                        "(bootstrap internals are forbidden outside bootstrap package root)."
                    )

    return violations


def _check_forbidden_wiring_paths_rule() -> list[Violation]:
    """Wrap forbidden wiring path detection as architecture violations."""
    scan_paths = [_REPO_ROOT / "src" / "application"]
    violations = _check_forbidden_wiring_paths(scan_paths)
    return [
        Violation(
            category="forbidden_wiring_path",
            message=message,
            rule_id="WIRING001",
            severity=Severity.ERROR,
        )
        for message in violations
    ]


def _parse_implementation_reference(reference: str) -> tuple[str, str] | None:
    """Parse implementation reference into module path and symbol name."""
    if ":" in reference:
        module_path, symbol_name = reference.split(":", maxsplit=1)
        if module_path and symbol_name:
            return module_path, symbol_name
        return None
    if "." not in reference:
        return None
    module_path, symbol_name = reference.rsplit(".", maxsplit=1)
    if not module_path or not symbol_name:
        return None
    return module_path, symbol_name


def _resolve_module_source_paths(module_path: str) -> list[Path]:
    """Return source paths for a module path when present in repository."""
    module_relative_path = Path(*module_path.split("."))
    module_file_path = _REPO_ROOT / f"{module_relative_path}.py"
    package_directory_path = _REPO_ROOT / module_relative_path
    if module_file_path.exists():
        return [module_file_path]
    if package_directory_path.is_dir():
        return sorted(package_directory_path.rglob("*.py"))
    return []


def _collect_module_symbols(module_source_path: Path) -> set[str]:
    """Collect top-level symbols from a python module source file."""
    try:
        source = module_source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_source_path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return set()

    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols.add(node.target.id)
    return symbols


def _check_implementation_existence(catalog_snapshot: object) -> list[Violation]:
    """Ensure every declared allowed implementation points to an existing symbol."""
    violations: list[Violation] = []
    module_symbols_cache: dict[Path, set[str]] = {}

    for responsibility in getattr(catalog_snapshot, "responsibilities", ()):
        allowed_implementations = getattr(
            responsibility,
            "allowed_implementations",
            (),
        )
        responsibility_id = getattr(responsibility, "responsibility_id", "unknown")
        for implementation_reference in allowed_implementations:
            parsed_reference = _parse_implementation_reference(str(implementation_reference))
            if parsed_reference is None:
                violations.append(
                    Violation(
                        category="implementation_not_found",
                        message=(
                            f"Invalid implementation reference '{implementation_reference}' "
                            f"in responsibility '{responsibility_id}'."
                        ),
                        rule_id="IMPL001",
                    )
                )
                continue

            module_path, symbol_name = parsed_reference
            module_source_paths = _resolve_module_source_paths(module_path)
            if not module_source_paths:
                violations.append(
                    Violation(
                        category="implementation_not_found",
                        message=(
                            f"Implementation module '{module_path}' not found for "
                            f"responsibility '{responsibility_id}'."
                        ),
                        rule_id="IMPL001",
                    )
                )
                continue

            symbol_exists = False
            for module_source_path in module_source_paths:
                module_symbols = module_symbols_cache.setdefault(
                    module_source_path,
                    _collect_module_symbols(module_source_path),
                )
                if symbol_name in module_symbols:
                    symbol_exists = True
                    break

            if not symbol_exists:
                violations.append(
                    Violation(
                        category="implementation_not_found",
                        message=(
                            f"Implementation '{symbol_name}' not found in module "
                            f"'{module_path}' for responsibility '{responsibility_id}'."
                        ),
                        rule_id="IMPL001",
                    )
                )

    return violations


def _check_declared_implementation_existence() -> list[Violation]:
    """Load catalog and validate implementation references existence."""
    try:
        catalog_snapshot = load_catalog_snapshot()
    except Exception as exc:
        return [
            Violation(
                category="implementation_not_found_load",
                message=str(exc),
                rule_id="IMPL001",
            )
        ]
    return _check_implementation_existence(catalog_snapshot)


def run_architecture_checks() -> list[Violation]:
    """Run all architecture checks and return a list of Violation instances.

    Returns an empty list when no violations are found.
    """
    violations: list[Violation] = []
    violations.extend(_check_catalog_loads())
    violations.extend(_check_extended_blueprint_catalog())
    violations.extend(_check_runtime_contract())
    violations.extend(_check_wiring_verifier())
    violations.extend(_check_no_direct_instantiation())
    violations.extend(_check_suspicious_names())
    violations.extend(_check_utility_creep())
    violations.extend(_check_forbidden_layer_imports())
    violations.extend(_check_forbidden_wiring_paths_rule())
    violations.extend(_check_declared_implementation_existence())
    return violations


def main() -> int:
    """Entry point: print violations and return exit code.

    Returns 0 when there are no violations, 1 otherwise.
    """
    violations = run_architecture_checks()

    if violations:
        print("Architecture violations found:")
        for violation in violations:
            print(f"  {violation}")
        return 1

    print("No architecture violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
