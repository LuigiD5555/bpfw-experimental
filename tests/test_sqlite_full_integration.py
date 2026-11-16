"""Regression tests for the SQLite compatibility layers across historical APIs."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
import yaml
from bpfw.core.authority.sqlite.migration import migrate_legacy
from bpfw.core.authority.sqlite.store import SqliteAuthorityStore, AuthorityConflict
from bpfw.core.authority import AuthorityRepository
from bpfw.core.authority.patch.transaction import PatchWriteContext
from bpfw.core.blueprint_engine.engine import BlueprintEngine
from bpfw.core.blueprint_engine.models import BlueprintChangeRequest,BlueprintChangeKind,BlueprintChangeSource
from bpfw.core.catalog.verify import _validate_sharded_authority
from bpfw.core.catalog.loader import BlueprintLoader
from bpfw.core.history.ledger import read_authority_snapshot

@pytest.fixture
def configured(tmp_path):
    root = tmp_path / 'project'
    bp = root/'.bpfw/blueprint.yaml'
    shard1=root/'.bpfw/blocks/a.yaml'; shard2=root/'.bpfw/blocks/b.yaml'
    shard1.parent.mkdir(parents=True)
    index={'version':2,'project':{'name':'integration','source_roots':['src']},'authority':{'layout':'sharded'},'includes':['.bpfw/blocks/a.yaml','.bpfw/blocks/b.yaml']}
    bp.write_text(yaml.safe_dump(index))
    shard1.write_text(yaml.safe_dump({'blocks':[{'id':'a','uid':'bp_a','status':'active','domain':'core','purpose':'run','code':{'path':'src/f.py','symbol':'a','kind':'function'}}]}))
    shard2.write_text(yaml.safe_dump({'blocks':[{'id':'b','uid':'bp_b','status':'active','domain':'core','purpose':'run b','code':{'path':'src/f.py','symbol':'b','kind':'function'}}]}))
    (root/'src').mkdir();(root/'src/f.py').write_text('def a(): pass\ndef b(): pass\n')
    migrate_legacy(root,apply=True)
    return root, bp, shard1, shard2

def req(kind, **data):
    return BlueprintChangeRequest(kind=kind, source=BlueprintChangeSource.TEST, human_confirmed=True, payload=data)

def test_repository_load_save_atomic_and_provenance(configured):
    root,bp,sa,sb=configured
    original=(bp.read_bytes(),sa.read_bytes(),sb.read_bytes())
    repo=AuthorityRepository(root); doc=repo.load()
    assert doc.block_origins['b']==Path('.bpfw/blocks/b.yaml')
    doc.get_block('a')['purpose']='updated'
    result=repo.save(doc)
    assert SqliteAuthorityStore(root).get_block('a')['purpose']=='updated'
    assert (bp.read_bytes(),sa.read_bytes(),sb.read_bytes())==original
    assert not result.saved_shards
    stale=repo.load()
    now=AuthorityRepository(root).load()
    now.get_block('a')['purpose']='other'; AuthorityRepository(root).save(now)
    stale.get_block('a')['purpose']='stale'
    with pytest.raises(AuthorityConflict):
        repo.save(stale)
    assert SqliteAuthorityStore(root).get_block('a')['purpose']=='other'

def test_sqlite_plan_full_semantic_and_no_yaml(configured):
    root,bp,sa,sb=configured
    before=(bp.read_bytes(),sa.read_bytes(),sb.read_bytes())
    engine=BlueprintEngine(root)
    actions=[req(BlueprintChangeKind.UPDATE_INTENT,block_id='a',source_shard_path='.bpfw/blocks/a.yaml',intent={'summary':'NEW'}),
             req(BlueprintChangeKind.ADD_INVARIANT,block_id='a',source_shard_path='.bpfw/blocks/a.yaml',invariants=[{'id':'i1','description':'test'}]),
             req(BlueprintChangeKind.UPDATE_SYMBOL,block_id='b',source_shard_path='.bpfw/blocks/b.yaml',new_symbol='b2'),
             req(BlueprintChangeKind.MOVE_BLOCK,block_id='a',source_shard_path='.bpfw/blocks/a.yaml',target_shard_path='.bpfw/blocks/b.yaml')]
    preview=engine.preview_changes(actions)
    assert preview.allowed,preview.blocked_reason
    assert SqliteAuthorityStore(root).revision()==1
    outcome=engine.apply_changes(actions,PatchWriteContext(tool_name='inspector'))
    assert outcome.success,outcome.blocked_reason
    assert SqliteAuthorityStore(root).get_block('a')['intent']['summary']=='NEW'
    assert SqliteAuthorityStore(root).get_block('b')['code']['symbol']=='b2'
    assert AuthorityRepository(root).load().block_origins['a']==Path('.bpfw/blocks/b.yaml')
    assert (bp.read_bytes(),sa.read_bytes(),sb.read_bytes())==before
    assert SqliteAuthorityStore(root).doctor()['ok']

def test_sqlite_verify_uses_logical_provenance_not_removed_yamls(configured):
    root,bp,sa,sb=configured
    sa.unlink();sb.unlink();bp.unlink()
    result=BlueprintLoader(root).load()
    assert len(result.data['blocks'])==2
    assert read_authority_snapshot(root)==SqliteAuthorityStore(root).load_document()
    findings=_validate_sharded_authority(root,result)
    assert 'INCLUDE_FILE_MISSING' not in [f.code for f in findings]
    assert 'AUTHORITY_REPOSITORY_ERROR' not in [f.code for f in findings]


def test_sqlite_plan_fails_all_or_nothing(configured):
    root,_,_,_=configured
    engine=BlueprintEngine(root)
    requests=[req(BlueprintChangeKind.UPDATE_METADATA,block_id='a',source_shard_path='.bpfw/blocks/a.yaml',metadata_changes={'status':'deprecated'}),
              req(BlueprintChangeKind.DELETE_BLOCK,block_id='missing',source_shard_path='.bpfw/blocks/b.yaml')]
    before=SqliteAuthorityStore(root).load_document()
    assert not engine.apply_changes(requests,PatchWriteContext(tool_name='inspector')).success
    assert SqliteAuthorityStore(root).load_document()==before

def test_cli_read_commands(configured, capsys, monkeypatch):
    from bpfw.cli import main
    import sys
    root,*_=configured
    for command in ('verify','status','history'):
        monkeypatch.setattr(sys,'argv',['bpfw',command,'--project-root',str(root)])
        try:
            outcome=main()
        except Exception as err:
            pytest.fail(f'{command} unexpectedly crashed: {err!r}')
        assert isinstance(outcome,int)

def test_history_projector_idempotent(configured):
    from bpfw.core.history.ledger import HistoryLedger
    from bpfw.core.authority.sqlite.history import project_outbox
    root,*_=configured
    store=SqliteAuthorityStore(root)
    store.apply_patches([{'uid':'bp_a','field':'purpose','op':'set','value':'changed'}])
    ledger=HistoryLedger(root)
    initial=ledger.query('bp_a')
    assert any(e.get('event_type')=='INTENT_MODIFIED' for e in initial)
    assert project_outbox(root)['pending']==0
    same=ledger.query('bp_a')
    assert len(initial)==len(same)
    assert store.doctor()['ok']

def test_editor_bulk_preview_commit_and_atomic_lock(configured):
    from bpfw.core.authority.sqlite.editor import run_editor
    root,*_=configured
    store=SqliteAuthorityStore(root)
    arguments={'domain':'core','status':None,'search':None,'limit':50,'selected':None,
               'all_matching':True,'assignments':['domain=backend'],'clears':[],
               'apply':False,'interactive':False}
    assert run_editor(store,**arguments)['changed']==2
    assert all(b['domain']=='core' for b in store.load_document()['blocks'])
    assert run_editor(store,**{**arguments,'apply':True})['applied']
    assert all(b['domain']=='backend' for b in store.load_document()['blocks'])
    store.set_locked(True)
    with pytest.raises(AuthorityConflict):
        run_editor(store,**{**arguments,'apply':True,'domain':'backend','assignments':['status=deprecated']})
    assert all(b['status']=='active' for b in store.load_document()['blocks'])
    store.set_locked(False)

def test_verification_cache_revision_invalidation(configured):
    from bpfw.core.catalog.loader import BlueprintLoader
    from bpfw.core.catalog.verification_cache import _build_cache_signature
    root,*_=configured
    loaded=BlueprintLoader(root).load()
    sig1=_build_cache_signature(root, loaded, ['src'], ['.git'])
    store=SqliteAuthorityStore(root)
    store.apply_patches([{'uid':'bp_a','field':'purpose','op':'set','value':'new'}])
    sig2=_build_cache_signature(root, loaded, ['src'], ['.git'])
    assert sig1['authority_revision']==1
    assert sig2['authority_revision']==2
    assert sig1 != sig2


def test_sqlite_logical_guard_and_history_snapshot(configured):
    from bpfw.core.protection.authority import get_authority_protection_status
    root,*_=configured
    store=SqliteAuthorityStore(root)
    store.set_locked(True)
    assert get_authority_protection_status(root).status=='locked'
    with pytest.raises(AuthorityConflict):
        store.apply_patches([{'uid':'bp_a','field':'purpose','value':'new'}])
    assert store.doctor()['ok']
    store.set_locked(False)
    assert get_authority_protection_status(root).status=='unlocked'

def test_snapshot_export_restore_preview(configured,capsys):
    from bpfw.core.authority.sqlite.commands import run_sqlite_cli
    root,*_=configured
    snapshot=root/'blueprint-snapshot.json'
    assert run_sqlite_cli('authority',None,['export','--out',str(snapshot)],root,True)==0
    pristine=SqliteAuthorityStore(root).load_document()
    assert json.loads(snapshot.read_text())==pristine
    SqliteAuthorityStore(root).apply_patches([{'uid':'bp_a','field':'status','value':'deprecated'}])
    assert run_sqlite_cli('authority',None,['restore','--input',str(snapshot)],root,True)==0
    assert SqliteAuthorityStore(root).get_block('a')['status']=='deprecated'
    assert run_sqlite_cli('authority',None,['restore','--input',str(snapshot),'--apply'],root,True)==0
    assert SqliteAuthorityStore(root).load_document()==pristine
    assert len(list((root/'.bpfw/backups').glob('*.sqlite')))==1
    assert SqliteAuthorityStore(root).doctor()['ok']

def test_sqlite_diagnostics_in_verify(configured):
    from bpfw.core.authority.sqlite.diagnostics import sqlite_findings
    root,*_=configured
    SqliteAuthorityStore(root).apply_patches([{'uid':'bp_a','field':'purpose','value':'okay'}])
    assert sqlite_findings(root)==[]
    document=SqliteAuthorityStore(root).load_document()
    document['blocks'][0]['connections']=[{'target':'does_not_exist','relationship':'calls'}]
    SqliteAuthorityStore(root).replace_document(document)
    findings=sqlite_findings(root)
    assert 'SQLITE_UNRESOLVED_CONNECTION' in [f.code for f in findings]

def test_backward_compatible_guard_for_post1_database(configured):
    root,*_=configured
    store=SqliteAuthorityStore(root)
    with store.connect(write=True) as conn:
        conn.execute('DROP TABLE protection_state')
    assert store.locked() is False
    assert store.doctor()['ok']
    store.set_locked(True)
    assert store.locked()
    with pytest.raises(AuthorityConflict):
        store.apply_patches([{'uid':'bp_a','field':'status','value':'legacy'}])
    store.set_locked(False)
    assert store.apply_patches([{'uid':'bp_a','field':'status','value':'legacy'}])['changed']==1

def test_editor_cli_real_flags(configured,monkeypatch,capsys):
    from bpfw.cli import main
    import sys
    root,*_=configured
    monkeypatch.setattr(sys,'argv',['bpfw','editor','--view','table','--all','--set','domain=updated','--project-root',str(root)])
    assert main()==0
    assert SqliteAuthorityStore(root).get_block('a')['domain']=='core'
    monkeypatch.setattr(sys,'argv',['bpfw','editor','--all','--set','domain=updated','--apply','--project-root',str(root)])
    assert main()==0
    assert SqliteAuthorityStore(root).get_block('a')['domain']=='updated'
