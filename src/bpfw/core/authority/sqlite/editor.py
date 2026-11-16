"""Single Editor application entry point for SQLite authority.

The same query, selection, patch validation and rendering mechanisms serve
interactive navigation and scripts. There is no second SQLite table editor.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from bpfw.core.authority.sqlite.queries import AuthorityQueries, Query
from bpfw.core.authority.sqlite.store import AuthorityConflict, SqliteAuthorityStore
from bpfw.integrations.shared.cli_explorer.controller import BrowserController, parsed_value
from bpfw.integrations.shared.cli_explorer.models import ExplorerQuery
from .explorer_adapter import BpfwExplorerAdapter


def rows_with_revisions(store: SqliteAuthorityStore, *, domain: str | None = None,
                        status: str | None = None, search: str | None = None,
                        limit: int = 100) -> list[dict[str, Any]]:
    """Projected rows, bounded to requested scope, never full Blueprint documents."""
    if not 1 <= limit <= 10000:
        raise ValueError('limit must be between 1 and 10000')
    query=Query(filters=tuple((key,value) for key,value in (('domain',domain),('status',status))
                              if value is not None),search=search or '',limit=min(100,limit))
    repo=AuthorityQueries(store)
    result=[];cursor=None
    while len(result)<limit:
        page=repo.page(replace(query,limit=min(100,limit-len(result))),after=cursor)
        result.extend(page.rows)
        if not page.has_next:break
        # The page-size is part of cursor fingerprint. Keep all full pages equal.
        if len(result)+100>limit:
            # Final partial page uses the same query fingerprint by reading a full page and slicing.
            next_page=repo.page(query,after=page.next_cursor)
            result.extend(next_page.rows[:limit-len(result)])
            break
        cursor=page.next_cursor
    return result[:limit]


def prepare_edits(rows: list[dict[str,Any]], *, selected: set[str] | None,
                  assignments: list[str], clears: list[str]) -> list[dict[str,Any]]:
    """One canonical patch builder for scripting, CSV and interactive editing."""
    targets=[r for r in rows if selected is None or r['uid'] in selected or r['external_id'] in selected]
    if selected is not None:
        missing=selected-{r['uid'] for r in targets}-{r['external_id'] for r in targets}
        if missing:raise AuthorityConflict(f'Selected blocks not in current query: {sorted(missing)}')
    ops=[]
    for item in assignments:
        if '=' not in item:raise ValueError(f'Expected field=value: {item}')
        field,raw=item.split('=',1)
        if field not in BpfwExplorerAdapter.editable:raise ValueError(f'Field is not editable: {field}')
        ops.append((field,'set',parsed_value(raw)))
    for field in clears:
        if field not in BpfwExplorerAdapter.editable:raise ValueError(f'Field is not editable: {field}')
        ops.append((field,'clear',None))
    if not ops:return []
    if not targets:raise AuthorityConflict('No blocks match selection')
    if len(targets)*len(ops)>100000:raise AuthorityConflict('At most 100000 cell operations')
    return [{'uid':row['uid'],'expected_entity_revision':row['entity_revision'],
             'field':field,'op':operation,'value':value}
            for row in targets for field,operation,value in ops]


def run_editor(store: SqliteAuthorityStore, *, domain: str | None,
               status: str | None, search: str | None, limit: int,
               selected: list[str] | None, all_matching: bool,
               assignments: list[str], clears: list[str], apply: bool,
               interactive: bool, input_func: Callable[[str],str] = input,
               view: str = 'auto') -> dict[str,Any]:
    if selected and all_matching:raise ValueError('Choose either --select or --all')
    filters=tuple((key,value) for key,value in (('domain',domain),('status',status)) if value is not None)
    if interactive:
        if assignments or clears or selected or all_matching or apply:
            raise ValueError('Use interactive navigation OR script flags, not both')
        browser=BrowserController(BpfwExplorerAdapter(store),input_func=input_func,
                                  page_size=min(100,max(1,limit)),
                                  query=ExplorerQuery(filters=filters,search=search or '',limit=min(100,max(1,limit))))
        browser.state.mode={'table':'compact'}.get(view,view)
        browser.run()
        return {'interactive':True}
    rows=rows_with_revisions(store,domain=domain,status=status,search=search,limit=limit)
    if not assignments and not clears:
        return {'revision':store.revision(),'rows':rows,'read_only':True}
    if not selected and not all_matching:
        raise ValueError('Bulk changes require --select, --all or --interactive')
    patches=prepare_edits(rows,selected=None if all_matching else set(selected or []),
                          assignments=assignments,clears=clears)
    from bpfw.core.blueprint_engine.engine import BlueprintEngine
    engine=BlueprintEngine(store.project_root)
    preview=engine.preview_authority_patches(patches)
    if not apply:return {**preview,'applied':False}
    committed=engine.apply_authority_patches(patches,reason='CLI Editor explicit --apply')
    return {**committed,'applied':True}
