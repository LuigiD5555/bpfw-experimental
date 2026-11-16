"""Generic explorer contracts: deliberately independent of BPFW and persistence."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

@dataclass(frozen=True)
class ExplorerQuery:
    filters: tuple[tuple[str, str], ...] = ()
    search: str = ''
    sort: str = 'display_order'
    descending: bool = False
    limit: int = 20

@dataclass(frozen=True)
class ExplorerPage:
    rows: tuple[dict[str, Any], ...]
    next_cursor: Any | None
    has_next: bool

class ExplorerAdapter(Protocol):
    """One project-scoped data/action adapter, no globals or backend assumptions.

    Row identifiers and entity revisions are opaque to the explorer. Adapter must
    supply stable uid/entity_revision keys in page and resolve/matching results.
    """
    title: str
    default_sort: str
    identity: str
    profiles: Mapping[str, tuple[str, ...]]
    labels: Mapping[str, str]
    fields: frozenset[str]
    sortable: frozenset[str]
    groupable: frozenset[str]
    editable: frozenset[str]
    detail_fields: tuple[str, ...]
    section_fields: tuple[str, ...]

    def page(self, query: ExplorerQuery, after: Any | None = None) -> ExplorerPage: ...
    def get(self, identity: str) -> tuple[dict[str, Any], int] | None: ...
    def resolve(self, identities: list[str]) -> list[dict[str, Any]]: ...
    def matching(self, query: ExplorerQuery) -> list[dict[str, Any]]: ...
    def facets(self, query: ExplorerQuery, field: str) -> list[tuple[Any, int]]: ...
    def relations(self, identity: str) -> Any: ...
    def history(self, identity: str) -> Any: ...
    def issues(self) -> Any: ...
    def preview(self, patches: list[dict[str, Any]]) -> Any: ...
    def apply(self, patches: list[dict[str, Any]]) -> Any: ...
    def inspect(self, identity: str, input_func: Callable[[str], str], output: Callable[[str], Any]) -> Any: ...
    def export(self, query: ExplorerQuery, fmt: str, destination: str) -> int: ...
