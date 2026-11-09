from __future__ import annotations

import json
import uuid
from datetime import timedelta

from ..service import iso, now_utc
from ..work_items import DeliveryError, require_source
from .context import build_context, encode, next_batch
from .prompts import PROMPT_VERSION

JOB_COLUMNS='id,project_source_id,input_message_ids,context_versions,prompt_version,model,status,attempts,lease_until,next_retry_at,error_code,created_at,completed_at,filtered_task_count,auto_publish'


class JobService:
    def __init__(self, database, store):
        self.database,self.store=database,store

    def ready(self):
        config,key=self.store.snapshot()
        if not config.enabled:
            raise DeliveryError('ai_disabled','请在模型设置中启用分析；启用后仍须预览并确认发送范围',409)
        if not key:
            raise DeliveryError('key_missing','请先在模型设置中保存 DeepSeek API Key',409)
        return config

    def preview(self, data):
        config,_=self.store.snapshot()  # A preview is available offline, without a key.
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            built=next_batch(conn,data.project_source_id,data.after_message_id,data.through_message_id,config)
            token=uuid.uuid4().hex
            conn.execute('DELETE FROM ai_previews WHERE created_at<?',(iso(now_utc()-timedelta(hours=24)),))
            conn.execute('INSERT INTO ai_previews VALUES(?,?,?,?,?)',(token,data.project_source_id,encode(built['input_ids']),built['input_hash'],iso(now_utc())))
        return {'preview_token':token,'project_source_id':data.project_source_id,'model':config.model,
                'input_message_ids':built['input_ids'],'through_message_id':max(built['input_ids']),
                'has_more':built['has_more'],'context':built['context'],'prompt_version':PROMPT_VERSION}

    @staticmethod
    def insert(conn, source_id, built, advance=False, auto_publish=False):
        inserted=conn.execute('INSERT OR IGNORE INTO ai_jobs(project_source_id,input_message_ids,input_hash,context_versions,prompt_version,model,status,created_at,context_json,persons_json,config_json,context_message_ids) VALUES(?,?,?,?,?,?,\'queued\',?,?,?,?,?)',
                     (source_id,encode(built['input_ids']),built['input_hash'],encode(built['versions']),PROMPT_VERSION,built['config']['model'],iso(now_utc()),encode(built['context']),encode(built['persons']),encode(built['config']),encode(built['context_ids'])))
        row=conn.execute(f'SELECT {JOB_COLUMNS} FROM ai_jobs WHERE project_source_id=? AND input_hash=?',(source_id,built['input_hash'])).fetchone()
        if inserted.rowcount:
            conn.execute('UPDATE ai_jobs SET auto_publish=? WHERE id=?',(int(auto_publish),row['id']))
            conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES(?,?,?)',('delivery_analysis_enqueue',encode({'job_id':row['id'],'source_id':source_id,'message_count':len(built['input_ids'])}),iso(now_utc())))
        if advance:
            conn.execute('UPDATE project_sources SET last_enqueued_message_id=MAX(last_enqueued_message_id,?),analysis_error=NULL WHERE id=?',(max(built['input_ids']),source_id))
        return {**dict(row),'auto_publish':int(auto_publish) if inserted.rowcount else row['auto_publish']}

    def enqueue(self, data):
        config=self.ready()
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            p=conn.execute('SELECT * FROM ai_previews WHERE token=?',(data.preview_token,)).fetchone()
            if not p or p['created_at']<iso(now_utc()-timedelta(hours=24)):
                raise DeliveryError('preview_expired','分析预览已过期，请重新预览',409)
            built=build_context(conn,p['project_source_id'],json.loads(p['input_message_ids']),config)
            if built['input_hash']!=p['input_hash']:
                raise DeliveryError('preview_changed','消息、事项或模型配置已变化，请重新预览并确认',409)
            return self.insert(conn,p['project_source_id'],built,advance=True)

    def automation(self, source_id, data):
        if data.enabled:
            self.ready()
            if not data.consent:
                raise DeliveryError('consent_required','请确认该来源的后续消息会发送给 DeepSeek')
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE');require_source(conn,source_id)
            if data.enabled:
                source=conn.execute('SELECT auto_analysis_enabled FROM project_sources WHERE id=?',(source_id,)).fetchone()
                if not source[0]:
                    baseline=conn.execute('SELECT COALESCE(MAX(id),0) FROM messages WHERE project_source_id=?',(source_id,)).fetchone()[0]
                    conn.execute('UPDATE project_sources SET last_enqueued_message_id=MAX(last_enqueued_message_id,?) WHERE id=?',(baseline,source_id))
            old=conn.execute('SELECT auto_analysis_enabled FROM project_sources WHERE id=?',(source_id,)).fetchone()[0]
            conn.execute('UPDATE project_sources SET auto_analysis_enabled=?,auto_publish_enabled=0,analysis_error=NULL WHERE id=?',(data.enabled,source_id))
            if old!=int(data.enabled):
                conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES(?,?,?)',('delivery_automation_toggle',encode({'source_id':source_id,'enabled':data.enabled}),iso(now_utc())))
            return dict(conn.execute('SELECT * FROM project_sources WHERE id=?',(source_id,)).fetchone())

    def enqueue_automatic(self):
        try:config=self.ready()
        except DeliveryError:return
        with self.database.connection() as conn:
            source_ids=[r[0] for r in conn.execute('SELECT id FROM project_sources WHERE auto_analysis_enabled=1')]
        for source_id in source_ids:
            try:
                with self.database.connection() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    source=require_source(conn,source_id)
                    # Recheck the toggle under the transaction; do not race user disable.
                    if not source['auto_analysis_enabled']:continue
                    # Automatic results need the preceding batch's current item versions.
                    if source['auto_publish_enabled'] and conn.execute("SELECT 1 FROM ai_jobs WHERE project_source_id=? AND status IN ('queued','running')",(source_id,)).fetchone():continue
                    built=next_batch(conn,source_id,source['last_enqueued_message_id'],None,config)
                    self.insert(conn,source_id,built,advance=True,auto_publish=bool(source['auto_publish_enabled']))
            except DeliveryError as exc:
                if exc.code=='no_messages':continue
                with self.database.connection() as conn:
                    conn.execute('UPDATE project_sources SET analysis_error=? WHERE id=?',(exc.code,source_id))

    def list(self, project_id=None):
        with self.database.connection() as conn:
            sql=f'SELECT '+','.join('j.'+c for c in JOB_COLUMNS.split(','))+',s.display_name FROM ai_jobs j JOIN project_sources s ON s.id=j.project_source_id'
            args=()
            if project_id is not None:sql+=' WHERE s.project_id=?';args=(project_id,)
            return {'items':[dict(r) for r in conn.execute(sql+' ORDER BY j.id DESC LIMIT 100',args)]}

    def get(self, job_id):
        with self.database.connection() as conn:
            row=conn.execute(f'SELECT {JOB_COLUMNS} FROM ai_jobs WHERE id=?',(job_id,)).fetchone()
            if not row:raise DeliveryError('job_not_found','分析任务不存在',404)
            result=dict(row)
            result['attempt_details']=[dict(r) for r in conn.execute('SELECT attempt,requested_model,returned_model,latency_ms,tokens,finish_reason,error_code FROM ai_attempts WHERE job_id=? ORDER BY attempt',(job_id,))]
            return result

    def action(self, job_id, action):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM ai_jobs WHERE id=?',(job_id,)).fetchone()
            if not row:raise DeliveryError('job_not_found','分析任务不存在',404)
            if action=='cancel':
                if row['status'] in ('queued','running'):
                    conn.execute("UPDATE ai_jobs SET status='cancelled',lease_token=NULL,lease_until=NULL,completed_at=? WHERE id=?",(iso(now_utc()),job_id))
            elif row['status']=='failed':
                self.ready();require_source(conn,row['project_source_id'])
                if row['attempts']>=3:raise DeliveryError('attempt_limit','本任务已达三次请求上限；请核对失败原因后调整配置并重新预览',409)
                conn.execute("UPDATE ai_jobs SET status='queued',error_code=NULL,completed_at=NULL WHERE id=?",(job_id,))
        return self.get(job_id)
