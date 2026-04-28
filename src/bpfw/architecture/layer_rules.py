"""Layer resolution and permission rules for architecture checks."""

from __future__ import annotations

from pathlib import Path

from bpfw.architecture.profile import LayerProfile



def resolve_layer_for_file(
    file_path: Path,
    project_root: Path,
    layers: list[LayerProfile],
) -> LayerProfile | None:
    """Return the matching layer for a file path, if any."""

    for layer in layers:
        layer_root = (project_root / layer.path).resolve()
        candidate = file_path.resolve()
        try:
            candidate.relative_to(layer_root)
            return layer
        except ValueError:
            continue
    return None



def is_import_allowed(
    source_layer: LayerProfile,
    target_layer: LayerProfile,
) -> bool:
    """Check if one layer may import another."""

    if source_layer.name == target_layer.name:
        return True
    return target_layer.name in source_layer.may_import
