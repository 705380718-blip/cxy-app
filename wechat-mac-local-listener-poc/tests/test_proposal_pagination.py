import json

from test_ai_workflow import setup, queued, run, response_for
from test_delivery import bind


def test_proposal_pages_cover_over_100_and_isolate_filters(client):
    project, source, _ = setup(client)
    queued(client, source); run(client, response_for)
    db = client.app.state.service.database
    other, other_source = bind(client, name='其他空间', kind='decoder')
    with db.connection() as conn:
        row = conn.execute('SELECT * FROM item_proposals').fetchone()
        fields = json.loads(row['proposed_fields_json'])
        for n in range(1, 130):
            fields['type'] = 'risk' if n % 2 else 'task'
            conn.execute('INSERT INTO item_proposals(job_id,candidate_key,proposed_fields_json,evidence_ids) VALUES (?,?,?,?)', (row['job_id'], f'page-{n}', json.dumps(fields), row['evidence_ids']))
        other_job = conn.execute("INSERT INTO ai_jobs(project_source_id,input_message_ids,input_hash,prompt_version,model,status,created_at) VALUES (?,'[]','fixture','fixture','mock','succeeded','2026-10-10')", (other_source['id'],)).lastrowid
        conn.execute("INSERT INTO item_proposals(job_id,candidate_key,proposed_fields_json,evidence_ids) VALUES (?,'other',?,'[]')", (other_job, json.dumps(fields)))
    base = f"/api/item-proposals?project_id={project['id']}"
    default = client.get(base).json()
    assert default['total'] == 130 and len(default['items']) == 100
    seen = []
    for page in range(1, 27):
        data = client.get(base + f'&page={page}&page_size=5').json()
        assert data['pages'] == 26 and data['page'] == page
        assert all(r['project_id'] == project['id'] for r in data['items'])
        seen += [r['id'] for r in data['items']]
    assert len(seen) == len(set(seen)) == 130
    filtered = client.get(base + '&type=risk&page_size=5').json()
    assert filtered['total'] == 65 and all(r['fields']['type'] == 'risk' for r in filtered['items'])
    assert client.get(f"/api/item-proposals?project_id={other['id']}").json()['total'] == 1
    last = client.get(base + '&page=999&page_size=5').json()
    assert last['page'] == 26
    for row in last['items']:
        assert client.post(f"/api/item-proposals/{row['id']}/dismiss", json={}).status_code == 200
    reduced = client.get(base + '&page=26&page_size=5').json()
    assert reduced['total'] == 125 and reduced['page'] == 25
    empty = client.get(base + '&type=decision&page_size=5').json()
    assert empty['items'] == [] and empty['pages'] == empty['page'] == 1


def test_proposal_pagination_rejects_invalid_requests(client):
    for query in ['page=0', 'page_size=0', 'page_size=101', 'type=unknown', 'project_id=0']:
        assert client.get('/api/item-proposals?' + query).status_code == 422
