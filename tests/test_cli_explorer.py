"""End-to-end navigation and safety tests for the one shared terminal explorer."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from bpfw.core.authority.sqlite.store import SqliteAuthorityStore, AuthorityConflict
from bpfw.core.authority.sqlite.queries import AuthorityQueries, Query
from bpfw.core.authority.sqlite.editor import rows_with_revisions
from bpfw.integrations.shared.cli_explorer.controller import BrowserController, selection_indices
from bpfw.core.authority.sqlite.explorer_adapter import BpfwExplorerAdapter
from bpfw.integrations.shared.cli_explorer.memory_adapter import MemoryExplorerAdapter
from bpfw.integrations.shared.cli_explorer.models import ExplorerQuery
from bpfw.integrations.shared.cli_explorer.presentation import catalogue, safe, width
from bpfw.core.authority.sqlite.migration import migrate_legacy


@pytest.fixture
def store(tmp_path):
    path = tmp_path / 'project'
    database = SqliteAuthorityStore(path)
    database.initialize()
    data={'project':{'name':'cli-tests'},
          'blocks':[{'uid':f'bp_{i:04}', 'id':f'block_{i:04}', 'name':f'Block {i}',
                     'domain': 'core' if i%2==0 else 'payments',
                     'status': 'active' if i%3 else 'experimental',
                     'purpose': 'Handling some responsibility ' + str(i),
                     'intent': {'summary': 'Intention ' + str(i)},
                     'connections':([{'id':f'c_{i}', 'target':f'block_{i+1:04}',
                                      'relationship':'uses'}] if i<305 else [])}
                    for i in range(306)]}
    database.import_document(data)
    # migration manifest must be active for Engine preview / commit.
    from bpfw.core.authority.sqlite.migration import active_backend
    (path/'.bpfw'/'authority-backend.json').write_text('{}') if False else None
    return database


def test_keyset_pages_no_duplicates(store):
    repo=AuthorityQueries(store)
    query=Query(limit=19)
    ids=[];cursor=None
    while True:
        page=repo.page(query,after=cursor)
        ids.extend(r['uid'] for r in page.rows)
        if not page.has_next:break
        cursor=page.next_cursor
    assert len(ids)==306
    assert len(set(ids))==306
    assert ids[0]=='bp_0000'
    assert ids[-1]=='bp_0305'
    assert len(rows_with_revisions(store,limit=253))==253


@pytest.mark.parametrize('field', ['name','domain','kind','status','entity_revision','display_order'])
@pytest.mark.parametrize('desc', [False,True])
def test_sort_cursor_with_nulls_and_shared_values(store,field,desc):
    repo=AuthorityQueries(store)
    query=Query(limit=23,sort=field,descending=desc)
    observed=[];cursor=None
    while True:
        page=repo.page(query,after=cursor)
        observed.extend(x['uid'] for x in page.rows)
        if not page.has_next:break
        cursor=page.next_cursor
    assert len(observed)==306
    assert len(set(observed))==306


def test_cursor_rejects_stale_changes(store):
    repo=AuthorityQueries(store)
    p=repo.page(Query(limit=10))
    store.apply_patches([{'uid':'bp_0000','field':'status','op':'set','value':'legacy'}])
    with pytest.raises(AuthorityConflict, match='Authority changed'):
        repo.page(Query(limit=10),after=p.next_cursor)


def test_details_and_relations_no_full_document(store):
    repo=AuthorityQueries(store)
    block,rev=repo.get('block_0000')
    assert rev==1
    assert block['intent']['summary']=='Intention 0'
    assert len(block['connections'])==1
    assert repo.relations('bp_0001')['incoming'][0]['source_block_uid']=='bp_0000'
    assert repo.facets(Query(), 'domain') == [('core',153),('payments',153)]


def test_filter_escaped_sql_and_bad_fields(store):
    repo=AuthorityQueries(store)
    assert not repo.page(Query(search="%' OR 1=1 --")).rows
    assert len(repo.page(Query(filters=(('domain','core'),),limit=15)).rows)==15
    with pytest.raises(ValueError):Query(filters=(('raw_json',"' OR 1=1"),))
    with pytest.raises(ValueError):Query(sort='raw_json')


def test_selection_command_and_navigation_state(store):
    repo=AuthorityQueries(store)
    messages=[]
    ui=BrowserController(BpfwExplorerAdapter(store),output=messages.append,page_size=10)
    ui.refresh()
    assert ui.command('m 1,3,5-6')
    selected=set(ui.state.selected)
    assert selected=={'bp_0000','bp_0002','bp_0004','bp_0005'}
    ui.command('n'); ui.refresh()
    ui.command('m 2')
    assert 'bp_0011' in ui.state.selected
    ui.command('sort domain desc'); ui.refresh()
    ui.command('f status=active');ui.refresh()
    assert 'bp_0011' in ui.state.selected
    ui.command('2'); ui.render()
    assert ui.state.detail_uid is not None
    ui.command('detail intent')
    assert 'Intention' in '\n'.join(messages)
    ui.command('b')
    assert ui.state.detail_uid is None
    ui.command('group domain')
    assert 'core:' in '\n'.join(messages)
    ui.command('m clear')
    assert not ui.state.selected


def test_select_all_filtered_and_deterministic_limit(store):
    ui=BrowserController(BpfwExplorerAdapter(store), page_size=10)
    ui.refresh()
    ui.command('f domain=core');ui.refresh()
    ui.command('m all')
    assert len(ui.state.selected)==153
    assert ui.state.query.filters == (('domain','core'),)
    assert len(selection_indices('1,3,5-8',10))==6
    with pytest.raises(ValueError):selection_indices('10-15',10)


def test_terminal_injection_and_dynamic_width():
    rows=[{'uid':'bp_x','external_id':'foo\x1b[31mBAR\x1b[0m',
           'domain':'日本語', 'purpose':'long \n'*40,'status':'active'}]
    for cols in (32,40,58,80,120):
        result=catalogue(rows,max_width=cols,mode='auto')
        assert all(width(line)<=cols for line in result.splitlines()),(cols,result)
        assert '\x1b' not in result
    assert '\x1b' not in safe('\x1b]0;evil\x07')


def test_review_never_writes_and_confirmation_required(store,monkeypatch):
    from bpfw.core.blueprint_engine.engine import BlueprintEngine
    # Only patch the engine's backend-activity guard for a standalone SQLite fixture.
    monkeypatch.setattr('bpfw.core.authority.sqlite.migration.active_backend',lambda root:'sqlite')
    output=[];responses=iter(['not apply','APPLY'])
    ui=BrowserController(BpfwExplorerAdapter(store),page_size=10,
                         input_func=lambda prompt:next(responses),output=output.append)
    ui.refresh()
    ui.command('m 1,2,3')
    ui.command('edit status=deprecated')
    prior=store.revision()
    assert prior==1
    ui.command('review')
    assert store.revision()==prior
    ui.command('apply')
    assert store.revision()==prior
    ui.command('apply')
    assert store.revision()==prior+1
    assert store.get_block('bp_0000')['status']=='deprecated'
    assert store.get_block('bp_0002')['status']=='deprecated'
    assert store.get_block('bp_0003')['status']!='deprecated'
    assert ui.state.pending==[]


def test_conflict_and_logical_lock_are_not_ignored(store,monkeypatch):
    monkeypatch.setattr('bpfw.core.authority.sqlite.migration.active_backend',lambda root:'sqlite')
    ui=BrowserController(BpfwExplorerAdapter(store),page_size=10,input_func=lambda prompt:'APPLY')
    ui.refresh();ui.command('m 1');ui.command('edit status=deprecated')
    store.apply_patches([{'uid':'bp_0000','field':'purpose','op':'set','value':'changed'}])
    with pytest.raises(AuthorityConflict):ui.command('review')
    ui.state.pending.clear();ui.state.reviewed=False
    ui.state.selected.clear();ui.refresh();ui.command('m 1');ui.command('edit status=deprecated')
    ui.command('review');store.set_locked(True)
    with pytest.raises(AuthorityConflict):ui.command('apply')
    store.set_locked(False)


def test_export_csv_safe_formulas(store,tmp_path):
    store.apply_patches([{'uid':'bp_0000','field':'name','op':'set','value':'=HYPERLINK("x")'}])
    ui=BrowserController(BpfwExplorerAdapter(store),page_size=10)
    ui.refresh()
    out=tmp_path/'export.csv'
    ui.command(f'export csv {out}')
    with out.open() as handle: data=list(csv.DictReader(handle))
    assert len(data)==306
    assert data[0]['name'].startswith("'=HYPERLINK")


def test_diff_filters_preserve_plan_and_sequence(tmp_path):
    from types import SimpleNamespace
    from bpfw.integrations.diff.session import DiffSession
    items=[]
    for i,(risk,kind,action) in enumerate([
        ('HIGH','MISSING_DECLARED_CODE','HUMAN_DECISION'),
        ('LOW','UNDECLARED_CODE','READ_ONLY'),
        ('HIGH','UNDECLARED_CODE','HUMAN_DECISION')]):
        items.append(SimpleNamespace(identifier=str(i),risk=SimpleNamespace(value=risk),
                                     kind=SimpleNamespace(value=kind),
                                     action_level=SimpleNamespace(value=action)))
    outputs=[]
    responses=iter(['risk=HIGH','kind=UNDECLARED_CODE','clear'])
    session=DiffSession(tmp_path,input_func=lambda prompt:next(responses),print_func=outputs.append)
    session.snapshot=SimpleNamespace(items=tuple(items))
    session._configure_filters()
    assert len(session._visible_items())==2
    assert session._group_counts()=={'HUMAN_DECISION':2}
    session._configure_filters()
    assert len(session._visible_items())==1
    assert session.current_index==0
    assert session.plan.is_empty()
    session._configure_filters()
    assert len(session._visible_items())==3
    assert session.plan.is_empty()


def test_sqlite_not_scanning_source_for_browsing(store,monkeypatch):
    import bpfw.core.catalog.verify as verify
    def fail(*args,**kwargs):raise AssertionError('Browsing must not run scanner')
    monkeypatch.setattr(verify,'scan_project_from_blueprint',fail)
    repo=AuthorityQueries(store)
    page=repo.page(Query(limit=5))
    assert len(page.rows)==5
    assert repo.get(page.rows[0]['uid']) is not None
    assert repo.facets(Query(),'status')


def test_non_sqlite_editor_requires_explicit_migration(tmp_path,monkeypatch,capsys):
    from bpfw.cli import main
    import sys
    root=tmp_path/'old_project'
    (root/'.bpfw').mkdir(parents=True)
    (root/'.bpfw'/'blueprint.yaml').write_text('blocks: []\n',encoding='utf-8')
    monkeypatch.setattr(sys,'argv',['bpfw','editor','--project-root',str(root)])
    assert main()==2
    assert 'migrate --to sqlite' in capsys.readouterr().out
    assert not (root/'.bpfw'/'authority.sqlite').exists()


def test_planner_uses_shared_terminal_module_not_editor():
    from bpfw.integrations.planner import controller,renderer,modals
    from bpfw.integrations.shared import terminal_io
    assert renderer.get_terminal_width is terminal_io.get_terminal_width
    assert renderer.get_terminal_height is terminal_io.get_terminal_height
    assert controller.read_input is terminal_io.read_input
    assert modals.read_line is terminal_io.read_line


def test_explicit_inspector_returns_to_same_block_without_changing_filters(store,monkeypatch):
    output=[]
    repo=AuthorityQueries(store)
    ui=BrowserController(BpfwExplorerAdapter(store),page_size=10,output=output.append)
    ui.refresh()
    ui.command('f domain=core');ui.refresh()
    ui.command('1');ui.render()
    original_uid=ui.state.detail_uid
    original_filter=ui.state.query.filters
    calls=[]
    def fake_inspector(**kw):
        calls.append(kw['block_id'])
        store.apply_patches([{'uid':original_uid,'field':'purpose','value':'updated from Inspector'}])
        return 'saved'
    monkeypatch.setattr('bpfw.integrations.inspector.target.run_inspector_target',fake_inspector)
    ui.command('inspect')
    assert calls
    assert ui.state.detail_uid==original_uid
    assert ui.state.query.filters==original_filter
    assert ui._detail[1]==2
    ui.command('b');ui.refresh()
    assert ui.state.detail_uid is None
    assert ui.state.query.filters==original_filter
