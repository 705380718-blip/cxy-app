import json
import pytest
from test_delivery import imported


def setup(client, name='交付空间', groups=None, kind='import'):
    return client.put('/api/workflow/setup',json={'project_name':name,'groups':groups or ['交付群'],'self_names':['测试助手'],'source_kind':kind})


def test_setup_atomic_and_idempotent(client):
    initial=client.get('/api/settings').json()
    first=setup(client).json()
    second=setup(client).json()
    assert first['project']['id']==second['project']['id']
    assert first['sources'][0]['id']==second['sources'][0]['id']
    assert first['source_ready'] and first['source_kind']=='import'
    assert not first['key_configured'] and not first['ai_enabled']
    assert not client.get('/api/dashboard').json()['process']['running']
    saved=client.get('/api/settings').json()
    for field in ['keywords','target_names','require_at_me','retention_days']:assert saved[field]==initial[field]
    with client.app.state.service.database.connection() as conn:
        assert conn.execute("SELECT count(*) FROM audit_log WHERE action='workflow_setup'").fetchone()[0]==1


def test_source_conflict_rolls_back_project_and_whitelist(client):
    setup(client)
    before=client.get('/api/settings').json()
    rejected=setup(client,'冲突空间',['新群','交付群'])
    assert rejected.status_code==409
    assert [p['name'] for p in client.get('/api/projects').json()['items']]==['交付空间']
    assert client.get('/api/settings').json()==before


def test_removed_groups_stop_capture_preserve_other_and_history(client):
    one=setup(client,groups=['旧群','交付群']).json()
    source=next(s for s in one['sources'] if s['source_key']=='旧群')
    ids=imported(client,source)
    other=setup(client,'其他空间',['其他群']).json()
    changed=setup(client,groups=['交付群']).json()
    groups=client.get('/api/settings').json()['groups']
    assert '旧群' not in groups and '其他群' in groups
    assert changed['groups']==['交付群']
    with client.app.state.service.database.connection() as conn:
        assert conn.execute('SELECT project_source_id FROM messages WHERE id=?',(ids[0],)).fetchone()[0]==source['id']
    assert client.get(f"/api/workflow/status?project_id={other['project']['id']}").json()['groups']==['其他群']


def test_fallback_kind_persisted_and_scope_count(client):
    p=setup(client,kind='decoder').json()
    imported_source=setup(client,kind='import').json()
    assert imported_source['source_kind']=='import'
    imported(client,next(s for s in imported_source['sources'] if s['source_kind']=='import'))
    other=setup(client,'其他空间',['其他群']).json()
    assert other['message_count']==0 and other['recent_messages']==[]
    prior=client.get(f"/api/workflow/status?project_id={p['project']['id']}").json()
    assert prior['message_count']==1 and prior['source_kind']=='import'
    assert len(prior['recent_messages'])==1 and prior['recent_messages'][0]['chat_name']=='交付群'
    assert client.get('/api/workflow/status').json()['project']['id']==other['project']['id']


@pytest.mark.parametrize('field,value',[('groups',[]),('groups',['  ']),('self_names',[]),('self_names',['  ']),('project_name','  '),('source_kind','invalid')])
def test_setup_validates_without_partial_writes(client,field,value):
    body={'project_name':'交付空间','groups':['交付群'],'self_names':['测试助手'],'source_kind':'import'}
    body[field]=value
    assert client.put('/api/workflow/setup',json=body).status_code==422
    assert client.get('/api/projects').json()['items']==[]


def test_global_whitelist_limit_rolls_back(client):
    rules=client.get('/api/settings').json()
    rules['groups']=[f'旧群{i}' for i in range(30)]
    rules.pop('updated_at',None)
    assert client.put('/api/settings',json=rules).status_code==200
    assert setup(client).status_code==422
    assert client.get('/api/projects').json()['items']==[]


def test_disabled_latest_space_falls_back(client):
    first=setup(client).json()['project']['id']
    other=setup(client,'其他空间',['其他群']).json()['project']['id']
    with client.app.state.service.database.connection() as conn:conn.execute('UPDATE projects SET enabled=0 WHERE id=?',(other,))
    assert client.get('/api/workflow/status').json()['project']['id']==first
    assert client.get(f'/api/workflow/status?project_id={other}').status_code==404
