"""One lifecycle-owned worker; persistent inputs and bounded attempt leases."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import timedelta

from ..service import iso, now_utc
from ..work_items import DeliveryError, WorkItemService, require_source
from ..models import ProposalApply
from .context import encode
from .schemas import AISettings, resolve_deadline
from .prompts import PROMPT_VERSION
from .task_filter import supported_task

logger=logging.getLogger(__name__)


class AnalysisWorker:
    def __init__(self, database, jobs, client):
        self.database,self.jobs,self.client=database,jobs,client
        self.task=None
        self.scheduler_task=None
        self.lock=asyncio.Lock()
        self.stopping=False

    async def start(self):
        self.stopping=False
        self.task=asyncio.create_task(self.run(),name='delivery-analysis-worker')
        self.scheduler_task=asyncio.create_task(self.enqueue_loop(),name='delivery-queue-scanner')

    async def stop(self):
        self.stopping=True
        tasks=[task for task in (self.task,self.scheduler_task) if task]
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        self.task=self.scheduler_task=None

    async def enqueue_loop(self):
        # Queue scanning keeps running while the single analysis worker awaits HTTP.
        while not self.stopping:
            try:self.jobs.enqueue_automatic()
            except asyncio.CancelledError:raise
            except Exception:logger.error('delivery queue scan failed; see source status')
            await asyncio.sleep(2)

    async def run(self):
        while not self.stopping:
            try:
                await self.run_once()
            except asyncio.CancelledError:raise
            except Exception:
                # Never log a payload, key, exception text or database content.
                logger.error('delivery worker cycle failed; see persistent job status')
            await asyncio.sleep(2)

    def recover(self):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE ai_jobs SET status=CASE WHEN attempts<3 THEN 'queued' ELSE 'failed' END,error_code='interrupted',lease_token=NULL,lease_until=NULL WHERE status='running' AND lease_until<?",(iso(now_utc()),))

    def claim(self):
        self.recover()
        try:self.jobs.ready()
        except DeliveryError:return None
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute("SELECT j.* FROM ai_jobs j WHERE status='queued' AND NOT EXISTS (SELECT 1 FROM ai_jobs r WHERE r.project_source_id=j.project_source_id AND r.status='running') ORDER BY id LIMIT 1").fetchone()
            if not row:return None
            try:
                require_source(conn,row['project_source_id'])
                context=json.loads(row['context_json'])
                ids=json.loads(row['context_message_ids'])
                if not ids or not context.get('new_message_ids'):raise DeliveryError('context_invalid','旧任务缺少固定上下文，请重新预览')
                found={r[0] for r in conn.execute('SELECT id FROM messages WHERE project_source_id=? AND id IN (%s)' % ','.join('?'*len(ids)),(row['project_source_id'],*ids))}
                if found!=set(ids):raise DeliveryError('evidence_expired','上下文依据已过期')
                if row['prompt_version']!=PROMPT_VERSION:raise DeliveryError('prompt_changed','提示词已变化，请重新预览')
                if row['attempts']>=3:raise DeliveryError('attempt_limit','请求次数已达上限')
            except DeliveryError as exc:
                conn.execute("UPDATE ai_jobs SET status='failed',error_code=?,completed_at=? WHERE id=?",(exc.code,iso(now_utc()),row['id']))
                return None
            token=uuid.uuid4().hex
            conn.execute("UPDATE ai_jobs SET status='running',lease_token=?,lease_until=?,error_code=NULL WHERE id=?",(token,iso(now_utc()+timedelta(seconds=240)),row['id']))
            return {**dict(row),'lease_token':token}

    def guard(self, conn, job):
        row=conn.execute('SELECT status,lease_token,attempts FROM ai_jobs WHERE id=?',(job['id'],)).fetchone()
        if self.stopping or not row or row['status']!='running' or row['lease_token']!=job['lease_token']:
            raise DeliveryError('lease_lost','任务已取消或依据已过期',409)
        return row

    async def run_once(self):
        if self.lock.locked():return False
        async with self.lock:
            job=self.claim()
            if not job:return False
            attempt_number=None
            def before():
                nonlocal attempt_number
                with self.database.connection() as conn:
                    conn.execute('BEGIN IMMEDIATE');row=self.guard(conn,job)
                    if row['attempts']>=3:raise DeliveryError('attempt_limit','请求次数已达上限',409)
                    attempt_number=row['attempts']+1
                    conn.execute('UPDATE ai_jobs SET attempts=? WHERE id=?',(attempt_number,job['id']))
                    conn.execute('INSERT INTO ai_attempts(job_id,attempt,requested_model) VALUES(?,?,?)',(job['id'],attempt_number,job['model']))
            def after(metrics):
                with self.database.connection() as conn:
                    conn.execute('BEGIN IMMEDIATE');self.guard(conn,job)
                    for key in ('returned_model','request_id','latency_ms','tokens','finish_reason','error_code'):
                        if key in metrics:conn.execute(f'UPDATE ai_attempts SET {key}=? WHERE job_id=? AND attempt=?',(metrics[key],job['id'],attempt_number))
            try:
                config=AISettings.model_validate_json(job['config_json'])
                with self.database.connection() as conn:
                    corrected=bool(conn.execute("SELECT 1 FROM ai_attempts WHERE job_id=? AND error_code IN ('result_invalid','truncated','empty_content')",(job['id'],)).fetchone())
                result,_=await self.client.analyze_job(config,json.loads(job['context_json']),max_attempts=3-job['attempts'],before_attempt=before,after_attempt=after,corrected=corrected)
                self.finish(job,result)
            except asyncio.CancelledError:
                self.release(job)
                raise
            except asyncio.TimeoutError:
                self.fail(job,'task_timeout')
            except DeliveryError as exc:
                self.fail(job,exc.code)
            except Exception:
                self.fail(job,'internal_error')
            return True

    def release(self, job):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE ai_jobs SET status=CASE WHEN attempts<3 THEN 'queued' ELSE 'failed' END,error_code='interrupted',lease_until=NULL,lease_token=NULL WHERE id=? AND status='running' AND lease_token=?",(job['id'],job['lease_token']))
            conn.execute("UPDATE ai_attempts SET error_code='interrupted' WHERE job_id=? AND finish_reason IS NULL AND error_code IS NULL",(job['id'],))

    def fail(self, job, code):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE ai_jobs SET status='failed',error_code=?,completed_at=?,lease_until=NULL,lease_token=NULL WHERE id=? AND status='running' AND lease_token=?",(code,iso(now_utc()),job['id'],job['lease_token']))
            conn.execute('UPDATE ai_attempts SET error_code=? WHERE job_id=? AND finish_reason IS NULL AND error_code IS NULL',(code,job['id']))

    def finish(self, job, result):
        context=json.loads(job['context_json']);persons=json.loads(job['persons_json']);versions=json.loads(job['context_versions'])
        messages={r['id']:r for r in context['messages']}
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE');self.guard(conn,job)
            # Revalidate the source/retention boundary after the network round trip.
            source=require_source(conn,job['project_source_id'])
            automatic=bool(job.get('auto_publish') and source['auto_analysis_enabled'] and source['auto_publish_enabled'])
            filtered = 0
            for candidate in result.items:
                if automatic:
                    if not set(candidate.evidence_message_ids).intersection(context['new_message_ids']):continue
                    if candidate.type=='task' and candidate.target_item_id is None and candidate.task_basis and candidate.task_basis.message_id not in context['new_message_ids']:continue
                if not supported_task(candidate,messages):
                    filtered += 1
                    continue
                if candidate.target_item_id is not None:
                    target = conn.execute('SELECT withdrawn_at FROM work_items WHERE id=?',(candidate.target_item_id,)).fetchone()
                    if not target or target['withdrawn_at']:
                        continue
                fields=candidate.model_dump()
                fields['owner']=persons.get(candidate.owner_ref)
                deadline_ids=candidate.field_evidence.get('deadline',[])
                fields['due_at']=resolve_deadline(candidate.due_text,messages[deadline_ids[-1]]['timestamp']) if deadline_ids else None
                if candidate.due_text and not fields['due_at']:
                    fields['needs_confirmation'].append('deadline_precision')
                fields['work_status']=candidate.suggested_status
                conn.execute('INSERT OR IGNORE INTO item_proposals(job_id,candidate_key,target_item_id,target_version,proposed_fields_json,evidence_ids) VALUES(?,?,?,?,?,?)',
                             (job['id'],candidate.candidate_key,candidate.target_item_id,versions.get(str(candidate.target_item_id)),encode(fields),encode(candidate.evidence_message_ids)))
            if automatic:
                delivery=WorkItemService(self.database)
                proposals=conn.execute("SELECT id,target_version FROM item_proposals WHERE job_id=? AND status='pending' ORDER BY id",(job['id'],)).fetchall()
                for proposal in proposals:
                    conn.execute('SAVEPOINT auto_result')
                    try:
                        delivery._apply_proposal(conn,proposal['id'],ProposalApply(expected_version=proposal['target_version']),automatic=True)
                        conn.execute('RELEASE auto_result')
                    except DeliveryError:
                        conn.execute('ROLLBACK TO auto_result');conn.execute('RELEASE auto_result')
                        # A conflict stays visible as a suggestion; successful results still commit.
            conn.execute("UPDATE ai_jobs SET status='succeeded',completed_at=?,filtered_task_count=?,lease_token=NULL,lease_until=NULL,error_code=NULL WHERE id=?",(iso(now_utc()),filtered,job['id']))
