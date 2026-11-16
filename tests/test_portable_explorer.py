"""Proof that one CLI engine works across unrelated models and project roots."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import pytest

from bpfw.core.authority.sqlite.store import SqliteAuthorityStore
from bpfw.core.authority.sqlite.explorer_adapter import BpfwExplorerAdapter
from bpfw.integrations.shared.cli_explorer import BrowserController, ExplorerRegistry
from bpfw.integrations.shared.cli_explorer.memory_adapter import MemoryExplorerAdapter


def test_unrelated_dataset_navigation_without_blueprint(tmp_path):
    data=[{'key':'job-a','owner':'alice','status':'open','amount':5},
          {'key':'job-b','owner':'bob','status':'done','amount':10},
          {'key':'job-c','owner':'alice','status':'open','amount':12}]
    adapter=MemoryExplorerAdapter(data,identity='company/orders',key='key',
                                  title='ORDER CATALOGUE',profiles={'orders':('key','owner','status')})
    messages=[]
    ui=BrowserController(adapter,output=messages.append,page_size=2)
    ui.refresh()
    assert len(ui._page.rows)==2
    assert ui.command('n')
    ui.refresh()
    assert len(ui._page.rows)==1
    ui.command('first')
    ui.command('f owner=alice')
    ui.refresh()
    assert len(ui._page.rows)==2
    assert ui.command('sort amount desc')
    ui.refresh()
    assert ui._page.rows[0]['uid']=='job-c'
    ui.command('m 1')
    assert ui.state.selected=={'job-c':1}
    ui.command('2')
    ui.render()
    ui.command('detail status')
    assert any('open' in v for v in messages)
    ui.command('back')
    ui.command('group status')
    assert any('open: 2' in v for v in messages)
    with pytest.raises(ValueError,match='not editable'):
        ui.command('edit status=done')
    export=tmp_path/'orders.json'
    ui.command('export json '+str(export))
    assert len(json.loads(export.read_text()))==2
    assert not hasattr(ui,'q') and not hasattr(ui,'store')


def test_multi_project_registry_and_isolated_sessions(tmp_path):
    registry=ExplorerRegistry()
    registry.register('blueprint',lambda root:BpfwExplorerAdapter(SqliteAuthorityStore(root)))
    registry.register('arbitrary',lambda source:MemoryExplorerAdapter(source,identity='other',key='key'))
    assert registry.available()==('blueprint','arbitrary')
    with pytest.raises(ValueError,match='Unknown adapter'):
        registry.create('missing')
    roots=[tmp_path/'repo_one',tmp_path/'repo_two']
    stores=[]
    for i,root in enumerate(roots):
        store=SqliteAuthorityStore(root)
        store.initialize()
        store.import_document({'project':{'name':f'repo_{i}'},'blocks':[
            {'uid':'same-id','id':f'block_{i}','name':f'Project {i}','domain':f'domain_{i}',
             'status':'active','purpose':f'Purpose {i}'}]})
        stores.append(store)
    first=BrowserController(registry.create('blueprint',root=roots[0]))
    second=BrowserController(registry.create('blueprint',root=roots[1]))
    first.refresh();second.refresh()
    assert first._page.rows[0]['external_id']=='block_0'
    assert second._page.rows[0]['external_id']=='block_1'
    first.command('m 1');first.command('f domain=domain_0')
    assert second.state.selected=={}
    assert second.state.query.filters==()
    first.command('1');second.command('1')
    assert first.adapter.get('same-id')[0]['purpose']=='Purpose 0'
    assert second.adapter.get('same-id')[0]['purpose']=='Purpose 1'
    arbitrary=BrowserController(registry.create('arbitrary',source=[{'key':'k1','value':'other'}]))
    arbitrary.refresh()
    assert arbitrary._page.rows[0]['uid']=='k1'
    assert not arbitrary.state.selected


def test_memory_csv_safe_and_no_overwrite(tmp_path):
    adapter=MemoryExplorerAdapter([{'key':'x','comment':'=BAD()'}],identity='csv',key='key')
    ui=BrowserController(adapter)
    dest=tmp_path/'data.csv'
    ui.command('export csv '+str(dest))
    with dest.open() as stream:
        assert next(csv.DictReader(stream))['comment']=="'=BAD()"
    with pytest.raises(FileExistsError):ui.command('export csv '+str(dest))


def test_generic_engine_does_not_import_domain_packages():
    import ast
    root=Path(__file__).resolve().parents[1]/'src/bpfw/integrations/shared/cli_explorer'
    for path in root.glob('*.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                assert not (node.module or '').startswith(('bpfw.core','bpfw.integrations.inspector')),(path,node)
            elif isinstance(node,ast.Import):
                assert all(not name.name.startswith(('bpfw.core','bpfw.integrations.inspector')) for name in node.names),(path,node)


def test_sqlite_cursor_staleness_recovers_without_leaking_selection(tmp_path):
    root=tmp_path/'repo'
    store=SqliteAuthorityStore(root)
    store.initialize()
    store.import_document({'blocks':[{'uid':f'uid_{i}', 'id':f'block_{i}',
                                      'name':str(i)} for i in range(4)]})
    ui=BrowserController(BpfwExplorerAdapter(store),page_size=2)
    ui.refresh();ui.command('m 1');ui.command('n')
    assert len(ui.state.pages)==2
    old_selected=dict(ui.state.selected)
    store.apply_patches([{'uid':'uid_0','field':'purpose','op':'set','value':'new'}])
    ui.refresh()
    assert len(ui.state.pages)==1
    assert ui.state.selected==old_selected
    assert 'Dataset changed' in ui.state.notice
