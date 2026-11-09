"""Continuous collection to results with constructed messages and HTTP mocks."""
import asyncio
import json
import sqlite3

import pytest

from app.db import Database
from app.delivery_schema import SCHEMA_VERSION
from app.ai.settings import AISettingsUpdate
from test_ai_workflow import setup, queued, run, response_for
from test_delivery import imported
from test_reports_evaluation import report


def enable(client, project, enabled=True):
    r=client.put('/api/workflow/automation',json={'project_id':project['id'],'enabled':enabled,'consent':enabled})
    assert r.status_code==200,r.text
    return r.json()


def fresh_job(client, source, text='请提交拓扑材料。'):
    ids=imported(client,source,f'[2026-10-10 12:00:00] 同事甲: {text}')
    client.app.state.ai_jobs.enqueue_automatic()
    return client.get('/api/ai/jobs').json()['items'][0],[max(ids)]


def automatic_item(client):
    project,source,ids=setup(client);enable(client,project)
    fresh_job(client,source);run(client,response_for)
    return project,source,client.get('/api/work-items').json()['items'][0]


def test_automation_requires_once_per_space_consent_without_mutation(client):
    project,source,_=setup(client)
    r=client.put('/api/workflow/automation',json={'project_id':project['id'],'enabled':True})
    assert r.status_code==422 and r.json()['code']=='consent_required'
    assert not client.get('/api/workflow/status').json()['automatic_results']
    assert client.get('/api/ai/jobs').json()['items']==[]


def test_continuous_results_future_only_and_restart_idempotent(client):
    project,source,old=setup(client);enable(client,project)
    jobs=client.app.state.ai_jobs;jobs.enqueue_automatic()
    assert jobs.list()['items']==[]
    job,ids=fresh_job(client,source)
    assert job['auto_publish']==1 and json.loads(job['input_message_ids'])==ids
    assert run(client,response_for)
    item=client.get('/api/work-items').json()['items'][0]
    assert item['auto_generated']==1 and item['review_status']=='pending' and not item['human_edited']
    assert item['work_status']=='waiting_confirmation'  # never fabricate human closure
    assert client.get('/api/item-proposals').json()['total']==0
    client.app.state.service.database.initialize();jobs.enqueue_automatic();assert not run(client)
    enable(client,project);jobs.enqueue_automatic()
    assert len(jobs.list()['items'])==1
    assert client.get('/api/work-items').json()['total']==1


def test_followup_updates_auto_item_without_any_accept_click(client):
    project,source,item=automatic_item(client)
    job,ids=fresh_job(client,source,'拓扑已上传，请复核。')
    run(client,lambda r:response_for(r,target=item['id']))
    items=client.get('/api/work-items').json()['items']
    assert len(items)==1 and items[0]['version']==2 and not items[0]['human_edited']
    evidence=client.get(f"/api/work-items/{item['id']}/evidence").json()['items']
    assert set(ids).issubset(e['id'] for e in evidence)
    assert client.get('/api/item-proposals').json()['total']==0


def test_auto_queue_waits_for_prior_results_before_capturing_context(client):
    project,source,_=setup(client);enable(client,project)
    first,_=fresh_job(client,source)
    imported(client,source,'[2026-10-10 12:01:00] 同事甲: 我负责提交新材料。')
    client.app.state.ai_jobs.enqueue_automatic()
    assert len(client.get('/api/ai/jobs').json()['items'])==1
    run(client,response_for)
    client.app.state.ai_jobs.enqueue_automatic()
    jobs=client.get('/api/ai/jobs').json()['items'];assert len(jobs)==2
    with client.app.state.service.database.connection() as conn:
        context=json.loads(conn.execute('SELECT context_json FROM ai_jobs WHERE id=?',(jobs[0]['id'],)).fetchone()[0])
    assert context['open_items'][0]['version']==1


@pytest.mark.parametrize('human_action',['edit','confirm','merge'])
def test_manual_content_is_protected_and_conflicts_remain_visible(client,human_action):
    project,source,item=automatic_item(client)
    if human_action=='merge':
        ids=client.get(f"/api/work-items/{item['id']}/evidence").json()['items']
        other=client.post('/api/work-items',json={'project_source_id':source['id'],'type':'task','title':'合并来源','evidence_message_ids':[ids[0]['id']]}).json()
        client.post(f"/api/work-items/{other['id']}/merge",json={'target_item_id':item['id'],'expected_version':1,'target_version':1})
    else:
        args={'expected_version':1,'owner':'人工指定人员'} if human_action=='edit' else {'expected_version':1,'review_status':'confirmed'}
        client.patch(f"/api/work-items/{item['id']}",json=args)
    before=client.get('/api/work-items').json()['items'][0]
    fresh_job(client,source,'请更新拓扑。');run(client,lambda r:response_for(r,target=item['id']))
    after=client.get('/api/work-items').json()['items'][0]
    assert after==before and after['human_edited']==1
    assert client.get('/api/item-proposals').json()['total']==1
    assert client.get('/api/workflow/status').json()['intervention_count']==1


def test_pause_cancels_queue_and_late_running_response(client):
    project,source,_=setup(client);enable(client,project);job,_=fresh_job(client,source)
    def handler(request):
        enable(client,project,False)
        return response_for(request)
    run(client,handler)
    assert client.get(f"/api/ai/jobs/{job['id']}").json()['status']=='cancelled'
    assert client.get('/api/work-items').json()['total']==0
    assert client.get('/api/item-proposals').json()['total']==0
    assert not client.get('/api/workflow/status').json()['automatic_results']
    imported(client,source,'[2026-10-10 13:00:00] 同事甲: 请提交新材料。')
    client.app.state.ai_jobs.enqueue_automatic();assert len(client.get('/api/ai/jobs').json()['items'])==1


def test_mode_does_not_auto_accept_prior_manual_job_or_suggestions(client):
    project,source,_=setup(client);queued(client,source);enable(client,project);run(client,response_for)
    assert client.get('/api/work-items').json()['total']==0
    assert client.get('/api/item-proposals').json()['total']==1


def test_key_can_be_configured_after_automation_without_extra_selection(client):
    project,source,_=setup(client)
    client.app.state.ai_store.save(AISettingsUpdate(enabled=False,clear_key=True))
    enable(client,project);imported(client,source,'[2026-10-10 12:00:00] 同事甲: 请提交材料。')
    client.app.state.ai_jobs.enqueue_automatic();assert client.get('/api/ai/jobs').json()['items']==[]
    client.app.state.ai_store.save(AISettingsUpdate(enabled=True,api_key='fixture-key'))
    client.app.state.ai_jobs.enqueue_automatic();run(client,response_for)
    assert client.get('/api/work-items').json()['total']==1


def test_auto_items_support_withdraw_restore_and_report_snapshot(client):
    project,source,item=automatic_item(client)
    generated=report(client,project).json()
    assert generated['snapshot']['items'][0]['auto_generated']==1
    assert '不计入已确认成果' in generated['content']
    r=client.request('DELETE',f"/api/work-items/{item['id']}",json={'expected_version':1})
    assert r.status_code==200
    assert report(client,project).json()['snapshot']['items']==[]
    restored=client.post(f"/api/work-items/{item['id']}/restore",json={'expected_version':2}).json()
    assert not restored['withdrawn_at'] and restored['human_edited']==1
    assert client.get(f"/api/followup-reports/{generated['id']}").json()['snapshot']==generated['snapshot']


def test_duplicate_same_result_and_old_overlap_do_not_create_extra_items(client):
    project,source,_=setup(client);enable(client,project);fresh_job(client,source)
    def duplicate(result):
        result['items'].append({**result['items'][0],'candidate_key':'copy'})
    run(client,lambda r:response_for(r,change=duplicate))
    assert client.get('/api/work-items').json()['total']==1
    assert client.get('/api/item-proposals').json()['total']==0


def test_partial_auto_updates_preserve_success_and_human_protected_suggestion(client):
    project,source,item=automatic_item(client)
    client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'owner':'人工人员'})
    fresh_job(client,source,'请提交新拓扑。')
    def mixed(result):
        result['items'].append({**result['items'][0],'candidate_key':'new','target_item_id':None,'title':'提交新拓扑'})
    run(client,lambda r:response_for(r,target=item['id'],change=mixed))
    assert client.get('/api/work-items').json()['total']==2
    assert client.get('/api/item-proposals').json()['total']==1
    assert client.get('/api/ai/jobs').json()['items'][0]['status']=='succeeded'


def test_disallowed_source_stays_off_and_other_projects_are_untouched(client):
    project,source,_=setup(client)
    with client.app.state.service.database.connection() as conn:conn.execute("UPDATE settings SET groups_json='[]'")
    r=client.put('/api/workflow/automation',json={'project_id':project['id'],'enabled':True,'consent':True})
    assert r.status_code==409
    assert client.get('/api/workflow/status').json()['automatic_results'] is False


def test_v4_additive_migration_preserves_data_and_leaves_old_mode_off(tmp_path):
    path=tmp_path/'v4.db';db=Database(path);db.initialize()
    with db.connection() as conn:
        for table,column in [('project_sources','auto_publish_enabled'),('ai_jobs','auto_publish'),('work_items','auto_generated'),('work_items','human_edited')]:
            conn.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
        conn.execute("INSERT INTO projects(id,name,created_at) VALUES(1,'旧项目','now')")
        conn.execute("INSERT INTO project_sources(id,project_id,source_kind,source_key,display_name,auto_analysis_enabled) VALUES(1,1,'import','旧群','旧群',1)")
        conn.execute("INSERT INTO work_items(project_source_id,type,title,review_status,created_at,updated_at) VALUES(1,'task','人工事项','confirmed','now','now')")
        conn.execute('PRAGMA user_version=4')
    db.initialize();db.initialize()
    with db.connection() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
        assert conn.execute('SELECT auto_publish_enabled FROM project_sources').fetchone()[0]==0
        item=dict(conn.execute('SELECT * FROM work_items').fetchone());assert item['review_status']=='confirmed' and not item['auto_generated']
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    backups=list((tmp_path/'backups').glob('*.db'));assert len(backups)==1
    with sqlite3.connect(backups[0]) as conn:assert conn.execute('PRAGMA user_version').fetchone()[0]==4


def test_old_overlap_action_cannot_be_reinvented_as_a_new_automatic_task(client):
    project,source,_=setup(client);enable(client,project);fresh_job(client,source,'收到，谢谢。')
    def old_basis(request):
        context=json.loads(json.loads(request.content)['messages'][1]['content'])
        old=next(m for m in context['messages'] if m['id'] not in context['new_message_ids'])
        def change(result):result['items'][0]['task_basis']={'kind':'commitment','message_id':old['id'],'quote':old['text']};result['items'][0]['evidence_message_ids'].append(old['id'])
        return response_for(request,change=change)
    run(client,old_basis)
    assert client.get('/api/work-items').json()['total']==0
    assert client.get('/api/item-proposals').json()['total']==0
