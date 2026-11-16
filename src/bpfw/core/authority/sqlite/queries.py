"""Read-only, bounded, parameterized SQLite projections for the authority browser.

No call here scans source code, writes authority, or loads complete Blueprint.
Positions are presentation-only; identities and revisions always travel together.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any, Iterator

from .store import SqliteAuthorityStore, AuthorityConflict

FIELDS = frozenset({'uid', 'external_id', 'name', 'purpose', 'domain', 'status', 'kind',
                    'entity_revision', 'display_order', 'updated_at'})
SORTABLE = frozenset({'display_order', 'external_id', 'name', 'domain', 'status', 'kind',
                      'entity_revision', 'updated_at'})
FACETS = frozenset({'domain', 'status', 'kind'})
MAX_PAGE_SIZE = 100
MAX_SELECTION = 10000


@dataclass(frozen=True)
class Query:
    filters: tuple[tuple[str, str], ...] = ()
    search: str = ''
    sort: str = 'display_order'
    descending: bool = False
    limit: int = 20

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_PAGE_SIZE:
            raise ValueError(f'Page size must be within 1..{MAX_PAGE_SIZE}')
        if self.sort not in SORTABLE:
            raise ValueError(f'Unknown sort column: {self.sort}')
        for field, _ in self.filters:
            if field not in FIELDS:
                raise ValueError(f'Unknown filter column: {field}')
        if len(self.search) > 512:
            raise ValueError('Search is limited to 512 characters')

    @property
    def fingerprint(self) -> str:
        payload = (self.filters, self.search, self.sort, self.descending, self.limit)
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:20]


@dataclass(frozen=True)
class Cursor:
    sort_value: Any
    uid: str
    fingerprint: str
    revision: int


@dataclass(frozen=True)
class Page:
    rows: tuple[dict[str, Any], ...]
    revision: int
    next_cursor: Cursor | None
    previous_cursor: Cursor | None
    has_next: bool
    has_previous: bool


def _where(query: Query) -> tuple[str, list[Any]]:
    terms: list[str] = []
    params: list[Any] = []
    for field, value in query.filters:
        if field not in FIELDS:  # defense in depth
            raise ValueError('Invalid filter column')
        terms.append(f'{field}=?')
        params.append(value)
    if query.search:
        pat = '%' + query.search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        terms.append("(uid LIKE ? ESCAPE '\\' OR external_id LIKE ? ESCAPE '\\' "
                     "OR name LIKE ? ESCAPE '\\' OR purpose LIKE ? ESCAPE '\\')")
        params.extend([pat] * 4)
    return (' WHERE ' + ' AND '.join(terms)) if terms else '', params


def _sort_expression(query: Query) -> str:
    return 'display_order' if query.sort == 'display_order' else f"COALESCE({query.sort},'')"


def _sort_value(row: dict[str, Any], query: Query) -> Any:
    value = row[query.sort]
    return value if query.sort == 'display_order' else ('' if value is None else value)


class AuthorityQueries:
    """Structured, read-only catalogue API for a *single* SQLite source of truth."""

    def __init__(self, store: SqliteAuthorityStore) -> None:
        self.store = store

    def page(self, query: Query, *, after: Cursor | None = None,
             before: Cursor | None = None) -> Page:
        if after and before:
            raise ValueError('Choose only one page cursor')
        cursor = before or after
        if cursor is not None and cursor.fingerprint != query.fingerprint:
            raise AuthorityConflict('Page cursor belongs to a different query')
        wh, params = _where(query)
        key = _sort_expression(query)
        forward_ascending = not query.descending
        backward = before is not None
        ascending = (not forward_ascending) if backward else forward_ascending
        direction = 'ASC' if ascending else 'DESC'
        if cursor:
            cmp = '>' if ascending else '<'
            wh += (' AND ' if wh else ' WHERE ') + f'(({key},uid) {cmp} (?,?))'
            params.extend((cursor.sort_value, cursor.uid))
        params.append(query.limit + 1)
        # No raw_json, children or entire project are ever loaded for a catalogue page.
        sql = ("SELECT uid,external_id,name,domain,status,kind,"
               "substr(purpose,1,161) AS purpose,entity_revision,display_order,updated_at "
               "FROM blocks" + wh + f' ORDER BY {key} {direction}, uid {direction} LIMIT ?')
        with self.store.connect() as conn:
            conn.execute('BEGIN')  # consistent revision and page snapshot
            revision = self.store._revision(conn)
            if cursor and revision != cursor.revision:
                raise AuthorityConflict('Authority changed since this page; refresh the catalogue')
            chunk = [dict(r) for r in conn.execute(sql, params)]
        more = len(chunk) > query.limit
        rows = chunk[:query.limit]
        if backward:
            rows.reverse()
        if rows:
            first = rows[0]; last = rows[-1]
            first_cursor = Cursor(_sort_value(first, query), first['uid'], query.fingerprint, revision)
            last_cursor = Cursor(_sort_value(last, query), last['uid'], query.fingerprint, revision)
        else:
            first_cursor = last_cursor = None
        return Page(tuple(rows), revision, last_cursor, first_cursor,
                    (bool(after) or more) if backward else more,
                    more if backward else bool(after))

    def count(self, query: Query) -> int:
        wh, params = _where(query)
        with self.store.connect() as conn:
            return int(conn.execute('SELECT count(*) FROM blocks'+wh, params).fetchone()[0])

    def facets(self, query: Query, field: str) -> list[tuple[str | None, int]]:
        if field not in FACETS:
            raise ValueError(f'Cannot group by {field}')
        wh, params = _where(query)
        with self.store.connect() as conn:
            return [(r[0], r[1]) for r in conn.execute(
                f'SELECT {field},count(*) FROM blocks'+wh+f' GROUP BY {field} ORDER BY count(*) DESC,{field}', params)]

    def get(self, uid_or_id: str) -> tuple[dict[str, Any], int] | None:
        with self.store.connect() as conn:
            row = conn.execute('SELECT uid,entity_revision FROM blocks WHERE uid=? OR external_id=?',
                               (uid_or_id, uid_or_id)).fetchone()
            if row is None:
                return None
            block = self.store._load_blocks(conn, conn.execute('SELECT * FROM blocks WHERE uid=?',
                                                               (row['uid'],)).fetchall())[0]
            return block, row['entity_revision']

    def relations(self, uid: str, *, limit: int = 50) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise ValueError('Relation limit must be between 1 and 200')
        with self.store.connect() as conn:
            outgoing = [dict(r) for r in conn.execute(
                'SELECT target_literal,target_block_uid,relationship,provenance FROM connections '
                'WHERE source_block_uid=? ORDER BY ordinal LIMIT ?', (uid, limit + 1))]
            incoming = [dict(r) for r in conn.execute(
                'SELECT c.source_block_uid,b.external_id,c.relationship FROM connections c '
                'JOIN blocks b ON b.uid=c.source_block_uid WHERE c.target_block_uid=? '
                'ORDER BY c.source_block_uid LIMIT ?', (uid, limit + 1))]
        return {'outgoing': outgoing[:limit], 'incoming': incoming[:limit],
                'outgoing_more': len(outgoing)>limit, 'incoming_more': len(incoming)>limit}

    def resolve(self, values: list[str]) -> list[dict[str, Any]]:
        """Resolve explicit UID/external-ID selectors without scanning catalogue limits."""
        results = []
        with self.store.connect() as conn:
            for value in values:
                row = conn.execute('SELECT uid,external_id,entity_revision FROM blocks WHERE uid=? OR external_id=?',
                                   (value,value)).fetchone()
                if row is None:
                    raise AuthorityConflict(f'Unknown responsibility UID or ID: {value}')
                results.append(dict(row))
        if len({r['uid'] for r in results}) != len(results):
            raise ValueError('Duplicate responsibility in selection')
        return results

    def matching(self, query: Query, *, max_items: int = MAX_SELECTION) -> list[dict[str, Any]]:
        """Snapshot only UID/revision for bulk selection, never full block metadata."""
        if not 1 <= max_items <= MAX_SELECTION:
            raise ValueError('Invalid selection limit')
        wh, params = _where(query)
        with self.store.connect() as conn:
            rows = [dict(row) for row in conn.execute(
                'SELECT uid,external_id,entity_revision FROM blocks'+wh+' ORDER BY display_order,uid LIMIT ?',
                [*params,max_items + 1])]
        if len(rows) > max_items:
            raise AuthorityConflict(f'Selection exceeds {max_items} blocks; narrow the filter')
        return rows
