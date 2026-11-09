"""Constructed data only; validates metrics arithmetic and privacy, not model quality."""
import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from app.db import Database
from app.delivery_schema import SCHEMA_VERSION
from app.export_utils import csv_text, markdown_text
from test_delivery import bind, imported
from test_ai_workflow import setup, queued, run, response_for


def report(client,p,start='2026-10-09',end='2026-10-10'):
    return client.post('/api/followup-reports',json={'project_id':p['id'],'start_date':start,'end_date':end})


def fixture(client):
    p,s,ids=setup(client)
    job,_=queued(client,s);assert run(client,response_for)
    inputs=client.get('/api/evaluations/inputs',params={'project_id':p['id']}).json()
    pred=inputs['ai_predictions'][0]
    data={'project_id':p['id'],'dataset_label':'构造样例','scope_message_ids':ids,'labels':[{'id':'L1','type':'task','title':'补拓扑','evidence_message_ids':[ids[0]]}],'ai_reviews':[{'prediction_id':pred['id'],'label_id':'L1','field_evidence_verified':True}],'rule_reviews':[{'prediction_id':q['id'],'label_id':None} for q in inputs['rule_predictions']],'reviewer_label':'评测员A','attested':True}
    return p,s,ids,job,inputs,data


def test_report_period_coverage_idempotency_and_pending(client):
    p,s,ids,job,_,_=fixture(client)
    r=report(client,p);assert r.status_code==200,r.text
    d=r.json();assert d['coverage']['message_count']==2 and d['coverage']['analyzed_count']==2
    assert len(d['snapshot']['pending_proposals'])==1
    assert '待复核' in d['content'] and '未分析不能视作无风险' in d['content']
    assert report(client,p).json()['id']==d['id']
    proposal=client.get('/api/item-proposals').json()['items'][0]
    item=client.post(f"/api/item-proposals/{proposal['id']}/apply",json={}).json()
    assert item['work_status']=='waiting_confirmation'
    fresh=report(client,p).json();assert fresh['id']!=d['id']
    assert report(client,p,'2026-10-10','2026-10-10').json()['snapshot']['items'][0]['evidence'][0]['outside_period']
    assert client.get(f"/api/followup-reports/{d['id']}").json()==d


def test_report_snapshots_redaction_html_formula_and_version(client):
    p,s=bind(client);ids=imported(client,s,'[2026-10-10 09:00:00] 同事甲: <script>alert(1)</script> 联系 13800138000，10.1.2.3，test@example.org，password=secretvalue')
    item=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'issue','title':'=HYPERLINK("x") 同事甲','evidence_message_ids':ids}).json()
    client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'review_status':'confirmed','owner':'同事甲'})
    d=report(client,p).json();assert d['coverage']['analyzed_count']==0 and d['coverage']['unanalysed_count']==1
    md=client.get(f"/api/followup-reports/{d['id']}/export").text
    for secret in ('13800138000','10.1.2.3','test@example.org','secretvalue','同事甲','<script>'):assert secret not in md
    assert '&lt;script&gt;' in md and '已确认事项' in md
    c=client.get(f"/api/followup-reports/{d['id']}/export?format=csv")
    rows=list(csv.reader(io.StringIO(c.text.lstrip('\ufeff'))));assert rows[1][12].startswith("'=HYPERLINK")
    assert len(rows[0])==len(rows[1])==21
    assert c.headers['content-disposition']=='attachment; filename="followup-1.csv"'
    assert client.get(f"/api/followup-reports/{d['id']}/export?format=html").status_code==422
    client.patch(f"/api/work-items/{item['id']}",json={'expected_version':2,'title':'新标题'})
    assert report(client,p).json()['id']!=d['id']
    assert '新标题' not in client.get(f"/api/followup-reports/{d['id']}").json()['content']


def test_report_unresolved_carry_forward_closed_period_filter_and_merge(client):
    p,s=bind(client);ids=imported(client,s,'[2026-10-09 09:00:00] 同事甲: 待处理。')
    a=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'跨期任务','evidence_message_ids':ids}).json()
    b=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'重复任务','evidence_message_ids':ids}).json()
    assert client.post(f"/api/work-items/{b['id']}/merge",json={'target_item_id':a['id'],'expected_version':1,'target_version':1}).status_code==200
    d=report(client,p,'2026-10-10','2026-10-10').json();assert len(d['snapshot']['items'])==1
    assert d['coverage']['message_count']==0 and '跨期依据' in d['content']
    client.patch(f"/api/work-items/{a['id']}",json={'expected_version':2,'work_status':'resolved'})
    assert report(client,p,'2026-10-10','2026-10-10').json()['snapshot']['items']==[]


@pytest.mark.parametrize('start,end',[('2026-10-10','2026-10-09'),('2025-01-01','2026-10-10'),('2026-10-10','2099-01-01')])
def test_report_reject_bad_period(client,start,end):
    p,_=bind(client);assert report(client,p,start,end).status_code==422


def test_report_empty_csv_and_missing_project(client):
    p,_=bind(client);r=report(client,p).json();c=client.get(f"/api/followup-reports/{r['id']}/export?format=csv")
    rows=list(csv.reader(io.StringIO(c.text.lstrip('\ufeff'))));assert len(rows)==2 and len(rows[0])==len(rows[1])
    assert report(client,{'id':999}).status_code==404
    assert client.get('/api/followup-reports/999/export').status_code==404


def test_evaluation_arithmetic_unmeasured_and_idempotency(client):
    p,s,ids,job,inputs,data=fixture(client)
    r=client.post('/api/evaluations',json=data);assert r.status_code==200,r.text
    d=r.json();m=d['metrics'];assert m['ai']['precision']==1 and m['ai']['recall']==1 and m['ai']['field_count']==3 and m['ai']['field_evidence_rate']==1
    assert m['rules']['recall']==0 and m['rules']['precision'] is None # no rule-matching words in fixture
    assert m['timings']['ai_total_seconds'] is None and m['timings']['reduction_fraction'] is None
    assert m['quality_goal_eligible'] is False and m['latency']['goal_eligible'] is False
    assert client.post('/api/evaluations',json=data).json()['id']==d['id']
    assert client.get('/api/evaluations',params={'project_id':p['id']}).json()['items'][0]['id']==d['id']
    rows=list(csv.reader(io.StringIO(client.get(f"/api/evaluations/{d['id']}/export").text.lstrip('\ufeff'))));assert len(rows[0])==len(rows[1])==16
    assert 'test-secret-not-real' not in str(d)


def test_evaluation_partial_review_and_zero_timings(client):
    *_,data=fixture(client);data['ai_reviews']=[];data['timings']={'rule_seconds':100,'ai_wait_seconds':0,'ai_review_seconds':20,'export_seconds':0}
    d=client.post('/api/evaluations',json=data).json();m=d['metrics'];assert m['ai']['precision'] is None and m['ai']['false_positive'] is None
    assert m['timings']['ai_total_seconds']==20 and m['timings']['reduction_fraction']==.8
    data['timings']['rule_seconds']=0;assert client.post('/api/evaluations',json=data).json()['metrics']['timings']['reduction_fraction'] is None


@pytest.mark.parametrize('change',[lambda d:d['scope_message_ids'].append(d['scope_message_ids'][0]),lambda d:d['labels'].append(d['labels'][0]),lambda d:d['labels'][0].update(evidence_message_ids=[999]),lambda d:d['ai_reviews'].append(d['ai_reviews'][0]),lambda d:d['ai_reviews'][0].update(label_id='missing'),lambda d:d['labels'][0].update(type='risk'),lambda d:d['ai_reviews'][0].update(prediction_id=999)])
def test_evaluation_reject_false_matches(client,change):
    *_,data=fixture(client);change(data);r=client.post('/api/evaluations',json=data);assert r.status_code==422,r.text


def test_evaluation_other_project_scope_and_dismissed_predictions_count(client):
    p,s,ids,job,inputs,data=fixture(client)
    client.post(f"/api/item-proposals/{inputs['ai_predictions'][0]['id']}/dismiss",json={})
    data['ai_reviews'][0].update(label_id=None,field_evidence_verified=False)
    d=client.post('/api/evaluations',json=data).json();assert d['metrics']['ai']['false_positive']==1 and d['metrics']['ai']['field_evidence_rate']==0
    other=client.post('/api/projects',json={'name':'另一项目'}).json();data['project_id']=other['id']
    assert client.post('/api/evaluations',json=data).status_code==422


def test_evaluation_nonfinite_timings_and_attestation(client):
    *_,data=fixture(client);data['timings']={'ai_wait_seconds':float('inf')}
    r=client.post('/api/evaluations',content=json.dumps(data),headers={'Content-Type':'application/json'});assert r.status_code==422
    data['timings']={};data['attested']=False;assert client.post('/api/evaluations',json=data).status_code==422


def test_mock_cannot_claim_work_trial(client):
    *_,data=fixture(client)
    with client.app.state.service.database.connection() as conn:conn.execute("UPDATE ai_jobs SET model='mock-fixture'")
    data.update(mode='work_trial',data_origin='deidentified_work')
    assert client.post('/api/evaluations',json=data).status_code==422
    data.update(mode='simulated',data_origin='constructed')
    assert client.post('/api/evaluations',json=data).json()['metrics']['mock_detected']


def test_retention_invalidates_reports_evaluation_and_exports(client):
    p,s,ids,job,_,data=fixture(client);r=report(client,p).json();e=client.post('/api/evaluations',json=data).json()
    with client.app.state.service.database.connection() as conn:conn.execute('UPDATE messages SET source_time=?',((datetime.now(timezone.utc)-timedelta(days=20)).isoformat(),))
    client.app.state.service.cleanup_expired()
    assert client.get(f"/api/followup-reports/{r['id']}/export").status_code==404
    assert client.get(f"/api/evaluations/{e['id']}/export").status_code==404


def test_v2_migration_preserves_legacy_rows_and_backup(tmp_path):
    db=Database(tmp_path/'v2.db');db.initialize()
    with db.connection() as conn:
        conn.execute('DROP INDEX idx_evaluation_fingerprint')
        conn.execute('ALTER TABLE followup_reports DROP COLUMN snapshot_json')
        for c in ('project_id','scope_json','data_origin','fingerprint','snapshot_json'):conn.execute(f'ALTER TABLE evaluation_runs DROP COLUMN {c}')
        conn.execute("INSERT INTO evaluation_runs(dataset_label,mode,human_labels,matched_items,timings,sample_count,metrics,reviewer_label,created_at) VALUES('旧评测','simulated','[]','[]','{}',0,'{}','代号','now')")
        conn.execute('PRAGMA user_version=2')
    db.initialize();db.initialize()
    with db.connection() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
        assert conn.execute('SELECT dataset_label FROM evaluation_runs').fetchone()[0]=='旧评测'
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    backup=list((tmp_path/'backups').glob('*.db'));assert len(backup)==1
    with sqlite3.connect(backup[0]) as conn:assert conn.execute('PRAGMA user_version').fetchone()[0]==2


@pytest.mark.parametrize('value',['=A1',' +SUM(1)','-1','@X','\tvalue','\nvalue'])
def test_csv_formula_escape(value):
    row=list(csv.reader(io.StringIO(csv_text(['x'],[[value]]).lstrip('\ufeff'))))[1];assert row[0].startswith("'")


def test_report_duplicate_successes_union_and_failed_new_message(client):
    p,s,ids,job,_,_=fixture(client)
    with client.app.state.service.database.connection() as conn:
        fields='project_source_id,input_message_ids,input_hash,prompt_version,model,status,created_at'
        conn.execute(f"INSERT INTO ai_jobs({fields}) SELECT project_source_id,input_message_ids,'duplicate-success',prompt_version,model,'succeeded',created_at FROM ai_jobs WHERE id=?",(job['id'],))
        conn.execute(f"INSERT INTO ai_jobs({fields}) SELECT project_source_id,input_message_ids,'failed-copy',prompt_version,model,'failed',created_at FROM ai_jobs WHERE id=?",(job['id'],))
    imported(client,s,'[2026-10-10 09:30:00] 客户乙: 新消息未分析。')
    d=report(client,p).json();assert d['coverage']['analyzed_count']==2 and d['coverage']['unanalysed_count']==1
    assert d['coverage']['job_counts']['succeeded']==2 and d['coverage']['job_counts']['failed']==1
    listed=client.get('/api/followup-reports').json()['items'][0];assert listed['start_date']=='2026-10-09' and listed['end_date']=='2026-10-10'


def test_stopped_database_backup_restore_preserves_workflow(client,tmp_path):
    p,s=bind(client);ids=imported(client,s)
    item=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'恢复前事项','evidence_message_ids':ids}).json()
    db=client.app.state.service.database;backup=tmp_path/'restore.db'
    with sqlite3.connect(db.path) as original,sqlite3.connect(backup) as saved:original.backup(saved)
    client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'title':'恢复后移除的修改'})
    with sqlite3.connect(backup) as saved,sqlite3.connect(db.path) as original:saved.backup(original)
    db.initialize()
    items=client.get('/api/work-items').json()['items'];assert items[0]['title']=='恢复前事项' and items[0]['version']==1
    with db.connection() as conn:assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
