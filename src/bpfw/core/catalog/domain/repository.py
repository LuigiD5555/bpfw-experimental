"""Repository abstraction for blueprint authority IO + mapper conversion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bpfw.core.authority import AuthorityRepository
from bpfw.core.yaml_io import dump_yaml_data, load_yaml_text
from bpfw.core.catalog.access_control import ensure_blueprint_can_be_written
from bpfw.core.catalog.domain.mapper import BlueprintMapper
from bpfw.core.catalog.domain.models import BlueprintDocument
from bpfw.core.catalog.paths import resolve_blueprint_path


@dataclass(slots=True)
class RepositoryLoadResult:
    """Repository load data with domain model and raw dictionary."""

    document: BlueprintDocument
    raw_data: dict[str, Any]
    authority_document: Any | None = None


class BlueprintRepository:
    """Single entry-point for loading/saving blueprint authority."""

    def __init__(self, project_root: Path, mapper: BlueprintMapper | None = None) -> None:
        self.project_root = project_root
        self.blueprint_path = resolve_blueprint_path(project_root)
        self.mapper = mapper or BlueprintMapper()

    @staticmethod
    def _has_sharded_authority_layout(raw_blueprint_data: dict[str, Any]) -> bool:
        """Return True when raw blueprint data declares sharded authority."""

        authority_data = raw_blueprint_data.get("authority")
        if not isinstance(authority_data, dict):
            return False
        return authority_data.get("layout") == "sharded"

    def load(self) -> RepositoryLoadResult:
        if not self.blueprint_path.exists():
            return RepositoryLoadResult(document=BlueprintDocument(), raw_data={})

        raw_blueprint_data = load_yaml_text(self.blueprint_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw_blueprint_data, dict):
            raw_blueprint_data = {}

        if self._has_sharded_authority_layout(raw_blueprint_data):
            repository = AuthorityRepository(self.project_root)
            authority_document = repository.load()
            raw_blueprint_data = authority_document.blueprint_data
            document = self.mapper.from_raw(raw_blueprint_data)
            return RepositoryLoadResult(
                document=document,
                raw_data=raw_blueprint_data,
                authority_document=authority_document,
            )

        document = self.mapper.from_raw(raw_blueprint_data)
        return RepositoryLoadResult(document=document, raw_data=raw_blueprint_data)

    def save(self, document: BlueprintDocument, authority_document: Any | None = None) -> None:
        raw_blueprint_data = self.mapper.to_raw(document)

        if authority_document is not None:
            authority_document.blueprint_data.update(raw_blueprint_data)
            authority_document.replace_blocks(raw_blueprint_data.get("blocks", []))
            AuthorityRepository(self.project_root).save(authority_document)
            return

        rendered = dump_yaml_data(raw_blueprint_data, sort_keys=False, allow_unicode=True)
        ensure_blueprint_can_be_written(project_root=self.project_root)
        self.blueprint_path.parent.mkdir(parents=True, exist_ok=True)
        self.blueprint_path.write_text(rendered, encoding="utf-8")


__all__ = ["BlueprintRepository", "RepositoryLoadResult"]
