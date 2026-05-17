"""Blueprint loader for bpfw/blueprint.yaml with sharded authority."""

from pathlib import Path

from bpfw.authority import (
    AuthorityRepository,
    InvalidAuthorityIndexError,
    InvalidAuthorityShardError,
    MissingShardError,
)
from bpfw.catalog.models import (
    AUTHORITY_STATE_DEFINED,
    AUTHORITY_STATE_DRAFT,
    AUTHORITY_STATE_EMPTY,
    AUTHORITY_STATE_INVALID,
    AUTHORITY_STATE_MISSING,
    BlueprintLoadResult,
)
from bpfw.catalog.paths import resolve_blueprint_path
from bpfw.catalog.schema import get_blocks, get_code, get_kind, get_purpose, get_status
from bpfw.reports.finding import (
    FINDING_SEVERITY_BLOCK,
    FINDING_SEVERITY_INFO,
    FINDING_SEVERITY_WARNING,
    Finding,
)


class BlueprintLoader:
    """Load and parse bpfw/blueprint.yaml with sharded authority."""

    def __init__(self, project_root: Path):
        """Initialize the blueprint loader.
        
        Args:
            project_root: The project root directory.
        """
        self.project_root = project_root
        self.blueprint_path = resolve_blueprint_path(project_root)

    def load(self) -> BlueprintLoadResult:
        """Load and parse the blueprint.yaml file using sharded authority.
        
        Returns:
            BlueprintLoadResult with state, data, and findings.
        """
        if not self.blueprint_path.exists():
            finding = Finding(
                source="bpfw",
                code="NO_AUTHORITY",
                severity=FINDING_SEVERITY_INFO,
                message="No BPFW blueprint file was found.",
            )
            return BlueprintLoadResult(
                state=AUTHORITY_STATE_MISSING,
                path=str(self.blueprint_path),
                data={},
                findings=[finding],
            )

        # Check if this is a sharded authority or simple blueprint.yaml
        authority_dir = self.project_root / "bpfw" / "authority"
        
        if authority_dir.exists():
            # Use AuthorityRepository for sharded authority
            try:
                repository = AuthorityRepository(self.project_root)
                document = repository.load()
                blueprint_data = document.blueprint_data
            except (
                InvalidAuthorityIndexError,
                InvalidAuthorityShardError,
                MissingShardError,
                FileNotFoundError,
            ) as error:
                finding = Finding(
                    source="authority",
                    code="INVALID_SHARD",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=f"Invalid authority: {error}",
                    path=str(self.blueprint_path),
                )
                return BlueprintLoadResult(
                    state=AUTHORITY_STATE_INVALID,
                    path=str(self.blueprint_path),
                    data={},
                    findings=[finding],
                )
        else:
            # Load simple blueprint.yaml directly
            try:
                import yaml
                with open(self.blueprint_path, "r", encoding="utf-8") as f:
                    blueprint_data = yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError) as error:
                finding = Finding(
                    source="bpfw",
                    code="INVALID_BLUEPRINT",
                    severity=FINDING_SEVERITY_BLOCK,
                    message=f"Failed to parse blueprint: {error}",
                    path=str(self.blueprint_path),
                )
                return BlueprintLoadResult(
                    state=AUTHORITY_STATE_INVALID,
                    path=str(self.blueprint_path),
                    data={},
                    findings=[finding],
                )

        blocks = get_blocks(blueprint_data)

        if not blocks:
            finding = Finding(
                source="bpfw",
                code="EMPTY_AUTHORITY",
                severity=FINDING_SEVERITY_WARNING,
                message="Blueprint exists but contains no blocks.",
            )
            return BlueprintLoadResult(
                state=AUTHORITY_STATE_EMPTY,
                path=str(self.blueprint_path),
                data=blueprint_data,
                findings=[finding],
            )

        if not isinstance(blocks, list):
            finding = Finding(
                source="bpfw",
                code="INVALID_BLUEPRINT",
                severity=FINDING_SEVERITY_BLOCK,
                message="Blocks must be a list.",
            )
            return BlueprintLoadResult(
                state=AUTHORITY_STATE_INVALID,
                path=str(self.blueprint_path),
                data=blueprint_data,
                findings=[finding],
            )

        # Check for incomplete blocks
        has_incomplete = False
        for block in blocks:
            if not is_block_complete(block):
                has_incomplete = True
                break

        if has_incomplete:
            return BlueprintLoadResult(
                state=AUTHORITY_STATE_DRAFT,
                path=str(self.blueprint_path),
                data=blueprint_data,
                findings=[],
            )

        return BlueprintLoadResult(
            state=AUTHORITY_STATE_DEFINED,
            path=str(self.blueprint_path),
            data=blueprint_data,
            findings=[],
        )


def is_block_complete(block: dict) -> bool:
    """Check if a block has all required authority fields.

    Required fields:
    - id
    - purpose
    - name
    - domain
    - status
    - code.path
    - code.symbol
    - code.kind

    Args:
        block: The block dictionary to check.
    
    Returns:
        True if block is complete, False otherwise.
    """
    for key in ("id", "name", "domain"):
        value = block.get(key)
        if value is None or value == "":
            return False

    if get_purpose(block) in (None, ""):
        return False
    if get_status(block) in (None, ""):
        return False

    code = get_code(block)
    if not isinstance(code, dict):
        return False

    for key in ("path", "symbol"):
        value = code.get(key)
        if value is None or value == "":
            return False

    kind = get_kind(code)
    if kind is None or kind == "":
        return False

    return True
