"""Same-scope, human-reviewed metrics with explicit denominators and provenance."""
from __future__ import annotations
import hashlib
import json
import math
from .ai.context import encode
from .export_utils import csv_text, project_aliases, safe_text
from .followup_reports import require_project
from .service import iso, now_utc
from .work_items import DeliveryError


def invalid(detail):
    raise DeliveryError('invalid_evaluation',detail)


class EvaluationService:
    def __init__(self,database):self.database=database

    def _inputs(self,conn,project_id,scope=None):
        require_project(conn,project_id)
        aliases=project_aliases(conn,project_id)
        rows=list(conn.execute('SELECT m.* FROM messages m JOIN project_sources s ON s.id=m.project_source_id WHERE s.project_id=? ORDER BY m.id LIMIT 2001',(project_id,))) if scope is None else list(conn.execute('SELECT m.* FROM messages m JOIN project_sources s ON s.id=m.project_source_id WHERE s.project_id=? AND m.id IN ('+','.join('?' for _ in scope)+') ORDER BY m.id',(project_id,*scope)))
        if len(rows)>2000:invalid('项目超过 2000 条消息，请通过接口指定消息范围')
        ids={r['id'] for r in rows}
        if scope is not None and ids!=set(scope):invalid('样本包含过期消息或其他项目消息')
        messages=[{'id':r['id'],'source_id':r['project_source_id'],'sender':safe_text(r['sender'],aliases),'timestamp':r['source_time'],'text':safe_text(r['content_text'],aliases),'quote_text':safe_text(r['quote_content'],aliases)} for r in rows]
        rules=[]
        for r in conn.execute('SELECT q.* FROM questions q JOIN messages m ON m.id=q.message_id JOIN project_sources s ON s.id=m.project_source_id WHERE s.project_id=? ORDER BY q.id',(project_id,)):
            if r['message_id'] in ids:rules.append({'id':r['id'],'type':'issue','title':safe_text(r['title'],aliases),'evidence_message_ids':[r['message_id']],'status':r['status'],'structured_fields':{},'field_evidence':{}})
        predictions=[];job_ids=set()
        for r in conn.execute('SELECT p.*,j.model,j.project_source_id FROM item_proposals p JOIN ai_jobs j ON j.id=p.job_id JOIN project_sources s ON s.id=j.project_source_id WHERE s.project_id=? ORDER BY p.id',(project_id,)):
            evidence=json.loads(r['evidence_ids'])
            if not ids.intersection(evidence):continue
            fields=json.loads(r['proposed_fields_json']);job_ids.add(r['job_id'])
            predictions.append({'id':r['id'],'job_id':r['job_id'],'model':r['model'],'type':fields['type'],'title':safe_text(fields['title'],aliases),'evidence_message_ids':evidence,'status':r['status'],
                                'structured_fields':{k:safe_text(v,aliases) for k,v in [('owner',fields.get('owner')),('deadline',fields.get('due_text')),('progress',fields.get('latest_progress'))] if v},'field_evidence':fields.get('field_evidence',{})})
        batches=[]
        for j in conn.execute('SELECT j.* FROM ai_jobs j JOIN project_sources s ON s.id=j.project_source_id WHERE s.project_id=? ORDER BY j.id',(project_id,)):
            if not ids.intersection(json.loads(j['input_message_ids'])):continue
            a=conn.execute('SELECT latency_ms,returned_model FROM ai_attempts WHERE job_id=? AND attempt=1',(j['id'],)).fetchone()
            batches.append({'id':j['id'],'status':j['status'],'attempts':j['attempts'],'input_message_ids':json.loads(j['input_message_ids']),'error_code':j['error_code'],'requested_model':j['model'],'returned_model':a['returned_model'] if a else None,'latency_ms':a['latency_ms'] if a and j['status']=='succeeded' and j['attempts']==1 else None})
        if len(predictions)>2000 or len(rules)>2000:invalid('候选超过 2000 条，请缩小消息范围')
        return {'project_id':project_id,'messages':messages,'rule_predictions':rules,'ai_predictions':predictions,'batches':batches,'rules_type_basis':'规则仅提取问题，不识别任务、决策、风险类型'}

    def inputs(self,project_id):
        with self.database.connection() as conn:return self._inputs(conn,project_id)

    @staticmethod
    def score(predictions,reviews,labels,ai=False):
        by_id={p['id']:p for p in predictions};seen=set();matched=set();correct=0;verified=0;field_total=0;field_reviewed=0
        for p in predictions:field_total+=len(p['structured_fields'])
        for r in reviews:
            if r.prediction_id not in by_id or r.prediction_id in seen:invalid('复核候选不存在或重复')
            seen.add(r.prediction_id);p=by_id[r.prediction_id]
            if r.label_id is not None:
                label=labels.get(r.label_id)
                if label is None or r.label_id in matched:invalid('同一方法不可重复匹配人工标注，且标注必须存在')
                if p['type']!=label.type or not set(p['evidence_message_ids']).intersection(label.evidence_message_ids):invalid('匹配的类型与依据必须一致；语义需由人工核对')
                matched.add(r.label_id);correct+=1
            fields=len(p['structured_fields'])
            if r.field_evidence_verified is not None:
                field_reviewed+=fields
                if r.field_evidence_verified:verified+=fields
        complete=len(seen)==len(predictions)
        return {'prediction_count':len(predictions),'reviewed_count':len(seen),'label_count':len(labels),'true_positive':correct,'false_positive':len(predictions)-correct if complete else None,'false_negative':len(labels)-correct if complete else None,
                'precision':correct/len(predictions) if complete and predictions else None,'recall':correct/len(labels) if complete and labels else None,'review_complete':complete,
                'field_count':field_total,'field_reviewed_count':field_reviewed,'field_evidence_verified_count':verified,'field_evidence_rate':verified/field_total if ai and field_total and field_reviewed==field_total else None,
                'matching_basis':'人工一对一语义复核；类型一致且依据相交；重复候选算误报','field_basis':'逐项核对该候选所有已填字段；仅全部有据才记正确，空值不计分母'}

    def create(self,data):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if len(set(data.scope_message_ids))!=len(data.scope_message_ids):invalid('样本消息 ID 不可重复')
            inputs=self._inputs(conn,data.project_id,data.scope_message_ids);aliases=project_aliases(conn,data.project_id)
            labels={l.id:l for l in data.labels}
            if len(labels)!=len(data.labels):invalid('人工标注 ID 不可重复')
            for label in data.labels:
                if len(set(label.evidence_message_ids))!=len(label.evidence_message_ids) or not set(label.evidence_message_ids).issubset(data.scope_message_ids):invalid('标注依据须属于样本且不可重复')
            rules=self.score(inputs['rule_predictions'],data.rule_reviews,labels)
            ai=self.score(inputs['ai_predictions'],data.ai_reviews,labels,True)
            covered={mid for b in inputs['batches'] if b['status']=='succeeded' for mid in b['input_message_ids']} & set(data.scope_message_ids)
            ai['analyzed_message_count']=len(covered)
            ai['unanalysed_message_count']=len(data.scope_message_ids)-len(covered)
            ai['analysis_scope_complete']=len(covered)==len(data.scope_message_ids)
            if not inputs['batches']:
                ai.update(recall=None,false_negative=None,review_complete=False)
            times=data.timings.model_dump();total=sum(times[k] for k in ('ai_wait_seconds','ai_review_seconds','export_seconds')) if all(times[k] is not None for k in ('ai_wait_seconds','ai_review_seconds','export_seconds')) else None
            reduction=(times['rule_seconds']-total)/times['rule_seconds'] if total is not None and times['rule_seconds'] else None
            latencies=sorted(b['latency_ms'] for b in inputs['batches'] if b['latency_ms'] is not None)
            mock=any((p.get('model','').lower().startswith(('mock','test','offline'))) for p in inputs['ai_predictions']) or any(b['requested_model'].lower().startswith(('mock','test','offline')) for b in inputs['batches'])
            if data.mode=='work_trial' and mock:invalid('模拟接口不能记为真实岗位试用')
            real=data.mode=='work_trial' and data.data_origin=='deidentified_work' and not mock
            metrics={'rules':rules,'ai':ai,'latency':{'single_attempt_success_count':len(latencies),'p95_ms':latencies[math.ceil(.95*len(latencies))-1] if latencies else None,'goal_eligible':real and len(latencies)>=20,'p95_le_45000':latencies[math.ceil(.95*len(latencies))-1]<=45000 if real and len(latencies)>=20 else None,'basis':'同样本成功且仅一次请求的批次；P95 最近秩；失败与重试另见批次清单'},
                     'timings':{**times,'ai_total_seconds':total,'reduction_fraction':reduction,'basis':'人工规则整理与 AI 等待+复核+导出；未记录保持空值'},
                     'quality_goal_eligible':real and len(labels)>=30 and ai['review_complete'] and ai['analysis_scope_complete'],'real_trial_user_declared':real,'mock_detected':mock,'auto_wrong_closure_count':0,'auto_closure_basis':'应用 AI 建议只进入待确认结果，关闭由人工执行；非人工操作准确率测量'}
            snapshot={'project_label':f'项目{data.project_id}','dataset_label':safe_text(data.dataset_label,aliases),'mode':data.mode,'data_origin':data.data_origin,'reviewer_label':safe_text(data.reviewer_label,aliases),'familiarity_note':safe_text(data.familiarity_note,aliases),'scope':inputs,'labels':[{**l.model_dump(),'title':safe_text(l.title,aliases)} for l in data.labels],'reviews':{'rules':[r.model_dump() for r in data.rule_reviews],'ai':[r.model_dump() for r in data.ai_reviews]},'metrics':metrics,'attested':True}
            fingerprint=hashlib.sha256(encode(snapshot).encode()).hexdigest()
            old=conn.execute('SELECT id FROM evaluation_runs WHERE fingerprint=?',(fingerprint,)).fetchone()
            if old:return self._get(conn,old[0])
            snapshot['created_at']=iso(now_utc())
            cur=conn.execute('INSERT INTO evaluation_runs(dataset_label,mode,human_labels,matched_items,timings,sample_count,metrics,reviewer_label,created_at,project_id,scope_json,data_origin,fingerprint,snapshot_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(snapshot['dataset_label'],data.mode,encode(snapshot['labels']),encode(snapshot['reviews']),encode(metrics['timings']),len(data.scope_message_ids),encode(metrics),snapshot['reviewer_label'],snapshot['created_at'],data.project_id,encode(data.scope_message_ids),data.data_origin,fingerprint,encode(snapshot)))
            return self._get(conn,cur.lastrowid)

    @staticmethod
    def _get(conn,id):
        r=conn.execute('SELECT id,project_id,snapshot_json FROM evaluation_runs WHERE id=?',(id,)).fetchone()
        if not r:raise DeliveryError('evaluation_not_found','评测不存在或依据已过期',404)
        snapshot=json.loads(r['snapshot_json'])
        if not snapshot:raise DeliveryError('evaluation_legacy','旧评测缺少依据快照，请重新评测',409)
        return {'id':r['id'],'project_id':r['project_id'],**snapshot}

    def get(self,id):
        with self.database.connection() as conn:return self._get(conn,id)

    def list(self,project_id=None):
        with self.database.connection() as conn:
            rows=conn.execute('SELECT id FROM evaluation_runs WHERE snapshot_json!=?'+(' AND project_id=?' if project_id else '')+' ORDER BY id DESC LIMIT 100',('{}',project_id) if project_id else ('{}',))
            return {'items':[self._get(conn,r['id']) for r in rows]}

    def export(self,id):
        r=self.get(id);rows=[]
        for method in ('rules','ai'):
            reviews={v['prediction_id']:v for v in r['reviews'][method]}
            for p in r['scope']['rule_predictions' if method=='rules' else 'ai_predictions']:
                v=reviews.get(p['id'],{})
                rows.append([r['dataset_label'],r['mode'],r['data_origin'],r['created_at'],method,p['id'],p['type'],p['title'],encode(p['evidence_message_ids']),p['status'],v.get('label_id'),v.get('field_evidence_verified'),encode(r['metrics']),encode(r['labels']),encode(r['scope']),r['familiarity_note']])
        if not rows:rows=[[r['dataset_label'],r['mode'],r['data_origin'],r['created_at']]+[None]*8+[encode(r['metrics']),encode(r['labels']),encode(r['scope']),r['familiarity_note']]]
        return csv_text(['样本','模式','数据来源','生成时间','方法','候选ID','类型','标题','依据ID','候选状态','人工匹配标注','字段证据人工核对','指标及分子分母','人工标注','样本及批次证据','熟悉样本偏差说明'],rows)
