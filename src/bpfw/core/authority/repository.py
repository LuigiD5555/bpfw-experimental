"""Authority repository for BPFW sharded blueprint loading and validation."""

from pathlib import Path
from typing import Any

from bpfw.core.authority.document import AuthorityDocument
from bpfw.core.authority.index import AuthorityIndex
from bpfw.core.authority.persistence import AuthorityPersistenceEngine, AuthorityPersistenceResult
from bpfw.core.authority.shard import AuthorityShard
from bpfw.reports.finding import Finding, FINDING_SEVERITY_BLOCK


class AuthorityRepository:
    """Load, validate, and save sharded authority documents.
    
    This repository:
    - Loads the authority index and all shard files
    - Composes a unified blueprint_data dictionary
    - Tracks block origins
    - Validates for duplicate IDs and reports duplicate code declarations
    - Saves documents through the persistence engine
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the authority repository.
        
        Args:
            project_root: The project root directory.
        """
        self.project_root = project_root
        self._document: AuthorityDocument | None = None
        self._persistence_engine: AuthorityPersistenceEngine | None = None

    def load(self) -> AuthorityDocument:
        """Load the authority document from the project.
        
        Returns:
            Loaded AuthorityDocument.
        
        Raises:
            InvalidAuthorityIndexError: If the index is invalid.
            InvalidAuthorityShardError: If any shard is invalid.
            MissingShardError: If a referenced shard is missing.
            DuplicateBlockIdError: If duplicate block IDs are found.
        """
        # Load index
        index = AuthorityIndex.load(self.project_root)

        # Get includes
        include_paths = index.get_includes()

        # Load shards
        shards: dict[Path, AuthorityShard] = {}
        block_origins: dict[str, Path] = {}
        all_blocks: list[dict[str, Any]] = []

        # Track for duplicate detection
        seen_block_ids: dict[str, list[Path]] = {}
        seen_code_declarations: dict[str, list[str]] = {}

        for shard_path in include_paths:
            # Load shard
            shard = AuthorityShard.load(self.project_root, shard_path)
            shards[shard_path] = shard

            # Process blocks
            for block in shard.get_blocks():
                block_id = block.get("id")
                if not block_id:
                    continue

                # Track origin
                block_origins[block_id] = shard_path
                all_blocks.append(block)

                # Check for duplicate block ID
                if block_id in seen_block_ids:
                    seen_block_ids[block_id].append(shard_path)
                else:
                    seen_block_ids[block_id] = [shard_path]

                # Track code declaration
                code = block.get("code")
                if isinstance(code, dict):
                    code_path = code.get("path", "")
                    symbol = code.get("symbol", "")
                    kind = code.get("kind", "")

                    if code_path and symbol and kind:
                        code_key = f"{code_path}:{symbol}:{kind}"

                        if code_key in seen_code_declarations:
                            seen_code_declarations[code_key].append(block_id)
                        else:
                            seen_code_declarations[code_key] = [block_id]

        # Check for duplicate block IDs
        for block_id, locations in seen_block_ids.items():
            if len(locations) > 1:
                from bpfw.core.authority.errors import DuplicateBlockIdError
                raise DuplicateBlockIdError(
                    f"Duplicate block ID '{block_id}' found in shards: {locations}"
                )

        # Duplicate code declarations are validation findings, not load errors.
        # Loading must remain possible so Inspector and Drift Gate can show and
        # repair the conflicting declarations instead of crashing before the UI
        # opens. Duplicate block IDs still block loading because origins would be
        # ambiguous, but duplicate code targets can be represented safely.
        _ = seen_code_declarations

        # Compose unified blueprint_data
        blueprint_data = index.data.copy()
        blueprint_data["blocks"] = all_blocks

        # Create document
        self._document = AuthorityDocument(
            index=index,
            blueprint_data=blueprint_data,
            block_origins=block_origins,
            shards=shards,
        )

        # Initialize persistence engine
        self._persistence_engine = AuthorityPersistenceEngine(self.project_root)

        return self._document

    def save(self, document: AuthorityDocument) -> AuthorityPersistenceResult:
        """Save the authority document to shards.
        
        Args:
            document: The authority document to save.
        """
        if self._persistence_engine is None:
            self._persistence_engine = AuthorityPersistenceEngine(self.project_root)

        return self._persistence_engine.save_document(document)

    def validate(self, document: AuthorityDocument) -> list[Finding]:
        """Validate the authority document for issues.
        
        Args:
            document: The authority document to validate.
        
        Returns:
            List of findings.
        """
        findings: list[Finding] = []

        # Check for duplicate block IDs
        findings.extend(self._validate_duplicate_block_ids(document))

        # Check for duplicate code declarations
        findings.extend(self._validate_duplicate_code_declarations(document))

        return findings

    def _validate_duplicate_block_ids(self, document: AuthorityDocument) -> list[Finding]:
        """Validate that there are no duplicate block IDs.
        
        Args:
            document: The authority document to validate.
        
        Returns:
            List of findings for duplicate block IDs.
        """
        findings: list[Finding] = []

        seen_block_ids: dict[str, list[Path]] = {}

        for block in document.get_blocks():
            block_id = block.get("id")
            if not block_id:
                continue

            current_shard = document.get_origin(block_id)
            if current_shard is None:
                continue

            if block_id in seen_block_ids:
                seen_block_ids[block_id].append(current_shard)
            else:
                seen_block_ids[block_id] = [current_shard]

        for block_id, locations in seen_block_ids.items():
            if len(locations) > 1:
                findings.append(Finding(
                    source="authority",
                    code="DUPLICATE_BLOCK_ID",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=f"Duplicate block ID '{block_id}' found in multiple shards",
                    path=str(locations[0]),
                    symbol=block_id,
                    evidence={
                        "shards": [str(loc) for loc in locations],
                    },
                ))

        return findings

    def _validate_duplicate_code_declarations(self, document: AuthorityDocument) -> list[Finding]:
        """Validate that there are no duplicate code declarations.
        
        Args:
            document: The authority document to validate.
        
        Returns:
            List of findings for duplicate code declarations.
        """
        findings: list[Finding] = []

        seen_code_declarations: dict[str, list[str]] = {}

        for block in document.get_blocks():
            code = block.get("code")
            if not isinstance(code, dict):
                continue

            code_path = code.get("path", "")
            symbol = code.get("symbol", "")
            kind = code.get("kind", "")

            if not (code_path and symbol and kind):
                continue

            block_id = block.get("id")
            if not block_id:
                continue

            code_key = f"{code_path}:{symbol}:{kind}"

            if code_key in seen_code_declarations:
                seen_code_declarations[code_key].append(block_id)
            else:
                seen_code_declarations[code_key] = [block_id]

        for code_key, block_ids in seen_code_declarations.items():
            if len(block_ids) > 1:
                code_path, symbol, kind = code_key.split(":", 2)
                findings.append(Finding(
                    source="authority",
                    code="DUPLICATE_CODE_DECLARATION",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=f"Duplicate code declaration '{symbol}' ({kind}) found in multiple blocks",
                    path=code_path,
                    symbol=symbol,
                    evidence={
                        "blocks": block_ids,
                        "kind": kind,
                    },
                ))

        return findings
