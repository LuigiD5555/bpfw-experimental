"""BPFW-specific adapter for the portable terminal explorer.

The *only* browser integration allowed to know SQLite schema, Inspector and
Blueprint Engine. One instance = one resolved project root / authority.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from bpfw.integrations.shared.cli_explorer.models import ExplorerQuery, ExplorerPage
from .queries import AuthorityQueries, Query, Cursor, FIELDS, SORTABLE, FACETS, _where
from .store import SqliteAuthorityStore, AuthorityConflict


class BpfwExplorerAdapter:
    title='BPFW / EDITOR'
    default_sort='display_order'
    fields=FIELDS
    sortable=SORTABLE
    groupable=FACETS
    editable=frozenset({'name','purpose','domain','status','kind','intent.summary','intent.description',
                        'properties','failure_behavior','analysis','uniqueness'})
    detail_fields=('uid','id','name','domain','status','kind','purpose')
    section_fields=('intent','artifacts','invariants','connections')
    profiles={
        'responsibilities': ('external_id','domain','purpose'),
        'status': ('external_id','status','domain'),
        'technical': ('external_id','kind','name'),
        'revisions': ('external_id','entity_revision','status'),
    }
    labels={'external_id':'ID','uid':'UID','name':'NAME','domain':'DOMAIN',
            'purpose':'PURPOSE','status':'STATUS','kind':'KIND',
            'entity_revision':'REV','display_order':'ORDER'}

    def __init__(self, store: SqliteAuthorityStore) -> None:
        self.store=store
        self.queries=AuthorityQueries(store)
        self.identity=str(store.project_root)

    @staticmethod
    def _query(query: ExplorerQuery) -> Query:
        return Query(filters=query.filters,search=query.search,sort=query.sort,
                     descending=query.descending,limit=query.limit)

    def page(self, query: ExplorerQuery, after: Cursor | None=None) -> ExplorerPage:
        try:
            page=self.queries.page(self._query(query),after=after)
        except AuthorityConflict as exc:
            # Convert SQLite-specific cursor conflicts to the portable interface.
            raise ValueError(str(exc)) from exc
        return ExplorerPage(page.rows,page.next_cursor,page.has_next)

    def get(self, identity: str) -> tuple[dict[str,Any],int] | None:
        return self.queries.get(identity)

    def resolve(self, identities: list[str]) -> list[dict[str,Any]]:
        return self.queries.resolve(identities)

    def matching(self, query: ExplorerQuery) -> list[dict[str,Any]]:
        return self.queries.matching(self._query(query))

    def facets(self, query: ExplorerQuery, field: str) -> list[tuple[Any,int]]:
        return self.queries.facets(self._query(query),field)

    def relations(self, identity: str) -> Any:
        return self.queries.relations(identity)

    def history(self, identity: str) -> Any:
        with self.store.connect() as conn:
            return [dict(x) for x in conn.execute(
                'SELECT l.reason,l.result_revision,l.created_at FROM operation_deltas d '
                'JOIN operation_log l ON l.operation_id=d.operation_id WHERE d.entity_uid=? '
                'ORDER BY l.result_revision DESC LIMIT 30',(identity,))]

    def issues(self) -> Any:
        return self.store.doctor()

    def preview(self, patches: list[dict[str,Any]]) -> Any:
        from bpfw.core.blueprint_engine.engine import BlueprintEngine
        return BlueprintEngine(self.store.project_root).preview_authority_patches(patches)

    def apply(self, patches: list[dict[str,Any]]) -> Any:
        from bpfw.core.blueprint_engine.engine import BlueprintEngine
        return BlueprintEngine(self.store.project_root).apply_authority_patches(
            patches,reason='CLI explorer confirmed batch')

    def inspect(self, identity: str, input_func: Callable[[str],str],
                output: Callable[[str],Any]) -> Any:
        hit=self.get(identity)
        if hit is None:raise AuthorityConflict('Responsibility no longer exists')
        block,_=hit
        from bpfw.integrations.inspector.target import run_inspector_target
        return run_inspector_target(project_root=self.store.project_root,
                                    block_id=str(block.get('id') or identity),
                                    header_title='Blueprint Framework Editor · Inspect',
                                    input_func=input_func,print_func=output)

    def export(self, query: ExplorerQuery, fmt: str, destination: str) -> int:
        """Bounded transactional export. No partial output or overwrite on failure."""
        if fmt not in {'csv','json'}:raise ValueError('Invalid export format')
        path=Path(destination)
        if not path.parent.is_dir():raise FileNotFoundError('Export directory does not exist')
        if path.exists():raise FileExistsError(f'Export target already exists: {path}')
        wh,params=_where(self._query(query))
        columns=('uid','external_id','name','domain','status','kind','purpose','entity_revision')
        sql=('SELECT '+','.join(columns)+' FROM blocks'+wh+' ORDER BY display_order,uid LIMIT 10001')
        fd,tempname=tempfile.mkstemp(prefix='.bpfw-export-',dir=str(path.parent))
        count=0
        try:
            with os.fdopen(fd,'w',newline='',encoding='utf-8') as file:
                with self.store.connect() as conn:
                    conn.execute('BEGIN')
                    initial_revision=self.store._revision(conn)
                    cursor=conn.execute(sql,params)
                    if fmt=='csv':
                        writer=csv.DictWriter(file,fieldnames=columns);writer.writeheader()
                    else:file.write('[\n')
                    while True:
                        batch=cursor.fetchmany(200)
                        if not batch:break
                        for row in batch:
                            count+=1
                            if count>10000:raise AuthorityConflict('Export exceeds 10000 records; narrow the filter')
                            data=dict(row)
                            if fmt=='csv':
                                for key,val in data.items():
                                    if isinstance(val,str) and val.lstrip().startswith(('=','+','-','@')):
                                        data[key]="'"+val
                                writer.writerow(data)
                            else:
                                if count>1:file.write(',\n')
                                json.dump(data,file,ensure_ascii=False)
                    if fmt=='json':file.write('\n]\n')
                file.flush();os.fsync(file.fileno())
            if self.store.revision()!=initial_revision:
                raise AuthorityConflict('Authority changed during export; retry')
            os.link(tempname,path)
        finally:
            if os.path.exists(tempname):os.unlink(tempname)
        return count
