from app.delivery_schema import SCHEMA_VERSION
import sqlite3

from app.db import Database
from app.models import AnalysisPreview
from test_ai_workflow import setup, queued, run, response_for
from test_reports_evaluation import report


def adopted(client):
    project, source, _ = setup(client)
    queued(client, source); run(client, response_for)
    proposal = client.get('/api/item-proposals').json()['items'][0]
    item = client.post(f"/api/item-proposals/{proposal['id']}/apply", json={}).json()
    return project, source, proposal, item


def test_withdraw_restore_preserve_evidence_and_report_snapshots(client):
    project, source, proposal, item = adopted(client)
    path = f"/api/work-items/{item['id']}"
    old_report = report(client, project).json()
    evidence = client.get(path + '/evidence').json()
    assert client.request('DELETE', path, json={'expected_version':99}).status_code == 409
    withdrawn = client.request('DELETE', path, json={'expected_version':item['version']}).json()
    assert withdrawn['withdrawn_at'] and withdrawn['version'] == item['version'] + 1
    assert client.request('DELETE', path, json={'expected_version':item['version']}).json() == withdrawn
    assert client.get('/api/work-items').json()['total'] == 0
    assert client.get('/api/work-items?withdrawn=true').json()['items'][0]['id'] == item['id']
    assert client.get(path + '/evidence').json() == evidence
    context = client.app.state.ai_jobs.preview(AnalysisPreview(project_source_id=source['id']))['context']
    assert context['open_items'] == []
    assert report(client, project).json()['snapshot']['items'] == []
    assert client.get(f"/api/followup-reports/{old_report['id']}").json() == old_report
    assert client.patch(path,json={'expected_version':withdrawn['version'],'title':'修改'}).status_code == 409
    assert client.post(f"/api/item-proposals/{proposal['id']}/apply",json={}).json()['code'] == 'item_withdrawn'
    assert client.post(path + '/restore',json={'expected_version':item['version']}).status_code == 409
    restored = client.post(path + '/restore',json={'expected_version':withdrawn['version']}).json()
    assert not restored['withdrawn_at'] and restored['review_status'] == 'confirmed'
    assert client.get('/api/work-items').json()['total'] == 1
    assert len(report(client,project).json()['snapshot']['items']) == 1
    with client.app.state.service.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='delivery_item_withdraw'").fetchone()[0] == 1


def test_late_progress_cannot_revive_withdrawn_item(client):
    _, source, _, item = adopted(client)
    job, _ = queued(client, source)
    def handler(request):
        assert client.request('DELETE',f"/api/work-items/{item['id']}",json={'expected_version':item['version']}).status_code == 200
        return response_for(request,target=item['id'])
    run(client,handler)
    assert client.get('/api/item-proposals').json()['items'] == []
    assert client.get(f"/api/ai/jobs/{job['id']}").json()['status'] == 'succeeded'
    assert client.get('/api/work-items').json()['total'] == 0


def test_v3_migration_keeps_items_and_creates_one_private_backup(tmp_path):
    path=tmp_path/'v3.db';db=Database(path);db.initialize()
    with db.connection() as conn:
        conn.execute('ALTER TABLE work_items DROP COLUMN withdrawn_at')
        conn.execute('ALTER TABLE ai_jobs DROP COLUMN filtered_task_count')
        conn.execute("INSERT INTO projects(id,name,created_at) VALUES (1,'构造项目','now')")
        conn.execute("INSERT INTO project_sources(id,project_id,source_kind,source_key,display_name) VALUES (1,1,'import','构造群','构造群')")
        conn.execute("INSERT INTO work_items(project_source_id,type,title,review_status,created_at,updated_at) VALUES (1,'task','保留的确认事项','confirmed','now','now')")
        conn.execute('PRAGMA user_version=3')
    db.initialize();db.initialize()
    with db.connection() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert conn.execute('SELECT title,review_status,withdrawn_at FROM work_items').fetchone()[:] == ('保留的确认事项','confirmed',None)
        assert 'withdrawn_at' in {r[1] for r in conn.execute('PRAGMA table_info(work_items)')}
    backups=list((tmp_path/'backups').glob(f'*before-v{SCHEMA_VERSION}*'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 3
