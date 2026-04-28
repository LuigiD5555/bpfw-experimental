from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpfw.init.scanner import MechanicalScanResult


@dataclass(slots=True)
class GeneratedBaseline:
    """Represents generated baseline file paths."""

    blueprint_path: Path
    architecture_path: Path
    report_path: Path


class InitialBlueprintGenerator:
    """Generates an initial blueprint and architecture profile from scan facts."""

    def generate(self, project_root: Path, scan_result: MechanicalScanResult) -> GeneratedBaseline:
        """Create generated baseline files from a mechanical scan."""
        blueprint_path = project_root / "blueprint.generated.yaml"
        architecture_path = project_root / "architecture.generated.yaml"
        report_path = project_root / ".bpfw/scan_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        blueprint_path.write_text(self._build_blueprint(scan_result=scan_result), encoding="utf-8")
        architecture_path.write_text(self._build_architecture(scan_result=scan_result), encoding="utf-8")
        report_path.write_text(self._build_report(scan_result=scan_result), encoding="utf-8")
        return GeneratedBaseline(blueprint_path=blueprint_path, architecture_path=architecture_path, report_path=report_path)

    def generate_empty_baseline(self, project_root: Path) -> GeneratedBaseline:
        blueprint_path = project_root / "blueprint.yaml"
        architecture_path = project_root / "architecture.yaml"
        report_path = project_root / ".bpfw/scan_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        blueprint_path.write_text(
            (
                "version: 1\n"
                "responsibilities: []\n"
                "locked_resources:\n"
                "  - resource_id: project_blueprint\n"
                "    path: blueprint.yaml\n"
                "    mutability: locked\n"
                "    owner: project_owner\n"
            ),
            encoding="utf-8",
        )
        architecture_path.write_text(
            (
                "architecture_profile:\n"
                "  id: baseline\n"
                "  layers:\n"
                "    - name: domain\n"
                "      path: src/domain\n"
                "      may_import: []\n"
                "    - name: application\n"
                "      path: src/application\n"
                "      may_import: [domain]\n"
                "    - name: infrastructure\n"
                "      path: src/infrastructure\n"
                "      may_import: [application, domain]\n"
                "    - name: public\n"
                "      path: src/public\n"
                "      may_import: [application, domain]\n"
                "  composition_roots:\n"
                "    - src/bootstrap/wiring.py\n"
            ),
            encoding="utf-8",
        )
        report_path.write_text("# BPFW Mechanical Scan\n\nNo source files were discovered.\n", encoding="utf-8")
        return GeneratedBaseline(blueprint_path=blueprint_path, architecture_path=architecture_path, report_path=report_path)

    def _build_blueprint(self, scan_result: MechanicalScanResult) -> str:
        lines = ["version: 1", "responsibilities:"]
        responsibilities = self._group_responsibilities(scan_result=scan_result)
        if not responsibilities:
            lines.append("  []")
        for responsibility in responsibilities:
            lines.extend(responsibility)
        lines.append("locked_resources: []")
        return "\n".join(lines) + "\n"

    def _group_responsibilities(self, scan_result: MechanicalScanResult) -> list[list[str]]:
        grouped: dict[str, dict[str, list[str] | str]] = {}
        symbols_by_file: dict[str, list[str]] = {}
        for symbol in scan_result.symbols:
            symbols_by_file.setdefault(symbol.file_path, []).append(symbol.name)

        for file_path in scan_result.files:
            path_parts = Path(file_path).parts
            if len(path_parts) < 2 or path_parts[0] != "src":
                continue
            owner_layer = path_parts[1]
            if owner_layer not in {"domain", "application", "infrastructure", "public"}:
                continue
            key_part = path_parts[2] if len(path_parts) > 2 else Path(file_path).stem
            identifier = f"{owner_layer}_{Path(key_part).stem}".replace("-", "_")
            grouped.setdefault(identifier, {"owner_layer": owner_layer, "files": [], "symbols": []})
            grouped[identifier]["files"].append(file_path)
            grouped[identifier]["symbols"].extend(symbols_by_file.get(file_path, []))

        blocks: list[list[str]] = []
        for responsibility_id in sorted(grouped):
            owner_layer = str(grouped[responsibility_id]["owner_layer"])
            canonical_name = "".join(word.capitalize() for word in responsibility_id.split("_"))
            files = sorted(set(grouped[responsibility_id]["files"]))
            symbols = sorted(set(grouped[responsibility_id]["symbols"]))
            block = [
                f"  - responsibility_id: {responsibility_id}",
                f"    canonical_name: {canonical_name}",
                f"    owner_layer: {owner_layer}",
                "    lifecycle_state: active",
                "    allowed_files:",
            ]
            if files:
                block.extend([f"      - {file_path}" for file_path in files])
            else:
                block.append("      []")
            block.append("    allowed_symbols:")
            if symbols:
                block.extend([f"      - {symbol_name}" for symbol_name in symbols])
            else:
                block.append("      []")
            implementation_id = f"{responsibility_id}_default"
            class_name = self._primary_class_name(symbols=symbols, file_path=files[0] if files else "")
            impl_file = files[0] if files else ""
            block.append("    allowed_implementations:")
            block.append(f"      - implementation_id: {implementation_id}")
            block.append(f"        class_name: {class_name}")
            block.append(f"        file: {impl_file}")
            block.append("        lifecycle_state: active")
            block.append("        replacement_id: null")
            block.append("        disabled_reason: null")
            block.append("        removal_plan: null")
            block.append(f"    active_implementation: {implementation_id}")
            block.append("    forbidden_duplicates: []")
            block.append("    mutability: editable")
            block.append("    owner: project_owner")
            block.append("    source: auto_discovered")
            blocks.append(block)
        return blocks

    def _build_architecture(self, scan_result: MechanicalScanResult) -> str:
        discovered_layers = sorted(set(layer for layer in scan_result.probable_layers.values() if layer))
        if not discovered_layers:
            discovered_layers = ["domain", "application", "infrastructure", "public"]
        path_by_layer = {
            "domain": "src/domain",
            "application": "src/application",
            "infrastructure": "src/infrastructure",
            "public": "src/public",
        }
        may_import_by_layer = {
            "domain": [],
            "application": ["domain"],
            "infrastructure": ["application", "domain"],
            "public": ["application", "domain"],
        }
        lines = ["architecture_profile:", "  id: generated", "  layers:"]
        for layer_name in discovered_layers:
            lines.append(f"    - name: {layer_name}")
            lines.append(f"      path: {path_by_layer.get(layer_name, f'src/{layer_name}')}")
            allowed = [item for item in may_import_by_layer.get(layer_name, []) if item in discovered_layers]
            if allowed:
                allowed_items = ", ".join(allowed)
                lines.append(f"      may_import: [{allowed_items}]")
            else:
                lines.append("      may_import: []")
        lines.append("  composition_roots:")
        lines.append("    - src/bootstrap/wiring.py")
        return "\n".join(lines) + "\n"

    def _primary_class_name(self, symbols: list[str], file_path: str) -> str:
        for symbol_name in symbols:
            if "." not in symbol_name:
                return symbol_name
        file_stem = Path(file_path).stem if file_path else "Implementation"
        return "".join(part.capitalize() for part in file_stem.split("_"))

    def _build_report(self, scan_result: MechanicalScanResult) -> str:
        class_count = len([symbol for symbol in scan_result.symbols if symbol.kind == "class"])
        function_count = len([symbol for symbol in scan_result.symbols if symbol.kind == "function"])
        probable_responsibilities = len(self._group_responsibilities(scan_result=scan_result))
        probable_layers = len(set(scan_result.probable_layers.values()))
        report_lines = [
            "# BPFW Mechanical Scan",
            "",
            f"- Python files: {len(scan_result.files)}",
            f"- Classes: {class_count}",
            f"- Functions: {function_count}",
            f"- Probable responsibilities: {probable_responsibilities}",
            f"- Probable layers: {probable_layers}",
            "",
            "## Probable entrypoints",
        ]
        if scan_result.probable_entrypoints:
            report_lines.extend([f"- {item}" for item in scan_result.probable_entrypoints])
        else:
            report_lines.append("- none")
        return "\n".join(report_lines) + "\n"
