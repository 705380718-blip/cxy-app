from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from app.db import Database, SCHEMA
from app.delivery_schema import execute_script, SCHEMA_VERSION
from app.models import DecoderMessage


def bind(client, group='POC测试群', name='交付测试', kind='import'):
    project = client.post('/api/projects',json={'name':name}).json()
    result = client.put(f"/api/projects/{project['id']}/sources",json={'source_kind':kind,'source_key':group,'display_name':group})
    assert result.status_code == 200, result.text
    return project,result.json()


def csv_text(rows):
    import csv,io
    buf=io.StringIO()
    writer=csv.writer(buf)
    writer.writerow(['source_message_id','timestamp','sender','content'])
    writer.writerows(rows)
    return buf.getvalue()


def preview(client, source, content, format='txt', **extra):
    return client.post('/api/imports/preview',json={'project_source_id':source['id'],'format':format,'content':content,**extra})


def imported(client,source,content=None):
    text = content or f"[{datetime.now(timezone(timedelta(hours=8))).isoformat()}] 同事甲: 请补充拓扑。"
    result=preview(client,source,text).json()
    assert result['id']
    response=client.post(f"/api/imports/{result['id']}/commit",json={})
    assert response.status_code==200,response.text
    with client.app.state.service.database.connection() as conn:
        return [r[0] for r in conn.execute('SELECT id FROM messages WHERE project_source_id=? ORDER BY id',(source['id'],))]


def test_csv_repeat_import_idempotent_and_multiline(client):
    _,s=bind(client)
    text=csv_text([['external-1','2026-10-09 09:00:00','同事甲','请补充拓扑\n包含两行。']])
    p=preview(client,s,'\ufeff'+text,'csv').json()
    first=client.post(f"/api/imports/{p['id']}/commit",json={}).json()
    second=client.post(f"/api/imports/{p['id']}/commit",json={}).json()
    again=preview(client,s,text,'csv').json()
    assert first['inserted']==1 and second['inserted']==0 and second['reused']
    assert again['id']==p['id'] and again['status']=='committed'
    assert p['rows'][0]['timestamp']=='2026-10-09T01:00:00+00:00'
    messages=client.get('/api/messages').json()
    assert messages['total']==1
    assert '包含两行' in messages['items'][0]['content']
    assert messages['items'][0]['source_kind']=='import'
    with client.app.state.service.database.connection() as conn:
        assert conn.execute('SELECT preview_json FROM import_batches').fetchone()[0]=='[]'


def test_invalid_txt_requires_explicit_partial_commit(client):
    _,s=bind(client)
    p=preview(client,s,'没有时间的文本\n[2026-10-09 09:00:00] 同事甲: 请问如何处理？\n下一行正文\n[bad] 内容').json()
    assert len(p['errors'])==2 and p['row_count']==1
    assert '下一行正文' in p['rows'][0]['content']
    assert client.post(f"/api/imports/{p['id']}/commit",json={}).status_code==409
    assert client.post(f"/api/imports/{p['id']}/commit",json={'accept_valid_rows':True}).json()['inserted']==1


def test_unstructured_paste_requires_metadata(client):
    _,s=bind(client)
    p=preview(client,s,'请补充拓扑\n明天中午前','paste').json()
    assert p['id'] is None and p['errors']
    p=preview(client,s,'请补充拓扑\n明天中午前','paste',default_sender='同事甲',default_timestamp='2026-10-09T09:00:00+08:00').json()
    assert p['row_count']==1 and p['errors']==[]
    assert p['rows'][0]['sender']=='同事甲'


def test_no_external_id_preserves_identical_messages_and_warns_overlap(client):
    _,s=bind(client)
    line='[2026-10-09 09:00:00] 同事甲: 请补充拓扑'
    p=preview(client,s,line+'\n'+line).json()
    assert client.post(f"/api/imports/{p['id']}/commit",json={}).json()['inserted']==2
    changed=preview(client,s,line+'\n[2026-10-09 09:01:00] 同事甲: 收到').json()
    assert changed['possible_duplicates']==1
    assert client.post(f"/api/imports/{changed['id']}/commit",json={}).json()['inserted']==2


def test_external_id_overlap_and_conflict_are_atomic(client):
    _,s=bind(client)
    p=preview(client,s,csv_text([['a','2026-10-09 09:00:00','同事甲','请补充拓扑']]),'csv').json()
    client.post(f"/api/imports/{p['id']}/commit",json={})
    p=preview(client,s,csv_text([['b','2026-10-09 09:01:00','同事甲','新消息'],['a','2026-10-09 09:00:00','同事甲','被改写的消息']]),'csv').json()
    r=client.post(f"/api/imports/{p['id']}/commit",json={})
    assert r.status_code==409 and r.json()['code']=='external_id_conflict'
    assert client.get('/api/messages').json()['total']==1


def test_whitelist_rechecked_at_commit(client):
    _,s=bind(client)
    p=preview(client,s,'[2026-10-09 09:00:00] 同事甲: 请补充拓扑').json()
    rules=client.get('/api/settings').json()
    rules.pop('updated_at');rules['groups']=['另一个群']
    client.put('/api/settings',json=rules)
    r=client.post(f"/api/imports/{p['id']}/commit",json={})
    assert r.status_code==422 and r.json()['code']=='group_not_allowed'
    assert client.get('/api/messages').json()['total']==0


def test_source_cannot_move_to_another_project(client):
    _,s=bind(client)
    p=client.post('/api/projects',json={'name':'第二项目'}).json()
    r=client.put(f"/api/projects/{p['id']}/sources",json={'source_kind':'import','source_key':'POC测试群','display_name':'另一个名称'})
    assert r.status_code==409
    assert s['auto_analysis_enabled']==0


def test_evidence_boundaries_and_dual_state_optimistic_lock(client):
    p,s=bind(client)
    ids=imported(client,s)
    r=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'task','title':'补充拓扑','evidence_message_ids':ids})
    assert r.status_code==201,r.text
    item=r.json()
    edited=client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'review_status':'confirmed'}).json()
    assert edited['review_status']=='confirmed' and edited['work_status']=='open' and edited['version']==2
    assert client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'work_status':'resolved'}).status_code==409
    assert client.get(f"/api/work-items/{item['id']}/evidence").json()['items'][0]['id']==ids[0]
    assert client.get(f"/api/work-items?project_id={p['id']}").json()['total']==1
    rules=client.get('/api/settings').json();rules.pop('updated_at');rules['groups'].append('第二群')
    client.put('/api/settings',json=rules)
    _,s2=bind(client,'第二群','第二项目')
    r=client.post('/api/work-items',json={'project_source_id':s2['id'],'type':'task','title':'越界','evidence_message_ids':ids})
    assert r.status_code==422 and r.json()['code']=='evidence_out_of_scope'


def test_listener_binding_only_applies_to_future_messages_and_keeps_context(client):
    service=client.app.state.service
    def message(i, kind='mac-decoder', source_time=None):
        return DecoderMessage(source_id=str(i),chat_name='POC测试群',sender='同事甲',content='收到',source_time=source_time or datetime.now(timezone.utc),source_kind=kind)
    service.ingest(message(1))
    _,s=bind(client,kind='decoder')
    service.ingest(message(2))
    service.ingest(message(3,'mac-history',datetime.now(timezone.utc)-timedelta(days=1)))
    with service.database.connection() as conn:
        rows=conn.execute('SELECT project_source_id FROM messages ORDER BY id').fetchall()
        assert [r[0] for r in rows]==[None,s['id'],s['id']]
        assert conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0]==0


def test_import_limits_and_csv_bad_rows(client):
    _,s=bind(client)
    r=preview(client,s,'中'*(2*1024*1024//3+1))
    assert r.status_code==413
    r=preview(client,s,'\n'.join(f'[2026-10-09 09:00:00] 同事甲: {i}' for i in range(2001)))
    assert r.status_code==413
    r=preview(client,s,'wrong,columns\na,b','csv')
    assert r.status_code==422
    p=preview(client,s,csv_text([['a','not-a-date','同事甲','内容'],['b','2026-10-09 09:00:00','同事甲','内容']]),'csv').json()
    assert p['row_count']==1 and p['errors'][0]['line']==2


def test_migration_backup_restore_and_idempotency(tmp_path):
    path=tmp_path/'old.db'
    with sqlite3.connect(path) as conn:
        execute_script(conn,SCHEMA)
        conn.execute("INSERT INTO settings(id,groups_json,self_names_json,keywords_json,updated_at) VALUES (1,'[]','[]','[]','2026-10-09')")
    db=Database(path);db.initialize();db.initialize()
    backups=list((tmp_path/'backups').glob('*.db'))
    assert len(backups)==1
    with db.connection() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
        assert conn.execute('SELECT COUNT(*) FROM settings').fetchone()[0]==1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM settings').fetchone()[0]==1
        restored=sqlite3.connect(tmp_path/'restored.db');conn.backup(restored);restored.close()
    Database(tmp_path/'restored.db').initialize()


def test_failed_migration_rolls_back_all_changes(tmp_path,monkeypatch):
    path=tmp_path/'old.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE marker(value TEXT)')
        conn.execute("INSERT INTO marker VALUES ('original')")
    def fail(conn):
        conn.execute('CREATE TABLE half_migrated(id INTEGER)')
        raise RuntimeError('injected failure')
    monkeypatch.setattr('app.db.migrate_delivery',fail)
    with pytest.raises(RuntimeError):Database(path).initialize()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()==[('marker',)]
        assert conn.execute('SELECT value FROM marker').fetchone()[0]=='original'
    assert len(list((tmp_path/'backups').glob('*.db')))==1


def test_retention_invalidates_derived_text_and_preview(client):
    _,s=bind(client)
    service=client.app.state.service
    old_time=datetime.now(timezone.utc)-timedelta(days=8)
    ids=imported(client,s,f'[{old_time.isoformat()}] 同事甲: OLD_SECRET_BODY')
    item=client.post('/api/work-items',json={'project_source_id':s['id'],'type':'issue','title':'OLD_SECRET_BODY','evidence_message_ids':ids}).json()
    client.patch(f"/api/work-items/{item['id']}",json={'expected_version':1,'latest_progress':'OLD_SECRET_BODY','owner':'OLD_SECRET_BODY'})
    with service.database.connection() as conn:
        conn.execute("INSERT INTO ai_jobs(project_source_id,input_message_ids,input_hash,prompt_version,model,status,created_at) VALUES (?,?,'hash','v1','mock','succeeded','2026-10-09')",(s['id'],json.dumps(ids)))
        job=conn.execute('SELECT id FROM ai_jobs').fetchone()[0]
        conn.execute("INSERT INTO item_proposals(job_id,candidate_key,proposed_fields_json,evidence_ids) VALUES (?,'c1',?,?)",(job,json.dumps({'title':'OLD_SECRET_BODY'}),json.dumps(ids)))
        conn.execute("INSERT INTO followup_reports(project_id,period_start,period_end,item_versions,content,coverage,created_at) VALUES (1,'a','b','1','OLD_SECRET_BODY','all','now')")
        conn.execute("UPDATE import_batches SET status='preview',preview_json='OLD_SECRET_BODY',created_at='2020-01-01' WHERE id=1")
    assert service.cleanup_expired()==1
    with service.database.connection() as conn:
        row=conn.execute('SELECT * FROM work_items').fetchone()
        assert row['evidence_expired']==1 and row['title']=='依据已过期' and row['latest_progress'] is None
        for table in ('item_evidence','ai_jobs','item_proposals','followup_reports'):
            assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0
        assert conn.execute('SELECT preview_json FROM import_batches').fetchone()[0]=='[]'
    assert client.patch(f"/api/work-items/{item['id']}",json={'expected_version':3,'review_status':'confirmed'}).status_code==409


def test_delivery_routes_inherit_local_origin_security(client):
    r=client.post('/api/projects',headers={'Origin':'https://bad.invalid'},json={'name':'unsafe'})
    assert r.status_code==403
    assert "default-src 'self'" in r.headers['content-security-policy']


def test_concurrent_commit_inserts_once(client):
    from concurrent.futures import ThreadPoolExecutor
    from app.imports import ImportService
    _,s=bind(client)
    p=preview(client,s,'[2026-10-09 09:00:00] 同事甲: 请补充拓扑').json()
    importer=client.app.state.imports
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda _:importer.commit(p['id'],False),range(2)))
    assert sorted(r['inserted'] for r in results)==[0,1]
    assert client.get('/api/messages').json()['total']==1


def test_legacy_reports_migrate_without_loss(tmp_path):
    path=tmp_path/'legacy.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE reports(id INTEGER PRIMARY KEY, report_date TEXT, content TEXT,question_count INTEGER,confirmed_count INTEGER,created_at TEXT,updated_at TEXT)')
        conn.execute("INSERT INTO reports VALUES(7,'2026-10-09','legacy body',2,1,'created','updated')")
    db=Database(path);db.initialize();db.initialize()
    with db.connection() as conn:
        r=conn.execute('SELECT * FROM reports').fetchone()
        assert r['id']==7 and r['report_key']=='D:2026-10-09' and r['content']=='legacy body'
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_future_schema_version_is_rejected_without_modification(tmp_path):
    path=tmp_path/'future.db'
    with sqlite3.connect(path) as conn:conn.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError,match='版本'):Database(path).initialize()
    with sqlite3.connect(path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==99
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]==0


def test_expired_preview_is_rejected_and_refresh_restores_preview(client):
    _,s=bind(client)
    text='[2026-10-09 09:00:00] 同事甲: 请补充拓扑'
    p=preview(client,s,text).json()
    with client.app.state.service.database.connection() as conn:
        conn.execute("UPDATE import_batches SET created_at='2020-01-01' WHERE id=?",(p['id'],))
    assert client.post(f"/api/imports/{p['id']}/commit",json={}).json()['code']=='preview_expired'
    refreshed=preview(client,s,text).json()
    assert refreshed['id']==p['id']
    assert client.post(f"/api/imports/{p['id']}/commit",json={}).json()['inserted']==1
