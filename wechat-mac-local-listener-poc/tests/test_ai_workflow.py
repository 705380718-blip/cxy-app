"""Constructed fixtures and HTTP mocks, never real model quality measurements."""
import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.ai.jobs import JobService
from app.ai.schemas import AnalysisResult
from app.ai.settings import AISettingsUpdate
from app.db import Database
from app.delivery_schema import DELIVERY_SCHEMA, SCHEMA_VERSION, execute_script
from app.models import AnalysisEnqueue, AnalysisPreview, AutomationUpdate
from app.work_items import DeliveryError
from test_delivery import bind, imported


async def no_wait(_):pass


def setup(client, **settings):
    project,source=bind(client)
    ids=imported(client,source,'[2026-10-09 23:58:00] 同事甲: 我负责，明天 12:00 补充拓扑。\n[2026-10-10 00:02:00] 客户甲: 收到，我看看。')
    client.app.state.ai_store.save(AISettingsUpdate(enabled=True,api_key='test-secret-not-real',**settings))
    client.app.state.ai_client.sleep=no_wait
    return project,source,ids


def queued(client, source, **extra):
    p=client.post('/api/ai/jobs/preview',json={'project_source_id':source['id'],**extra})
    assert p.status_code==200,p.text
    r=client.post('/api/ai/jobs',json={'preview_token':p.json()['preview_token'],'consent':True})
    assert r.status_code==202,r.text
    return r.json(),p.json()


def candidate(context, target=None):
    mid=context['new_message_ids'][0]
    ref=next(m['sender_ref'] for m in context['messages'] if m['id']==mid)
    return {'schema_version':1,'items':[{'candidate_key':'c1','target_item_id':target,'type':'task','title':'补充拓扑','task_basis':{'kind':'commitment','message_id':mid,'quote':next(m['text'] for m in context['messages'] if m['id']==mid)},'owner_ref':ref,'due_text':'明天 12:00','due_at':None,'suggested_status':'resolved','latest_progress':'已上传，待复核','evidence_message_ids':[mid],'field_evidence':{'owner':[mid],'deadline':[mid],'progress':[mid]},'needs_confirmation':[]}]}


def response_for(request, target=None, change=None):
    context=json.loads(json.loads(request.content)['messages'][1]['content'])
    result=candidate(context,target)
    if change:change(result)
    return httpx.Response(200,json={'id':'req-test','model':'deepseek-flash','usage':{'total_tokens':77},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})


def run(client, handler=None):
    if handler is not None:client.app.state.ai_client.transport=httpx.MockTransport(handler)
    return asyncio.run(client.app.state.ai_worker.run_once())


def test_offline_preview_redacts_and_does_not_enqueue(client):
    _,s=bind(client)
    imported(client,s,'[2026-10-09 09:00:00] 张某: 联系张某 13800138000，test@example.org，10.0.1.2，/Users/name/private，wxid_abcdef，sk-fake123')
    p=client.post('/api/ai/jobs/preview',json={'project_source_id':s['id']}).json()
    text=json.dumps(p['context'],ensure_ascii=False)
    for secret in ('张某','13800138000','test@example.org','10.0.1.2','/Users/name','wxid_abcdef','sk-fake123','raw_content','source_key'):
        assert secret not in text
    assert 'person-1' in text and '已脱敏' in text
    assert client.get('/api/ai/jobs').json()['items']==[]
    r=client.post('/api/ai/jobs',json={'preview_token':p['preview_token'],'consent':True})
    assert r.status_code==409 and r.json()['code']=='ai_disabled'
    assert client.post('/api/ai/jobs',json={'preview_token':p['preview_token'],'consent':False}).status_code==422


@pytest.mark.parametrize('text,secret', [
    ('password=fixture-password', 'fixture-password'),
    ('API_KEY=fixture-api-value', 'fixture-api-value'),
    ('token: fixture-token-value', 'fixture-token-value'),
    ('Authorization: Bearer fixture-bearer', 'fixture-bearer'),
    ('"Authorization": "Basic fixture-basic"', 'fixture-basic'),
    ('{"client_secret": "fixture with spaces"}', 'fixture with spaces'),
    ("密码：'fixture password'", 'fixture password'),
    ('access_token=fixture-access；refresh-token=fixture-refresh', 'fixture-refresh'),
    ('postgresql://user:fixture-db-secret@db.invalid/app', 'fixture-db-secret'),
])
def test_cloud_redaction_covers_common_credentials(text, secret):
    from app.ai.context import redact
    result = redact(text, {})
    assert secret not in result
    assert '[凭据已脱敏]' in result
    assert redact('任务：请明天提交接口说明，负责人待确认。', {}) == '任务：请明天提交接口说明，负责人待确认。'


def test_automatic_job_sends_no_chat_credentials_to_model(client):
    _, source = bind(client)
    client.app.state.ai_store.save(AISettingsUpdate(enabled=True, api_key='fixture-transport-key'))
    client.app.state.ai_jobs.automation(source['id'], AutomationUpdate(enabled=True, consent=True))
    secrets = ['fixture-api-value', 'fixture-password', 'fixture-token-value', 'fixture-bearer']
    content = '请补充接口说明。API_KEY=fixture-api-value；password="fixture-password"；token: fixture-token-value；Authorization: Bearer fixture-bearer'
    imported(client, source, f'[{datetime.now(timezone.utc).isoformat()}] 构造同事: {content}')
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        context = json.loads(payload['messages'][1]['content'])
        sent = json.dumps(context, ensure_ascii=False)
        assert all(secret not in sent for secret in secrets)
        assert '请补充接口说明' in sent and '[凭据已脱敏]' in sent
        seen.append(context)
        return httpx.Response(200, json={'id':'fixture-response', 'model':'deepseek-flash', 'choices':[{'finish_reason':'stop', 'message':{'content':'{"schema_version":1,"items":[]}'}}]})

    client.app.state.ai_client.transport = httpx.MockTransport(handler)
    client.app.state.ai_jobs.enqueue_automatic()
    assert asyncio.run(client.app.state.ai_worker.run_once())
    assert len(seen) == 1
    assert client.app.state.ai_jobs.list()['items'][0]['status'] == 'succeeded'
    # The local evidence is retained intact; only the cloud context is redacted.
    assert 'fixture-password' in client.get('/api/messages').text


def test_key_missing_and_preview_config_change(client):
    _,s,_=setup(client)
    p=client.post('/api/ai/jobs/preview',json={'project_source_id':s['id']}).json()
    client.app.state.ai_store.save(AISettingsUpdate(enabled=True,clear_key=True,max_batch_messages=2))
    assert client.post('/api/ai/jobs',json={'preview_token':p['preview_token'],'consent':True}).json()['code']=='key_missing'
    client.app.state.ai_store.save(AISettingsUpdate(enabled=True,api_key='test-secret-not-real',max_batch_messages=2))
    assert client.post('/api/ai/jobs',json={'preview_token':p['preview_token'],'consent':True}).json()['code']=='preview_changed'


def test_enqueue_is_durable_atomic_and_concurrent_idempotent(client):
    _,s,ids=setup(client)
    p=client.app.state.ai_jobs.preview(AnalysisPreview(project_source_id=s['id']))
    data=AnalysisEnqueue(preview_token=p['preview_token'],consent=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.app.state.ai_jobs.enqueue(data),range(2)))
    assert results[0]['id']==results[1]['id']
    db=client.app.state.service.database;db.initialize()
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM ai_jobs').fetchone()[0]==1
        assert conn.execute('SELECT last_enqueued_message_id FROM project_sources').fetchone()[0]==max(ids)
        assert set(json.loads(conn.execute('SELECT context_message_ids FROM ai_jobs').fetchone()[0]))==set(ids)


def test_worker_records_retry_metadata_without_blocking_ingest(client):
    _,s,_=setup(client);job,_=queued(client,s);calls=[]
    def handler(request):
        calls.append(1)
        # This needs a separate write transaction while the model request is in flight.
        with client.app.state.service.database.connection() as conn:
            conn.execute("INSERT INTO audit_log(action,detail_json,created_at) VALUES ('independent_write','{}','now')")
        if len(calls)<3:return httpx.Response(429 if len(calls)==1 else 503,headers={'Retry-After':'0'})
        return response_for(request)
    assert run(client,handler)
    d=client.get(f"/api/ai/jobs/{job['id']}").json()
    assert d['status']=='succeeded' and d['attempts']==3
    assert [a['error_code'] for a in d['attempt_details']]==['rate_limit','server_error',None]
    assert d['attempt_details'][-1]['tokens']==77
    assert client.get('/api/work-items').json()['total']==0
    p=client.get('/api/item-proposals').json()['items'][0]
    assert p['fields']['work_status']=='waiting_confirmation'
    assert p['fields']['due_at']=='2026-10-10T12:00:00+08:00'
    assert p['fields']['owner']=='同事甲'
    assert not run(client)


@pytest.mark.parametrize('failure',['outside_evidence','empty','truncated'])
def test_bad_results_get_one_correction_no_suggestions(client,failure):
    _,s,_=setup(client);job,_=queued(client,s)
    def handler(request):
        if failure=='outside_evidence':return response_for(request,change=lambda x:x['items'][0].update(evidence_message_ids=[999999],field_evidence={}))
        return httpx.Response(200,json={'choices':[{'finish_reason':'length' if failure=='truncated' else 'stop','message':{'content':''}}]})
    run(client,handler)
    d=client.get(f"/api/ai/jobs/{job['id']}").json()
    assert d['status']=='failed' and d['attempts']==2
    assert client.get('/api/item-proposals').json()['items']==[]


def test_retry_budget_survives_manual_retry_and_recovery(client):
    _,s,_=setup(client);job,_=queued(client,s)
    run(client,lambda _:httpx.Response(401,json={'error':'never surfaced'}))
    assert client.post(f"/api/ai/jobs/{job['id']}/retry",json={}).status_code==200
    assert client.post(f"/api/ai/jobs/{job['id']}/retry",json={}).status_code==200
    run(client,lambda _:httpx.Response(401))
    client.post(f"/api/ai/jobs/{job['id']}/retry",json={})
    run(client,lambda _:httpx.Response(401))
    d=client.get(f"/api/ai/jobs/{job['id']}").json()
    assert d['attempts']==3 and len(d['attempt_details'])==3
    assert client.post(f"/api/ai/jobs/{job['id']}/retry",json={}).json()['code']=='attempt_limit'
    assert client.get('/api/item-proposals').json()['items']==[]


def test_lost_lease_does_not_apply_delayed_response(client):
    _,s,_=setup(client);job,_=queued(client,s)
    def handler(request):
        client.app.state.ai_jobs.action(job['id'],'cancel')
        return response_for(request)
    run(client,handler)
    assert client.get(f"/api/ai/jobs/{job['id']}").json()['status']=='cancelled'
    assert client.get('/api/item-proposals').json()['items']==[]


def test_expired_lease_recovery_and_stale_owner_guard(client):
    _,s,_=setup(client);job,_=queued(client,s);worker=client.app.state.ai_worker
    first=worker.claim()
    with worker.database.connection() as conn:conn.execute("UPDATE ai_jobs SET lease_until='2020-01-01' WHERE id=?",(job['id'],))
    second=worker.claim()
    assert second['lease_token']!=first['lease_token']
    with pytest.raises(DeliveryError,match='取消'):
        worker.finish(first,AnalysisResult(schema_version=1,items=[]))
    worker.release(second)
    run(client,response_for)
    assert client.get(f"/api/ai/jobs/{job['id']}").json()['status']=='succeeded'
    assert len(client.get('/api/item-proposals').json()['items'])==1


def test_shutdown_cancels_http_and_requeues_only_remaining_attempts(client):
    _,s,_=setup(client);job,_=queued(client,s);worker=client.app.state.ai_worker
    async def exercise():
        entered=asyncio.Event()
        async def handler(request):
            entered.set();await asyncio.Future()
        client.app.state.ai_client.transport=httpx.MockTransport(handler)
        worker.task=asyncio.create_task(worker.run_once())
        await asyncio.wait_for(entered.wait(),2)
        await worker.stop()
    asyncio.run(exercise())
    d=client.get(f"/api/ai/jobs/{job['id']}").json()
    assert d['status']=='queued' and d['attempts']==1
    assert d['attempt_details'][0]['error_code']=='interrupted'
    assert client.get('/api/item-proposals').json()['items']==[]


def test_proposals_require_human_acceptance_and_are_idempotent(client):
    _,s,ids=setup(client);queued(client,s);run(client,response_for)
    p=client.get('/api/item-proposals').json()['items'][0]
    assert set(r['id'] for r in client.get(f"/api/item-proposals/{p['id']}/evidence").json()['items']).issubset(ids)
    first=client.post(f"/api/item-proposals/{p['id']}/apply",json={}).json()
    second=client.post(f"/api/item-proposals/{p['id']}/apply",json={}).json()
    assert first==second and first['review_status']=='confirmed' and first['work_status']=='waiting_confirmation'
    assert client.get('/api/work-items').json()['total']==1
    closed=client.patch(f"/api/work-items/{first['id']}",json={'expected_version':1,'work_status':'resolved'}).json()
    assert closed['work_status']=='resolved' and closed['review_status']=='confirmed'
    assert client.post(f"/api/item-proposals/{p['id']}/dismiss",json={}).status_code==409


def test_followup_snapshot_version_blocks_stale_overwrite(client):
    _,s,ids=setup(client)
    item=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'人工标题','evidence_message_ids':ids}).json()
    queued(client,s)
    run(client,lambda request:response_for(request,target=item['id']))
    p=client.get('/api/item-proposals').json()['items'][0]
    assert p['target_version']==1
    client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'owner':'人工责任人','review_status':'confirmed'})
    r=client.post(f"/api/item-proposals/{p['id']}/apply",json={'expected_version':1})
    assert r.status_code==409 and r.json()['code']=='version_conflict'
    current=client.get('/api/work-items').json()['items'][0]
    assert current['owner']=='人工责任人' and current['title']=='人工标题'
    assert client.post(f"/api/item-proposals/{p['id']}/dismiss",json={}).status_code==200


def test_followup_acceptance_preserves_prior_evidence(client):
    _,s,ids=setup(client)
    item=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'旧标题','evidence_message_ids':[ids[-1]]}).json()
    queued(client,s);run(client,lambda request:response_for(request,target=item['id']))
    p=client.get('/api/item-proposals').json()['items'][0]
    new=client.post(f"/api/item-proposals/{p['id']}/apply",json={'expected_version':1}).json()
    assert new['id']==item['id'] and new['version']==2 and new['review_status']=='confirmed'
    evidence=client.get(f"/api/work-items/{item['id']}/evidence").json()['items']
    assert {r['id'] for r in evidence}==set(ids)


def test_merge_same_source_evidence_and_prevent_cycles(client):
    _,s,ids=setup(client)
    a=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'A','evidence_message_ids':[ids[0]]}).json()
    b=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'B','evidence_message_ids':[ids[1]]}).json()
    args={'target_item_id':b['id'],'expected_version':1,'target_version':1}
    r=client.post(f"/api/work-items/{a['id']}/merge",json=args)
    assert r.status_code==200 and r.json()['version']==2
    assert client.get('/api/work-items').json()['total']==1
    assert {e['id'] for e in client.get(f"/api/work-items/{b['id']}/evidence").json()['items']}==set(ids)
    assert client.post(f"/api/work-items/{b['id']}/merge",json={'target_item_id':a['id'],'expected_version':2,'target_version':2}).status_code==409


def test_cross_source_proposal_link_and_merge_rejected(client):
    _,s,ids=setup(client)
    # Add a second exact-whitelist source for this boundary fixture.
    with client.app.state.service.database.connection() as conn:conn.execute("UPDATE settings SET groups_json=?",(json.dumps(['POC测试群','其他群']),))
    _,other=bind(client,group='其他群',name='其他项目');other_ids=imported(client,other)
    item=client.post('/api/work-items',json={'project_source_id':other['id'],'type':'task','title':'其他任务','evidence_message_ids':other_ids}).json()
    queued(client,s);run(client,response_for);p=client.get('/api/item-proposals').json()['items'][0]
    r=client.post(f"/api/item-proposals/{p['id']}/apply",json={'target_item_id':item['id'],'expected_version':1})
    assert r.json()['code']=='target_out_of_scope'
    local=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'本地','evidence_message_ids':ids}).json()
    assert client.post(f"/api/work-items/{local['id']}/merge",json={'target_item_id':item['id'],'expected_version':1,'target_version':1}).json()['code']=='merge_scope'


def test_automation_only_future_input_and_handles_late_history(client):
    _,s,ids=setup(client)
    r=client.put(f"/api/sources/{s['id']}/automation",json={'enabled':True})
    assert r.json()['code']=='consent_required'
    assert client.put(f"/api/sources/{s['id']}/automation",json={'enabled':True,'consent':True}).status_code==200
    jobs=client.app.state.ai_jobs;jobs.enqueue_automatic()
    assert jobs.list()['items']==[]
    # A late historical message has an older source_time but a larger local id.
    new_ids=imported(client,s,'[2026-10-08 09:00:00] 同事甲: 历史材料待补充。')
    jobs.enqueue_automatic();job=jobs.list()['items'][0]
    assert json.loads(job['input_message_ids'])==[max(new_ids)]
    client.put(f"/api/sources/{s['id']}/automation",json={'enabled':False})
    imported(client,s,'[2026-10-10 12:00:00] 同事甲: 下一个事项。');jobs.enqueue_automatic()
    assert len(jobs.list()['items'])==1


def test_context_shrinks_batches_without_silently_dropping_new_messages(client):
    _,s=bind(client)
    ids=imported(client,s,'\n'.join(f'[2026-10-09 09:0{i}:00] 同事甲: '+('材料待补充。'*100) for i in range(4)))
    client.app.state.ai_store.save(AISettingsUpdate(max_input_chars=2500))
    p=client.post('/api/ai/jobs/preview',json={'project_source_id':s['id']}).json()
    assert len(p['input_message_ids'])<len(ids) and p['has_more']
    remaining=client.post('/api/ai/jobs/preview',json={'project_source_id':s['id'],'after_message_id':p['through_message_id']}).json()
    assert min(remaining['input_message_ids'])>p['through_message_id']
    assert set(p['input_message_ids']).isdisjoint(remaining['input_message_ids'])


def test_retention_invalidates_job_when_only_overlap_expires(client):
    _,s,ids=setup(client)
    db=client.app.state.service.database
    with db.connection() as conn:
        conn.execute("UPDATE messages SET source_time=? WHERE id=?", ((datetime.now(timezone.utc)-timedelta(days=30)).isoformat(),ids[0]))
        conn.execute("UPDATE messages SET source_time=? WHERE id=?", (datetime.now(timezone.utc).isoformat(),ids[1]))
    job,_=queued(client,s,after_message_id=ids[0])
    assert json.loads(job['input_message_ids'])==[ids[1]]
    assert client.app.state.service.cleanup_expired()==1
    assert client.get('/api/ai/jobs').json()['items']==[]
    with db.connection() as conn:assert conn.execute('SELECT COUNT(*) FROM ai_previews').fetchone()[0]==0


def test_queue_budget_failure_is_visible_no_fake_empty_success(client):
    _,s,_=setup(client,max_calls_per_day=1);job,_=queued(client,s)
    run(client,lambda _:httpx.Response(503))
    d=client.get(f"/api/ai/jobs/{job['id']}").json()
    assert d['status']=='failed' and d['error_code']=='daily_budget' and d['attempts']==2
    assert client.get('/api/item-proposals').json()['items']==[]


def test_v1_upgrade_backs_up_and_preserves_queue_records(tmp_path):
    path=tmp_path/'v1.db';db=Database(path);db.initialize()
    with db.connection() as conn:
        # Reproduce the v1 tables by removing v2-only columns/tables.
        conn.execute('DROP TABLE ai_previews')
        for column in ('context_json','persons_json','config_json','context_message_ids','lease_token','completed_at'):
            conn.execute(f'ALTER TABLE ai_jobs DROP COLUMN {column}')
        conn.execute('ALTER TABLE item_proposals DROP COLUMN applied_item_id')
        conn.execute('ALTER TABLE project_sources DROP COLUMN analysis_error')
        conn.execute("INSERT INTO projects(name,created_at) VALUES ('原有项目','now')")
        conn.execute("INSERT INTO project_sources(project_id,source_kind,source_key,display_name) VALUES(1,'import','group','group')")
        conn.execute("INSERT INTO ai_jobs(project_source_id,input_message_ids,input_hash,prompt_version,model,status,created_at) VALUES(1,'[1]','old','v1','model','queued','now')")
        conn.execute('PRAGMA user_version=1')
    db.initialize();db.initialize()
    with db.connection() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
        assert conn.execute('SELECT input_hash FROM ai_jobs').fetchone()[0]=='old'
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    backup=list((tmp_path/'backups').glob('*.db'));assert len(backup)==1
    with sqlite3.connect(backup[0]) as conn:assert conn.execute('PRAGMA user_version').fetchone()[0]==1


def test_preview_item_edit_invalidates_consent_snapshot(client):
    _,s,ids=setup(client)
    item=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'旧标题','evidence_message_ids':ids}).json()
    p=client.post('/api/ai/jobs/preview',json={'project_source_id':s['id']}).json()
    client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'title':'人工新标题'})
    r=client.post('/api/ai/jobs',json={'preview_token':p['preview_token'],'consent':True})
    assert r.status_code==409 and r.json()['code']=='preview_changed'
    assert client.get('/api/ai/jobs').json()['items']==[]


def test_quote_context_redacts_people_not_in_message_senders(client):
    _,s,ids=setup(client)
    with client.app.state.service.database.connection() as conn:
        conn.execute("UPDATE messages SET quote_sender='外部引用人',quote_content='外部引用人 请检查 /Users/private/a.xml',raw_content='RAW_XML_MUST_NOT_LEAVE' WHERE id=?",(ids[0],))
    p=client.post('/api/ai/jobs/preview',json={'project_source_id':s['id']}).json()
    text=json.dumps(p['context'],ensure_ascii=False)
    assert '外部引用人' not in text and '/Users/private' not in text and 'RAW_XML_MUST_NOT_LEAVE' not in text
    assert p['context']['messages'][0]['quote_sender_ref'] in p['context']['persons']


def test_closed_or_merged_target_cannot_be_overwritten(client):
    _,s,ids=setup(client)
    item=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'任务','evidence_message_ids':ids}).json()
    queued(client,s);run(client,lambda request:response_for(request,target=item['id']))
    p=client.get('/api/item-proposals').json()['items'][0]
    client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'work_status':'resolved'})
    assert client.post(f"/api/item-proposals/{p['id']}/apply",json={'expected_version':1}).status_code==409
    assert client.get('/api/work-items').json()['items'][0]['work_status']=='resolved'


def test_disabled_ai_pauses_existing_queue_and_prompt_change_fails_safely(client):
    _,s,_=setup(client);job,_=queued(client,s)
    client.app.state.ai_store.save(AISettingsUpdate(enabled=False))
    assert not run(client)
    assert client.get(f"/api/ai/jobs/{job['id']}").json()['status']=='queued'
    client.app.state.ai_store.save(AISettingsUpdate(enabled=True))
    with client.app.state.service.database.connection() as conn:conn.execute("UPDATE ai_jobs SET prompt_version='obsolete' WHERE id=?",(job['id'],))
    assert not run(client)
    assert client.get(f"/api/ai/jobs/{job['id']}").json()['error_code']=='prompt_changed'


def test_source_removal_during_request_does_not_save_proposals(client):
    _,s,_=setup(client);job,_=queued(client,s)
    def handler(request):
        with client.app.state.service.database.connection() as conn:conn.execute("UPDATE settings SET groups_json='[]'")
        return response_for(request)
    run(client,handler)
    assert client.get(f"/api/ai/jobs/{job['id']}").json()['error_code']=='group_not_allowed'
    assert client.get('/api/item-proposals').json()['items']==[]


def test_provider_metadata_never_echoes_saved_key(client):
    _,s,_=setup(client);job,_=queued(client,s)
    def handler(request):
        r=response_for(request);data=r.json();data['model']='test-secret-not-real';data['id']='prefix-test-secret-not-real'
        return httpx.Response(200,json=data)
    run(client,handler)
    d=client.get(f"/api/ai/jobs/{job['id']}").json()
    assert 'test-secret-not-real' not in json.dumps(d)
    assert d['attempt_details'][0]['returned_model']=='unknown'


def test_oversized_auto_message_sets_error_without_advancing_cursor(client):
    _,s,_=setup(client,max_input_chars=2500)
    jobs=client.app.state.ai_jobs;jobs.automation(s['id'],AutomationUpdate(enabled=True,consent=True))
    imported(client,s,'[2026-10-10 10:00:00] 同事甲: '+'超长正文'*1000)
    jobs.enqueue_automatic()
    assert jobs.list()['items']==[]
    source=client.get('/api/projects').json()['items'][0]['sources'][0]
    assert source['analysis_error']=='input_too_large' and source['last_enqueued_message_id']==2


def test_worker_lifecycle_is_started_and_stopped_by_app(settings):
    from fastapi.testclient import TestClient
    from app.main import create_app
    app=create_app(settings)
    with TestClient(app,base_url='http://127.0.0.1:8791'):
        task=app.state.ai_worker.task
        assert task is not None and not task.done()
        scheduler=app.state.ai_worker.scheduler_task
        assert scheduler is not None and not scheduler.done()
    assert task.done() and scheduler.done() and app.state.ai_worker.task is None and app.state.ai_worker.scheduler_task is None and app.state.ai_worker.stopping


def test_accepted_ambiguous_deadline_clears_previous_precise_date(client):
    _,s,ids=setup(client)
    item=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'任务','evidence_message_ids':ids}).json()
    item=client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'due_text':'明天 12:00','due_at':'2026-10-10T12:00:00+08:00'}).json()
    queued(client,s)
    run(client,lambda r:response_for(r,target=item['id'],change=lambda result:result['items'][0].update(due_text='下周再补')))
    p=client.get('/api/item-proposals').json()['items'][0]
    result=client.post(f"/api/item-proposals/{p['id']}/apply",json={'expected_version':2}).json()
    assert result['due_text']=='下周再补' and result['due_at'] is None


def test_blank_unknown_fields_do_not_erase_existing_human_values(client):
    _,s,ids=setup(client)
    item=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'任务','evidence_message_ids':ids}).json()
    client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'owner':'人工责任人','latest_progress':'人工记录进展'})
    queued(client,s)
    run(client,lambda r:response_for(r,target=item['id'],change=lambda result:result['items'][0].update(owner_ref='',latest_progress='   ')))
    p=client.get('/api/item-proposals').json()['items'][0]
    updated=client.post(f"/api/item-proposals/{p['id']}/apply",json={'expected_version':2}).json()
    assert updated['owner']=='人工责任人' and updated['latest_progress']=='人工记录进展'


def test_queue_scanner_keeps_enqueuing_while_http_is_slow(client):
    _,s,_=setup(client);queued(client,s)
    jobs=client.app.state.ai_jobs;worker=client.app.state.ai_worker
    jobs.automation(s['id'],AutomationUpdate(enabled=True,consent=True))
    async def exercise():
        entered=asyncio.Event()
        async def handler(request):
            entered.set();await asyncio.Future()
        client.app.state.ai_client.transport=httpx.MockTransport(handler)
        await worker.start()
        try:
            await asyncio.wait_for(entered.wait(),2)
            imported(client,s,'[2026-10-10 13:00:00] 同事甲: 模型等待时的新进展。')
            async def wait_enqueued():
                while len(jobs.list()['items'])<2:await asyncio.sleep(.05)
            await asyncio.wait_for(wait_enqueued(),4)
            statuses={r['status'] for r in jobs.list()['items']}
            assert statuses=={'queued','running'}
        finally:await worker.stop()
    asyncio.run(exercise())
    assert [r['status'] for r in jobs.list()['items']]==['queued','queued']
