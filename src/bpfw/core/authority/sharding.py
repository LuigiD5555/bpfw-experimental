"""Shard decision engine for BPFW authority sharding."""

import re
from pathlib import Path
from typing import Any

from bpfw.core.authority.document import AuthorityDocument
from bpfw.core.authority.errors import InvalidShardPathError


class ShardDecisionEngine:
    """Decide which shard a block should live in based on authority config.

    Supported strategies:
    - domain: Use block domain to determine shard
    - path: Use code path to determine shard
    - architecture_layer: Use architecture.yaml layer mappings

    All generated shard paths are confined to bpfw/blocks/.
    """

    SHARD_BASE_DIR = Path("bpfw/blocks")

    # Valid shard name characters (alphanumeric, underscore, hyphen)
    VALID_SHARD_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")

    def __init__(self, authority_config: dict[str, Any]) -> None:
        """Initialize the shard decision engine.

        Args:
            authority_config: The authority configuration dictionary.
        """
        self.authority_config = authority_config or {}
        self.shard_strategy = self.authority_config.get("shard_strategy", "domain")
        self.default_shard = self.authority_config.get("default_shard", "bpfw/blocks/core.yaml")
        self.auto_create_shards = self.authority_config.get("auto_create_shards", True)

    def decide_shard_for_block(
        self,
        block: dict[str, Any],
        document: AuthorityDocument | None = None,
    ) -> Path:
        """Decide which shard a block should live in.

        Args:
            block: The block dictionary.
            document: Optional AuthorityDocument for architecture strategy.

        Returns:
            Project-relative path to the expected shard file.

        Raises:
            InvalidShardPathError: If the generated shard path is invalid.
        """
        strategy = self.shard_strategy

        if strategy == "domain":
            return self._decide_by_domain(block)
        elif strategy == "path":
            return self._decide_by_path(block)
        elif strategy == "architecture_layer":
            if document is None:
                # Fall back to domain if no document provided
                return self._decide_by_domain(block)
            return self._decide_by_architecture_layer(block, document)
        else:
            # Unknown strategy, use default
            return Path(self.default_shard)

    def _decide_by_domain(self, block: dict[str, Any]) -> Path:
        """Decide shard based on block domain.

        Args:
            block: The block dictionary.

        Returns:
            Project-relative path to the shard file.
        """
        domain = block.get("domain")

        if domain and isinstance(domain, str) and domain.strip():
            # Normalize domain to shard name
            shard_name = self.normalize_shard_name(domain)
            return self.SHARD_BASE_DIR / f"{shard_name}.yaml"

        # No domain or empty domain, use default shard
        return Path(self.default_shard)

    def _decide_by_path(self, block: dict[str, Any]) -> Path:
        """Decide shard based on code path.

        Args:
            block: The block dictionary.

        Returns:
            Project-relative path to the shard file.
        """
        code = block.get("code")
        if not isinstance(code, dict):
            return Path(self.default_shard)

        code_path = code.get("path")
        if not isinstance(code_path, str) or not code_path.strip():
            return Path(self.default_shard)

        # Extract first directory after src/bpfw
        path_parts = Path(code_path).parts

        # Look for src/bpfw pattern
        try:
            src_index = path_parts.index("src")
            bpfw_index = path_parts.index("bpfw", src_index)

            # Get the next directory after src/bpfw
            if bpfw_index + 1 < len(path_parts):
                next_dir = path_parts[bpfw_index + 1]
                shard_name = self.normalize_shard_name(next_dir)
                return self.SHARD_BASE_DIR / f"{shard_name}.yaml"
        except ValueError:
            # Pattern not found
            pass

        # Fallback to default shard
        return Path(self.default_shard)

    def _decide_by_architecture_layer(
        self,
        block: dict[str, Any],
        document: AuthorityDocument,
    ) -> Path:
        """Decide shard based on architecture layer mapping.

        Args:
            block: The block dictionary.
            document: The authority document.

        Returns:
            Project-relative path to the shard file.
        """
        code = block.get("code")
        if not isinstance(code, dict):
            return self._decide_by_domain(block)

        code_path = code.get("path")
        if not isinstance(code_path, str) or not code_path.strip():
            return self._decide_by_domain(block)

        # Try to load architecture.yaml
        project_root = document.index.path.parent.parent
        architecture_path = project_root / "bpfw" / "architecture.yaml"

        if not architecture_path.exists():
            # No architecture file, fall back to domain
            return self._decide_by_domain(block)

        try:
            import yaml
            with open(architecture_path, "r", encoding="utf-8") as f:
                arch_data = yaml.safe_load(f)
        except (OSError, ImportError, yaml.YAMLError):
            # Cannot load architecture, fall back to domain
            return self._decide_by_domain(block)

        if not isinstance(arch_data, dict):
            return self._decide_by_domain(block)

        arch = arch_data.get("architecture")
        if not isinstance(arch, dict):
            return self._decide_by_domain(block)

        layers = arch.get("layers")
        if not isinstance(layers, list):
            return self._decide_by_domain(block)

        # Find matching layer
        for layer in layers:
            if not isinstance(layer, dict):
                continue

            layer_name = layer.get("name")
            layer_paths = layer.get("paths", [])

            if not isinstance(layer_name, str) or not layer_name:
                continue

            if not isinstance(layer_paths, list):
                continue

            # Check if code path matches any layer path
            for layer_path_pattern in layer_paths:
                if not isinstance(layer_path_pattern, str):
                    continue

                # Simple prefix match
                if code_path.startswith(layer_path_pattern):
                    shard_name = self.normalize_shard_name(layer_name)
                    return self.SHARD_BASE_DIR / f"{shard_name}.yaml"

        # No layer match, fall back to domain
        return self._decide_by_domain(block)

    def normalize_shard_name(self, value: str) -> str:
        """Normalize a value to a safe shard filename.

        Normalization rules:
        - Convert to lowercase
        - Replace spaces with underscores
        - Replace slashes with underscores
        - Remove invalid characters
        - Ensure the result is a valid shard name

        Args:
            value: The value to normalize (e.g., domain name).

        Returns:
            Normalized shard filename without extension.

        Raises:
            InvalidShardPathError: If the value cannot be normalized safely.
        """
        if not value or not isinstance(value, str):
            return "uncategorized"

        # Convert to lowercase
        normalized = value.lower()

        # Replace spaces and slashes with underscores
        normalized = re.sub(r"[\s/]+", "_", normalized)

        # Remove any characters that are not alphanumeric, underscore, or hyphen
        normalized = re.sub(r"[^a-z0-9_\-]", "", normalized)

        # Collapse multiple underscores/hyphens
        normalized = re.sub(r"[_\-]+", "_", normalized)

        # Remove leading/trailing underscores
        normalized = normalized.strip("_")

        # Ensure it's not empty
        if not normalized:
            return "uncategorized"

        # Validate against pattern
        if not self.VALID_SHARD_NAME_PATTERN.match(normalized):
            # Should not happen after normalization, but check anyway
            return "uncategorized"

        # Ensure the shard name doesn't attempt path traversal
        if ".." in normalized or normalized.startswith("/") or normalized.startswith("\\"):
            raise InvalidShardPathError(
                f"Invalid shard name derived from '{value}': '{normalized}'. "
                "Shard names cannot contain path components."
            )

        return normalized

    def is_shard_path_valid(self, shard_path: Path) -> bool:
        """Check if a shard path is within the allowed directory.

        Args:
            shard_path: Project-relative shard path to validate.

        Returns:
            True if the path is valid, False otherwise.
        """
        try:
            # Convert to absolute path relative to project root
            resolved = (self.SHARD_BASE_DIR.parent / shard_path).resolve()
            base_resolved = self.SHARD_BASE_DIR.resolve()

            # Check if it's within the base directory
            try:
                resolved.relative_to(base_resolved)
                return True
            except ValueError:
                return False
        except Exception:
            return False

