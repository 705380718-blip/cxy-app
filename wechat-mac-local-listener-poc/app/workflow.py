"""Atomic onboarding reuses existing projects, whitelist, and source bindings."""
from __future__ import annotations
import json
from pydantic import BaseModel,Field,field_validator
from typing import Literal
from .models import STRICT,RuleSettingsUpdate
from .service import iso,now_utc
from .work_items import DeliveryError


class WorkflowSetup(BaseModel):
    model_config=STRICT
    project_name: str=Field(min_length=1,max_length=100)
    groups: list[str]=Field(min_length=1,max_length=30)
    self_names: list[str]=Field(min_length=1,max_length=10)
    source_kind: Literal['decoder','import']='decoder'

    @field_validator('groups','self_names')
    @classmethod
    def clean(cls,values):
        values=RuleSettingsUpdate.clean_values(values)
        if not values:raise ValueError('群名和昵称不能为空')
        return values


class WorkflowAutomation(BaseModel):
    model_config=STRICT
    project_id: int=Field(ge=1)
    enabled: bool
    consent: bool=False


class WorkflowService:
    def __init__(self,database,delivery,store):self.database,self.delivery,self.store=database,delivery,store

    def setup(self,data):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE');now=iso(now_utc())
            project=conn.execute('SELECT * FROM projects WHERE name=?',(data.project_name,)).fetchone()
            if project and not project['enabled']:raise DeliveryError('project_disabled','整理空间已停用，请使用其他名称',409)
            if project:pid=project['id']
            else:pid=conn.execute('INSERT INTO projects(name,created_at) VALUES(?,?)',(data.project_name,now)).lastrowid
            old_groups=json.loads(conn.execute('SELECT groups_json FROM settings WHERE id=1').fetchone()[0])
            owned={r[0] for r in conn.execute('SELECT source_key FROM project_sources WHERE project_id=?',(pid,))}
            other={r[0] for r in conn.execute('SELECT source_key FROM project_sources WHERE project_id!=?',(pid,))}
            # Preserve other projects and unbound legacy whitelist groups. Removed own groups stop capture.
            groups=list(dict.fromkeys([g for g in old_groups if g not in owned or g in other]+data.groups))
            if len(groups)>30:raise DeliveryError('group_limit','所有整理空间合计最多 30 个采集群，请先整理群名单')
            source_ids=[]
            for group in data.groups:
                old=conn.execute('SELECT * FROM project_sources WHERE source_kind=? AND source_key=?',(data.source_kind,group)).fetchone()
                if old and old['project_id']!=pid:raise DeliveryError('source_bound',f'群“{group}”已绑定其他整理空间，请选择原空间或其他群',409)
                if old:source_ids.append(old['id'])
                else:source_ids.append(conn.execute('INSERT INTO project_sources(project_id,source_kind,source_key,display_name) VALUES(?,?,?,?)',(pid,data.source_kind,group,group)).lastrowid)
            conn.execute('UPDATE settings SET groups_json=?,self_names_json=?,updated_at=? WHERE id=1',(json.dumps(groups,ensure_ascii=False),json.dumps(data.self_names,ensure_ascii=False),now))
            # No migration of old messages, no listener or model side effect.
            latest=conn.execute("SELECT detail_json FROM audit_log WHERE action='workflow_setup' ORDER BY id DESC LIMIT 1").fetchone()
            detail={'project_id':pid,'source_ids':source_ids,'source_kind':data.source_kind}
            if not latest or json.loads(latest[0])!=detail:conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES(?,?,?)',('workflow_setup',json.dumps(detail),now))
        return self.status(pid)

    def automation(self,data):
        if data.enabled and not data.consent:
            raise DeliveryError('consent_required','请同意配置群的后续脱敏文本自动发送至 DeepSeek')
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM projects WHERE id=? AND enabled=1',(data.project_id,)).fetchone():
                raise DeliveryError('project_not_found','整理空间不存在',404)
            groups=json.loads(conn.execute('SELECT groups_json FROM settings WHERE id=1').fetchone()[0])
            sources=conn.execute('SELECT * FROM project_sources WHERE project_id=?',(data.project_id,)).fetchall()
            allowed=[s for s in sources if s['source_key'] in groups]
            if data.enabled and not allowed:raise DeliveryError('source_not_found','请先配置需要采集的群',409)
            for source in sources:
                enabled=bool(data.enabled and source['source_key'] in groups)
                if enabled and not source['auto_analysis_enabled']:
                    baseline=conn.execute('SELECT COALESCE(MAX(id),0) FROM messages WHERE project_source_id=?',(source['id'],)).fetchone()[0]
                    conn.execute('UPDATE project_sources SET last_enqueued_message_id=MAX(last_enqueued_message_id,?) WHERE id=?',(baseline,source['id']))
                conn.execute('UPDATE project_sources SET auto_analysis_enabled=?,auto_publish_enabled=?,analysis_error=NULL WHERE id=?',(enabled,enabled,source['id']))
            if not data.enabled:
                conn.execute("UPDATE ai_jobs SET status='cancelled',lease_token=NULL,lease_until=NULL,completed_at=? WHERE auto_publish=1 AND status IN ('queued','running') AND project_source_id IN (SELECT id FROM project_sources WHERE project_id=?)",(iso(now_utc()),data.project_id))
            conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES(?,?,?)',('workflow_automation',json.dumps({'project_id':data.project_id,'enabled':data.enabled,'source_ids':[s['id'] for s in allowed]}),iso(now_utc())))
        return self.status(data.project_id)

    def status(self,project_id=None):
        projects=[p for p in self.delivery.projects()['items'] if p['enabled']]
        with self.database.connection() as conn:
            settings=dict(conn.execute('SELECT * FROM settings WHERE id=1').fetchone())
            last=conn.execute("SELECT detail_json FROM audit_log WHERE action='workflow_setup' ORDER BY id DESC LIMIT 1").fetchone()
            if project_id is None:
                candidate=json.loads(last[0])['project_id'] if last else None
                project_id=candidate if any(p['id']==candidate for p in projects) else (projects[0]['id'] if projects else None)
            selected=next((p for p in projects if p['id']==project_id),None)
            if project_id is not None and not selected:raise DeliveryError('project_not_found','整理空间不存在',404)
            groups=json.loads(settings['groups_json']);sources=[s for s in selected['sources'] if s['source_key'] in groups] if selected else []
            count=sum(s['message_count'] for s in sources)
            ids=[s['id'] for s in sources]
            messages=[dict(r) for r in conn.execute(f"SELECT id,source_time,sender,content,chat_name,source_kind FROM messages WHERE project_source_id IN ({','.join('?' for _ in ids)}) ORDER BY id DESC LIMIT 8",ids)] if ids else []
            preferred=conn.execute("SELECT detail_json FROM audit_log WHERE action='workflow_setup' ORDER BY id DESC").fetchall()
            chosen=next((json.loads(r[0]) for r in preferred if json.loads(r[0])['project_id']==project_id),None)
            kind=chosen['source_kind'] if chosen else (sources[0]['source_kind'] if sources else 'decoder')
            auto_enabled=bool(sources) and all(s['auto_analysis_enabled'] and s['auto_publish_enabled'] for s in sources)
            job_counts={r['status']:r['n'] for r in conn.execute('SELECT j.status,COUNT(*) AS n FROM ai_jobs j JOIN project_sources s ON s.id=j.project_source_id WHERE s.project_id=? GROUP BY j.status',(project_id,))}
            intervention=conn.execute("SELECT COUNT(*) FROM item_proposals p JOIN ai_jobs j ON j.id=p.job_id JOIN project_sources s ON s.id=j.project_source_id WHERE s.project_id=? AND j.auto_publish=1 AND p.status='pending' AND (p.target_item_id IS NULL OR EXISTS (SELECT 1 FROM work_items w WHERE w.id=p.target_item_id AND w.withdrawn_at IS NULL))",(project_id,)).fetchone()[0]
            rules_saved=bool(conn.execute("SELECT 1 FROM audit_log WHERE action='update_rules' LIMIT 1").fetchone())
        ai=self.store.public()
        return {'project':selected,'projects':projects,'sources':sources,'groups':list(dict.fromkeys(s['source_key'] for s in sources)),
                'source_kind':kind,'self_names':json.loads(settings['self_names_json']),'message_count':count,'recent_messages':messages,'source_ready':bool(sources),'rules_saved':rules_saved,
                'key_configured':ai['key_configured'],'ai_enabled':ai['enabled'],'automatic_results':auto_enabled,'automation_jobs':job_counts,'intervention_count':intervention}
