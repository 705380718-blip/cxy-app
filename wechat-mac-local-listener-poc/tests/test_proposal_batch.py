from concurrent.futures import ThreadPoolExecutor

import pytest

from test_ai_workflow import setup, queued, run, response_for


def proposals(client, count=3):
    project, source, _ = setup(client)
    queued(client, source); run(client, response_for)
    first = client.get('/api/item-proposals').json()['items'][0]
    with client.app.state.service.database.connection() as conn:
        for index in range(1, count):
            conn.execute("INSERT INTO item_proposals(job_id,candidate_key,proposed_fields_json,evidence_ids) SELECT job_id,?,proposed_fields_json,evidence_ids FROM item_proposals WHERE id=?", (f'batch-{index}',first['id']))
    return project, source, client.get('/api/item-proposals').json()['items']


def batch(client, project, rows, action='apply'):
    return client.post('/api/item-proposals/batch',json={'project_id':project['id'],'action':action,'items':[{'id':p['id'],'expected_version':p.get('target_version')} for p in rows]})


def test_batch_apply_retry_is_idempotent_and_preserves_evidence(client):
    project, _, rows = proposals(client)
    result = batch(client, project, rows).json()
    assert (result['succeeded'],result['failed']) == (3,0)
    assert client.get('/api/item-proposals').json()['total'] == 0
    assert client.get('/api/work-items').json()['total'] == 3
    for item in result['results']:
        assert client.get(f"/api/work-items/{item['item_id']}/evidence").json()['items']
    assert batch(client, project, rows).json() == result
    with client.app.state.service.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='delivery_proposal_apply'").fetchone()[0] == 3


def test_batch_dismiss_missing_and_applied_return_individual_results(client):
    project, _, rows = proposals(client)
    assert client.post(f"/api/item-proposals/{rows[0]['id']}/apply",json={}).status_code == 200
    rows.append({'id':9999})
    result = batch(client, project, rows,'dismiss').json()
    assert (result['succeeded'],result['failed']) == (2,2)
    assert {r['code'] for r in result['results'] if not r['ok']} == {'proposal_applied','proposal_not_found'}
    assert client.get('/api/work-items').json()['total'] == 1
    assert batch(client,project,rows[1:3],'dismiss').json()['succeeded'] == 2
    with client.app.state.service.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='delivery_proposal_dismiss'").fetchone()[0] == 2


def test_batch_scope_cannot_mutate_another_project(client):
    project, _, rows = proposals(client)
    other=client.post('/api/projects',json={'name':'构造另一个项目'}).json()
    for mode in ('apply','dismiss'):
        result=batch(client,other,rows,mode).json()
        assert result['succeeded'] == 0 and result['failed'] == 3
        assert all(r['code']=='proposal_out_of_scope' for r in result['results'])
    assert client.get('/api/item-proposals').json()['total'] == 3
    assert client.get('/api/work-items').json()['total'] == 0


@pytest.mark.parametrize('inactive', ['conflict','withdrawn','closed','expired'])
def test_batch_progress_checks_and_partial_commit(client, inactive):
    project, source, rows = proposals(client,2)
    target=client.post(f"/api/item-proposals/{rows[0]['id']}/apply",json={}).json()
    queued(client, source);run(client,lambda request:response_for(request,target=target['id']))
    progress=next(p for p in client.get('/api/item-proposals').json()['items'] if p['target_item_id'])
    with client.app.state.service.database.connection() as conn:
        if inactive=='conflict':conn.execute('UPDATE work_items SET version=version+1 WHERE id=?',(target['id'],))
        if inactive=='withdrawn':conn.execute("UPDATE work_items SET withdrawn_at='now' WHERE id=?",(target['id'],))
        if inactive=='closed':conn.execute("UPDATE work_items SET work_status='resolved' WHERE id=?",(target['id'],))
        if inactive=='expired':conn.execute("UPDATE item_proposals SET evidence_ids='[99999]' WHERE id=?",(progress['id'],))
    result=batch(client,project,[progress,rows[1]]).json()
    assert (result['succeeded'],result['failed']) == (1,1)
    assert result['results'][0]['code'] == {'conflict':'version_conflict','withdrawn':'item_inactive','closed':'item_closed','expired':'evidence_expired'}[inactive]
    with client.app.state.service.database.connection() as conn:
        assert conn.execute('SELECT status FROM item_proposals WHERE id=?',(progress['id'],)).fetchone()[0] == 'pending'
        assert conn.execute('SELECT version FROM work_items WHERE id=?',(target['id'],)).fetchone()[0] == (2 if inactive=='conflict' else 1)


def test_two_updates_to_same_target_do_not_overwrite_first_acceptance(client):
    project, _, rows=proposals(client)
    target=client.post(f"/api/item-proposals/{rows[0]['id']}/apply",json={}).json()
    with client.app.state.service.database.connection() as conn:
        conn.execute('UPDATE item_proposals SET target_item_id=?,target_version=1 WHERE status=?',(target['id'],'pending'))
    updates=client.get('/api/item-proposals').json()['items']
    result=batch(client,project,updates).json()
    assert (result['succeeded'],result['failed']) == (1,1)
    assert result['results'][1]['code'] == 'version_conflict'


@pytest.mark.parametrize('items', [[],[{'id':1},{'id':1}],[{'id':i+1} for i in range(101)],[{'id':0}],[{'id':1,'target_item_id':5}]])
def test_invalid_batch_rejected_before_any_mutation(client, items):
    project, _, _=proposals(client)
    response=client.post('/api/item-proposals/batch',json={'project_id':project['id'],'action':'apply','items':items})
    assert response.status_code == 422
    assert client.get('/api/item-proposals').json()['total'] == 3
    assert client.get('/api/work-items').json()['total'] == 0


def test_concurrent_batches_do_not_duplicate_items(client):
    project, _, rows=proposals(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:batch(client,project,rows).json(),range(2)))
    assert all(r['succeeded']==3 for r in results)
    assert client.get('/api/work-items').json()['total'] == 3
