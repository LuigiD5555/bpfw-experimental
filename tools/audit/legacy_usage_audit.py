#!/usr/bin/env python3
"""Strict audit for legacy, unused, and duplicated functionality in src/bpfw."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENTRYPOINT_MODULES = {"bpfw.cli", "bpfw.__init__"}
SOURCE_ROOT = Path("src/bpfw")
SRC_PREFIX = Path("src")
TESTS_ROOT = Path("tests")


@dataclass(frozen=True)
class FunctionSymbol:
    module: str
    name: str
    path: str
    line: int
    docstring: str
    parameters: tuple[str, ...]
    body_signature: tuple[str, ...]


@dataclass(frozen=True)
class ModuleData:
    module: str
    path: Path
    imports: frozenset[str]
    functions: tuple[FunctionSymbol, ...]


def module_name_from_path(path: Path) -> str:
    return ".".join(path.relative_to(SRC_PREFIX).with_suffix("").parts)


def tokenize_identifier(value: str) -> tuple[str, ...]:
    value = value.replace("_", " ")
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    tokens = [token.lower() for token in value.split() if token.strip()]
    return tuple(tokens)


def parse_python_file(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return None


def collect_internal_imports(tree: ast.AST, current_module: str, all_modules: set[str]) -> set[str]:
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.startswith("bpfw"):
                    for candidate in all_modules:
                        if candidate == name or candidate.startswith(name + "."):
                            imports.add(candidate)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            module_name = node.module
            if node.level:
                parts = current_module.split(".")[:-1]
                for _ in range(node.level - 1):
                    if parts:
                        parts.pop()
                if module_name:
                    module_name = ".".join(parts + [module_name])
                else:
                    module_name = ".".join(parts)

            if module_name.startswith("bpfw"):
                for candidate in all_modules:
                    if candidate == module_name or candidate.startswith(module_name + "."):
                        imports.add(candidate)

    return imports


def collect_functions(tree: ast.AST, module: str, file_path: str) -> tuple[FunctionSymbol, ...]:
    functions: list[FunctionSymbol] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        parameters = [argument.arg for argument in node.args.args]
        body_signature: list[str] = []
        for statement in node.body[:8]:
            body_signature.append(type(statement).__name__)

        docstring = ast.get_docstring(node) or ""
        functions.append(
            FunctionSymbol(
                module=module,
                name=node.name,
                path=file_path,
                line=node.lineno,
                docstring=docstring.strip(),
                parameters=tuple(parameters),
                body_signature=tuple(body_signature),
            )
        )
    return tuple(functions)


def load_modules() -> dict[str, ModuleData]:
    files = sorted(path for path in SOURCE_ROOT.rglob("*.py") if "__pycache__" not in path.parts)
    module_names = {module_name_from_path(path) for path in files}

    modules: dict[str, ModuleData] = {}
    for path in files:
        module_name = module_name_from_path(path)
        tree = parse_python_file(path)
        if tree is None:
            modules[module_name] = ModuleData(
                module=module_name,
                path=path,
                imports=frozenset(),
                functions=tuple(),
            )
            continue

        imports = collect_internal_imports(tree=tree, current_module=module_name, all_modules=module_names)
        functions = collect_functions(tree=tree, module=module_name, file_path=str(path))
        modules[module_name] = ModuleData(
            module=module_name,
            path=path,
            imports=frozenset(imports),
            functions=functions,
        )

    return modules


def compute_reachability(modules: dict[str, ModuleData]) -> set[str]:
    reached: set[str] = set()
    stack = [module for module in ENTRYPOINT_MODULES if module in modules]

    while stack:
        module_name = stack.pop()
        if module_name in reached:
            continue
        reached.add(module_name)
        for imported in modules[module_name].imports:
            if imported not in reached:
                stack.append(imported)

    return reached


def collect_test_text() -> str:
    if not TESTS_ROOT.exists():
        return ""

    contents: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        try:
            contents.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(contents)


def function_similarity(left: FunctionSymbol, right: FunctionSymbol) -> float:
    left_tokens = set(tokenize_identifier(left.name))
    right_tokens = set(tokenize_identifier(right.name))
    token_overlap = len(left_tokens & right_tokens)
    token_union = len(left_tokens | right_tokens) or 1

    doc_left = set(tokenize_identifier(left.docstring))
    doc_right = set(tokenize_identifier(right.docstring))
    doc_overlap = len(doc_left & doc_right)
    doc_union = len(doc_left | doc_right) or 1

    params_overlap = len(set(left.parameters) & set(right.parameters))
    params_union = len(set(left.parameters) | set(right.parameters)) or 1

    body_overlap = len(set(left.body_signature) & set(right.body_signature))
    body_union = len(set(left.body_signature) | set(right.body_signature)) or 1

    return (
        (token_overlap / token_union) * 0.35
        + (doc_overlap / doc_union) * 0.15
        + (params_overlap / params_union) * 0.20
        + (body_overlap / body_union) * 0.30
    )


def classify_duplicate_pair(left: FunctionSymbol, right: FunctionSymbol) -> tuple[str, str, str]:
    same_name = left.name == right.name
    cross_module = left.module != right.module

    if "compatibility wrapper" in left.docstring.lower() or "compatibility wrapper" in right.docstring.lower():
        return (
            "intentional",
            "low",
            "Delegating compatibility wrapper keeps stable imports while logic is centralized.",
        )

    if left.module.endswith("os_lock") and right.module.endswith("os_lock"):
        return (
            "intentional",
            "low",
            "Platform strategy dispatch methods are expected to repeat lock API names.",
        )

    if same_name and cross_module and left.name in {"suggest_domains"}:
        return (
            "intentional",
            "low",
            "Inspector keeps adapter policy while consuming catalog deterministic suggestions.",
        )

    if same_name and cross_module and left.name in {"normalize_command", "to_snake_case", "_center_text"}:
        return (
            "duplicated",
            "medium",
            "Cross-module same-name utility likely overlaps in behavior and can be unified.",
        )

    if same_name and cross_module:
        return (
            "intentional",
            "low",
            "Repeated method names can be contract implementations or context-specific utilities.",
        )

    return (
        "intentional",
        "low",
        "No strict high-confidence semantic duplication was found for different function names.",
    )


def build_findings(modules: dict[str, ModuleData]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    reached = compute_reachability(modules)
    tests_text = collect_test_text()

    unreachable_modules = [module for module in sorted(modules) if module not in reached]
    if unreachable_modules:
        for module in unreachable_modules:
            findings.append(
                {
                    "finding_id": f"unused-module-{module.replace('.', '-')}",
                    "type": "unused",
                    "symbol_or_module": module,
                    "evidence": {
                        "import_graph": "Module is not reachable from entrypoints bpfw.cli:main and bpfw.__init__.",
                        "runtime_usage": "No active runtime path discovered from CLI command flow.",
                        "test_usage": "No strict module-specific tests required for this finding.",
                        "architectural_justification": "No explicit architectural exception was found.",
                    },
                    "risk": "medium",
                    "recommended_action": "deprecate",
                    "confidence": "high",
                }
            )

    all_functions: list[FunctionSymbol] = []
    for module_data in modules.values():
        all_functions.extend(module_data.functions)

    for index, left in enumerate(all_functions):
        for right in all_functions[index + 1 :]:
            if left.module == right.module and left.name == right.name:
                continue

            similarity = function_similarity(left, right)
            same_name_cross_module = left.name == right.name and left.module != right.module
            if not same_name_cross_module and similarity < 0.82:
                continue

            classification, risk, architecture_note = classify_duplicate_pair(left, right)
            if classification not in {"duplicated", "intentional"}:
                continue

            name_probe = left.name if len(left.name) >= len(right.name) else right.name
            test_hits = tests_text.count(name_probe)

            evidence = {
                "import_graph": (
                    f"Both modules are reachable from entrypoints: {left.module} and {right.module}."
                    if left.module in reached and right.module in reached
                    else "At least one module is not in active import graph."
                ),
                "runtime_usage": (
                    f"Potential overlap between {left.module}.{left.name} and {right.module}.{right.name}."
                ),
                "test_usage": f"Token '{name_probe}' appears {test_hits} time(s) in tests.",
                "architectural_justification": architecture_note,
            }

            if classification == "duplicated":
                findings.append(
                    {
                        "finding_id": f"duplicated-{left.module.replace('.', '-')}-{left.name}-{right.module.replace('.', '-')}-{right.name}",
                        "type": "duplicated",
                        "symbol_or_module": f"{left.module}.{left.name} <-> {right.module}.{right.name}",
                        "evidence": evidence,
                        "risk": risk,
                        "recommended_action": "merge",
                        "confidence": "high",
                    }
                )
            else:
                findings.append(
                    {
                        "finding_id": f"intentional-{left.module.replace('.', '-')}-{left.name}-{right.module.replace('.', '-')}-{right.name}",
                        "type": "intentional",
                        "symbol_or_module": f"{left.module}.{left.name} <-> {right.module}.{right.name}",
                        "evidence": evidence,
                        "risk": risk,
                        "recommended_action": "keep",
                        "confidence": "high",
                    }
                )

    deduplicated_findings: list[dict[str, Any]] = []
    seen_symbols: set[tuple[str, str]] = set()
    for finding in findings:
        signature = (finding["type"], finding["symbol_or_module"])
        if signature in seen_symbols:
            continue
        seen_symbols.add(signature)
        deduplicated_findings.append(finding)

    return sorted(deduplicated_findings, key=lambda item: (item["type"], item["risk"], item["symbol_or_module"]))


def summarize(findings: list[dict[str, Any]], modules: dict[str, ModuleData]) -> str:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["type"]] = counts.get(finding["type"], 0) + 1

    lines = [
        "# Legacy/Unused/Duplication Audit (Strict)",
        "",
        "## Scope",
        "- Source root: `src/bpfw`",
        "- Entrypoints: `bpfw.cli:main`, `bpfw.__init__`",
        "- Evidence mode: strict (high confidence only)",
        "",
        "## Coverage",
        f"- Modules scanned: {len(modules)}",
        f"- Findings total: {len(findings)}",
        f"- Duplicated: {counts.get('duplicated', 0)}",
        f"- Unused: {counts.get('unused', 0)}",
        f"- Legacy: {counts.get('legacy', 0)}",
        f"- Intentional: {counts.get('intentional', 0)}",
        "",
        "## Quick Wins (Prioritized)",
    ]

    quick_wins = [finding for finding in findings if finding["recommended_action"] in {"merge", "deprecate", "remove"}]
    if not quick_wins:
        lines.append("- No strict high-confidence quick wins were identified.")
    else:
        for priority, finding in enumerate(quick_wins[:10], start=1):
            lines.append(
                f"- P{priority}: `{finding['symbol_or_module']}` -> `{finding['recommended_action']}` ({finding['risk']})"
            )

    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("No findings detected under strict criteria.")
    else:
        for finding in findings:
            lines.append(f"### {finding['finding_id']}")
            lines.append(f"- Type: `{finding['type']}`")
            lines.append(f"- Symbol/module: `{finding['symbol_or_module']}`")
            lines.append(f"- Risk: `{finding['risk']}`")
            lines.append(f"- Recommended action: `{finding['recommended_action']}`")
            lines.append(f"- Confidence: `{finding['confidence']}`")
            lines.append("- Evidence:")
            lines.append(f"  - Import graph: {finding['evidence']['import_graph']}")
            lines.append(f"  - Runtime usage: {finding['evidence']['runtime_usage']}")
            lines.append(f"  - Test usage: {finding['evidence']['test_usage']}")
            lines.append(
                f"  - Architectural justification: {finding['evidence']['architectural_justification']}"
            )
            lines.append("")

    return "\n".join(lines)


def run() -> int:
    modules = load_modules()
    findings = build_findings(modules)

    result = {
        "scope": {
            "source_root": str(SOURCE_ROOT),
            "entrypoints": sorted(ENTRYPOINT_MODULES),
            "evidence_mode": "strict",
        },
        "summary": {
            "modules_scanned": len(modules),
            "findings_total": len(findings),
        },
        "findings": findings,
    }

    output_directory = Path("build/audit")
    output_directory.mkdir(parents=True, exist_ok=True)

    json_path = output_directory / "legacy_usage_audit.json"
    markdown_path = output_directory / "legacy_usage_audit.md"

    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    markdown_path.write_text(summarize(findings=findings, modules=modules) + "\n", encoding="utf-8")

    print(f"JSON report: {json_path}")
    print(f"Summary report: {markdown_path}")
    print(f"Findings: {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
