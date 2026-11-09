"""Versioned, additive schema for project delivery workflows."""
SCHEMA_VERSION = 5
DELIVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, template_key TEXT NOT NULL DEFAULT 'delivery',
 enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_sources (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('import','decoder')),
 source_key TEXT NOT NULL, display_name TEXT NOT NULL,
 auto_analysis_enabled INTEGER NOT NULL DEFAULT 0,
 last_enqueued_message_id INTEGER NOT NULL DEFAULT 0,
 UNIQUE(source_kind,source_key)
);
CREATE TABLE IF NOT EXISTS import_batches (
 id INTEGER PRIMARY KEY, project_source_id INTEGER NOT NULL REFERENCES project_sources(id),
 content_hash TEXT NOT NULL, row_count INTEGER NOT NULL, status TEXT NOT NULL,
 error_rows TEXT NOT NULL DEFAULT '[]', preview_json TEXT NOT NULL DEFAULT '[]',
 result_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
 UNIQUE(project_source_id,content_hash)
);
CREATE TABLE IF NOT EXISTS ai_jobs (
 id INTEGER PRIMARY KEY, project_source_id INTEGER NOT NULL REFERENCES project_sources(id),
 input_message_ids TEXT NOT NULL, input_hash TEXT NOT NULL,
 context_versions TEXT NOT NULL DEFAULT '{}', prompt_version TEXT NOT NULL, model TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
 attempts INTEGER NOT NULL DEFAULT 0, lease_until TEXT, next_retry_at TEXT, error_code TEXT,
 created_at TEXT NOT NULL, UNIQUE(project_source_id,input_hash)
);
CREATE TABLE IF NOT EXISTS ai_attempts (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES ai_jobs(id) ON DELETE CASCADE,
 attempt INTEGER NOT NULL, requested_model TEXT NOT NULL, returned_model TEXT,
 request_id TEXT, latency_ms INTEGER, tokens INTEGER, finish_reason TEXT, error_code TEXT,
 UNIQUE(job_id,attempt)
);
CREATE TABLE IF NOT EXISTS work_items (
 id INTEGER PRIMARY KEY, project_source_id INTEGER NOT NULL REFERENCES project_sources(id),
 type TEXT NOT NULL CHECK(type IN ('issue','task','decision','risk')), title TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending','confirmed','ignored')),
 work_status TEXT NOT NULL DEFAULT 'open' CHECK(work_status IN ('open','in_progress','waiting_confirmation','resolved')),
 owner TEXT, due_at TEXT, due_text TEXT, latest_progress TEXT,
 version INTEGER NOT NULL DEFAULT 1, evidence_expired INTEGER NOT NULL DEFAULT 0,
 merged_into INTEGER REFERENCES work_items(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_evidence (
 item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
 message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
 field TEXT NOT NULL, job_id INTEGER REFERENCES ai_jobs(id) ON DELETE SET NULL,
 PRIMARY KEY(item_id,message_id,field)
);
CREATE TABLE IF NOT EXISTS item_proposals (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES ai_jobs(id) ON DELETE CASCADE,
 candidate_key TEXT NOT NULL, target_item_id INTEGER REFERENCES work_items(id), target_version INTEGER,
 proposed_fields_json TEXT NOT NULL, evidence_ids TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', UNIQUE(job_id,candidate_key)
);
CREATE TABLE IF NOT EXISTS followup_reports (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 period_start TEXT NOT NULL, period_end TEXT NOT NULL, item_versions TEXT NOT NULL,
 content TEXT NOT NULL, coverage TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(project_id,period_start,period_end,item_versions)
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
 id INTEGER PRIMARY KEY, dataset_label TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('simulated','replay','work_trial')),
 human_labels TEXT NOT NULL, matched_items TEXT NOT NULL, timings TEXT NOT NULL,
 sample_count INTEGER NOT NULL, metrics TEXT NOT NULL, reviewer_label TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_call_budget (
 day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_work_source ON work_items(project_source_id,review_status,work_status);
"""


def execute_script(conn, script):
    # sqlite3.executescript commits any pending transaction; keep migrations atomic.
    for statement in script.split(';'):
        if statement.strip():
            conn.execute(statement)


def migrate_delivery(conn):
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError('数据库版本高于程序版本，请使用较新程序')
    if version == SCHEMA_VERSION:
        return
    execute_script(conn, DELIVERY_SCHEMA)
    columns = {row[1] for row in conn.execute('PRAGMA table_info(messages)')}
    for name, definition in {
        'project_source_id': 'INTEGER REFERENCES project_sources(id)',
        'import_batch_id': 'INTEGER REFERENCES import_batches(id)',
    }.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE messages ADD COLUMN {name} {definition}')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_project_source ON messages(project_source_id,id)')
    if version < 2:
        additions = {
            'ai_jobs': {'context_json': "TEXT NOT NULL DEFAULT '{}'", 'persons_json': "TEXT NOT NULL DEFAULT '{}'", 'config_json': "TEXT NOT NULL DEFAULT '{}'", 'context_message_ids': "TEXT NOT NULL DEFAULT '[]'", 'lease_token': 'TEXT', 'completed_at': 'TEXT'},
            'item_proposals': {'applied_item_id': 'INTEGER REFERENCES work_items(id)'},
            'project_sources': {'analysis_error': 'TEXT'},
        }
        for table, fields in additions.items():
            existing = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            for name, definition in fields.items():
                if name not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_ai_jobs_status ON ai_jobs(status,id)')
        conn.execute('CREATE TABLE IF NOT EXISTS ai_previews(token TEXT PRIMARY KEY, project_source_id INTEGER NOT NULL REFERENCES project_sources(id), input_message_ids TEXT NOT NULL, input_hash TEXT NOT NULL, created_at TEXT NOT NULL)')
    if version < 3:
        additions = {
            'followup_reports': {'snapshot_json': "TEXT NOT NULL DEFAULT '{}'"},
            'evaluation_runs': {'project_id': 'INTEGER REFERENCES projects(id)', 'scope_json': "TEXT NOT NULL DEFAULT '[]'", 'data_origin': "TEXT NOT NULL DEFAULT 'constructed'", 'fingerprint': 'TEXT', 'snapshot_json': "TEXT NOT NULL DEFAULT '{}'"},
        }
        for table, fields in additions.items():
            existing = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            for name, definition in fields.items():
                if name not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluation_fingerprint ON evaluation_runs(fingerprint) WHERE fingerprint IS NOT NULL')
    if version < 4:
        for table, name, definition in [('work_items','withdrawn_at','TEXT'),('ai_jobs','filtered_task_count','INTEGER NOT NULL DEFAULT 0')]:
            existing = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            if name not in existing:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    if version < 5:
        additions = {
            'project_sources': {'auto_publish_enabled': 'INTEGER NOT NULL DEFAULT 0'},
            'ai_jobs': {'auto_publish': 'INTEGER NOT NULL DEFAULT 0'},
            'work_items': {'auto_generated': 'INTEGER NOT NULL DEFAULT 0', 'human_edited': 'INTEGER NOT NULL DEFAULT 0'},
        }
        for table, fields in additions.items():
            existing = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            for name, definition in fields.items():
                if name not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
