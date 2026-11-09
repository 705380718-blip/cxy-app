import json
import os

import httpx
import pytest

from app.ai.prompts import smoke_context
from app.ai.schemas import AnalysisResult, resolve_deadline
from app.ai.settings import AISettingsUpdate


RESULT={'schema_version':1,'items':[{'candidate_key':'c1','type':'task','title':'补充验收拓扑','owner_ref':'person-2','due_text':'明天中午前','suggested_status':'waiting_confirmation','latest_progress':'已上传，待客户确认','evidence_message_ids':[1,2,3,4],'field_evidence':{'owner':[2],'deadline':[2],'progress':[3,4]},'needs_confirmation':['deadline_precision']}]}


def response(content=None,finish='stop'):
    return httpx.Response(200,json={'model':'deepseek-flash','choices':[{'finish_reason':finish,'message':{'content':content if content is not None else json.dumps(RESULT)}}]})


def setup(client,handler):
    client.app.state.ai_client.transport=httpx.MockTransport(handler)
    async def no_wait(seconds):pass
    client.app.state.ai_client.sleep=no_wait
    r=client.put('/api/ai/settings',json={'api_key':'test-secret-not-real'})
    assert r.status_code==200,r.text


def models():return httpx.Response(200,json={'data':[{'id':'deepseek-flash'}]})


def test_key_never_read_back_or_echoed_on_validation(client,monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    assert client.get('/api/ai/settings').json()['key_configured'] is False
    r=client.post('/api/ai/test',json={})
    assert r.status_code==409 and r.json()['code']=='key_missing'
    r=client.put('/api/ai/settings',json={'api_key':'test-secret-not-real'})
    assert 'test-secret-not-real' not in r.text and r.json()['key_configured']
    assert 'test-secret-not-real' not in client.get('/api/ai/settings').text
    invalid=client.put('/api/ai/settings',json={'api_key':'test-secret-not-real','model':{'bad':'test-secret-not-real'}})
    assert invalid.status_code==422 and 'test-secret-not-real' not in invalid.text
    path=client.app.state.ai_store.path
    if os.name != 'nt':
        assert path.stat().st_mode & 0o777==0o600
        assert path.parent.stat().st_mode & 0o777==0o700
    assert client.put('/api/ai/settings',json={'clear_key':True}).json()['key_configured'] is False


def test_smoke_validates_models_json_evidence_and_sends_only_simulated_data(client):
    sent=[]
    def handler(req):
        assert req.headers['authorization']=='Bearer test-secret-not-real'
        sent.append(req)
        return models() if req.method=='GET' else response()
    setup(client,handler)
    client.post('/api/demo/messages',json={})
    r=client.post('/api/ai/test',json={})
    assert r.status_code==200,r.text
    assert r.json()['sample_kind']=='simulated' and r.json()['item_count']==1
    payload=json.loads(sent[1].content)
    assert payload['thinking']=={'type':'disabled'} and payload['response_format']=={'type':'json_object'}
    assert '客户投诉' not in str(payload) and 'test-secret-not-real' not in str(payload)
    assert len(sent)==2
    with client.app.state.service.database.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM work_items').fetchone()[0]==0
        assert conn.execute('SELECT calls FROM ai_call_budget').fetchone()[0]==2
        assert 'test-secret-not-real' not in conn.execute("SELECT detail_json FROM audit_log WHERE action='ai_connection_test'").fetchone()[0]


@pytest.mark.parametrize('status,code',[(401,'authentication'),(403,'permission'),(402,'balance')])
def test_nonretryable_auth_and_balance_errors_do_not_echo_provider(client,status,code):
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(status,json={'error':'test-secret-not-real'})
    setup(client,handler)
    r=client.post('/api/ai/test',json={})
    assert r.status_code==502 and r.json()['code']==code and len(calls)==1
    assert 'test-secret-not-real' not in r.text


@pytest.mark.parametrize('status,code',[(429,'rate_limit'),(503,'server_error')])
def test_bounded_transport_retries(client,status,code):
    calls=[]
    def handler(req):
        calls.append(req)
        return models() if req.method=='GET' else httpx.Response(status,headers={'Retry-After':'999'})
    setup(client,handler)
    r=client.post('/api/ai/test',json={})
    assert r.json()['code']==code
    assert len([req for req in calls if req.method=='POST'])==3


@pytest.mark.parametrize('failure,code',[(httpx.ReadTimeout,'timeout'),(httpx.ConnectError,'network')])
def test_timeout_and_network_failures(client,failure,code):
    calls=[]
    def handler(req):
        calls.append(req)
        if req.method=='GET':return models()
        raise failure('secret should not be shown',request=req)
    setup(client,handler)
    r=client.post('/api/ai/test',json={})
    assert r.json()['code']==code and len(calls)==4
    assert 'secret should not be shown' not in r.text


@pytest.mark.parametrize('bad,finish,code',[
    ('','stop','empty_content'),('not json','stop','result_invalid'),('{}','length','truncated'),
    (json.dumps({'schema_version':1,'items':[{'candidate_key':'x','type':'issue','title':'fake','evidence_message_ids':[999]}]}),'stop','result_invalid'),
])
def test_result_errors_get_only_one_correction(client,bad,finish,code):
    calls=[]
    def handler(req):
        calls.append(req)
        return models() if req.method=='GET' else response(bad,finish)
    setup(client,handler)
    r=client.post('/api/ai/test',json={})
    assert r.json()['code']==code,r.text
    assert len([req for req in calls if req.method=='POST'])==2
    assert client.get('/api/work-items').json()['total']==0


def test_daily_budget_covers_retries_and_does_not_reset_on_restart(client):
    calls=[]
    def handler(req):
        calls.append(req)
        return models() if req.method=='GET' else httpx.Response(503)
    setup(client,handler)
    client.put('/api/ai/settings',json={'max_calls_per_day':2})
    r=client.post('/api/ai/test',json={})
    assert r.json()['code']=='daily_budget' and len(calls)==2
    r=client.post('/api/ai/test',json={})
    assert r.json()['code']=='daily_budget' and len(calls)==2


def test_unavailable_model_and_optional_v1_path(client):
    seen=[]
    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(200,json={'data':[{'id':'another-model'}]})
    setup(client,handler)
    client.put('/api/ai/settings',json={'base_url':'https://api.deepseek.com/v1'})
    assert client.post('/api/ai/test',json={}).json()['code']=='model_unavailable'
    assert seen==['/v1/models']
    r=client.put('/api/ai/settings',json={'base_url':'http://localhost:1234','api_key':'test-secret-not-real'})
    assert r.status_code==422 and 'test-secret-not-real' not in r.text


def test_fields_require_evidence_and_no_auto_resolution():
    result=AnalysisResult.model_validate(RESULT)
    result.items[0].suggested_status='resolved'
    result.validate_scope({1,2,3,4},{'person-1','person-2'})
    assert result.items[0].suggested_status=='waiting_confirmation'
    assert 'human_resolution_required' in result.items[0].needs_confirmation
    bad=json.loads(json.dumps(RESULT));bad['items'][0]['field_evidence'].pop('owner')
    with pytest.raises(ValueError):AnalysisResult.model_validate(bad)
    result=AnalysisResult.model_validate(RESULT)
    with pytest.raises(ValueError):result.validate_scope({1,2,3,4},{'person-1'})
    result.items[0].owner_ref=None;result.items[0].target_item_id=999
    with pytest.raises(ValueError):result.validate_scope({1,2,3,4},{'person-1'})


def test_relative_date_uses_evidence_day_in_beijing():
    assert resolve_deadline('明天 12:00','2026-09-01T09:00:00+08:00')=='2026-09-02T12:00:00+08:00'
    assert resolve_deadline('明天 12:00','2026-09-01T20:00:00+00:00')=='2026-09-03T12:00:00+08:00'
    assert resolve_deadline('明天中午前','2026-09-01T09:00:00+08:00') is None
    assert resolve_deadline('下周','2026-09-01T09:00:00+08:00') is None
