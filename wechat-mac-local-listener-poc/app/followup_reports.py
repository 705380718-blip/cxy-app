"""Programmatic, immutable report snapshots; no extra model call."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta

from .ai.context import encode
from .export_utils import csv_text, markdown_text, project_aliases, safe_text
from .service import CST, iso, now_utc
from .work_items import DeliveryError

TYPES={'issue':'问题','task':'任务','decision':'决策','risk':'风险'}
STATUSES={'open':'待处理','in_progress':'处理中','waiting_confirmation':'待确认结果','resolved':'已解决'}


def require_project(conn, project_id):
    if not conn.execute('SELECT id FROM projects WHERE id=? AND enabled=1',(project_id,)).fetchone():
        raise DeliveryError('project_not_found','项目不存在或已停用',404)


class FollowupReportService:
    def __init__(self,database):self.database=database

    def generate(self,data):
        start=iso(datetime.combine(data.start_date,time.min,CST))
        end=iso(datetime.combine(data.end_date+timedelta(days=1),time.min,CST))
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE');require_project(conn,data.project_id)
            aliases=project_aliases(conn,data.project_id)
            sources=[dict(r) for r in conn.execute('SELECT * FROM project_sources WHERE project_id=? ORDER BY id',(data.project_id,))]
            messages=[dict(r) for r in conn.execute('SELECT m.id,m.project_source_id,m.source_time FROM messages m JOIN project_sources s ON s.id=m.project_source_id WHERE s.project_id=? AND m.source_time>=? AND m.source_time<? ORDER BY m.id LIMIT 20001',(data.project_id,start,end))]
            if len(messages)>20000:raise DeliveryError('range_too_large','区间超过 20000 条消息，请缩短报告区间')
            scope={m['id'] for m in messages};by_source={s['id']:{m['id'] for m in messages if m['project_source_id']==s['id']} for s in sources}
            analyzed=set();job_counts={k:0 for k in ('queued','running','succeeded','failed','cancelled')};relevant_jobs=[]
            for job in conn.execute('SELECT j.id,j.project_source_id,j.status,j.input_message_ids,j.error_code FROM ai_jobs j JOIN project_sources s ON s.id=j.project_source_id WHERE s.project_id=? ORDER BY j.id',(data.project_id,)):
                intersection=scope.intersection(json.loads(job['input_message_ids']))
                if not intersection:continue
                job_counts[job['status']]+=1
                relevant_jobs.append({'id':job['id'],'source_id':job['project_source_id'],'status':job['status'],'error_code':job['error_code']})
                if job['status']=='succeeded':analyzed.update(intersection)
            groups=set(json.loads(conn.execute('SELECT groups_json FROM settings WHERE id=1').fetchone()[0]))
            coverage_sources=[]
            for s in sources:
                ids=by_source[s['id']];times=[m['source_time'] for m in messages if m['id'] in ids]
                coverage_sources.append({'source_id':s['id'],'label':f"来源{s['id']}",'kind':s['source_kind'],'allowed':s['source_key'] in groups,
                                         'message_count':len(ids),'analyzed_count':len(ids&analyzed),'unanalysed_count':len(ids-analyzed),
                                         'first_message_at':min(times) if times else None,'last_message_at':max(times) if times else None})
            coverage={'message_count':len(scope),'analyzed_count':len(analyzed),'unanalysed_count':len(scope-analyzed),'job_counts':job_counts,'jobs':relevant_jobs,'sources':coverage_sources,
                      'message_range_start':start,'message_range_end_exclusive':end,'state_basis':'generation_snapshot',
                      'rule_output_is_ai_analysis':False,'continuous_capture_verified':False}
            rows=[dict(r) for r in conn.execute("SELECT w.* FROM work_items w JOIN project_sources s ON s.id=w.project_source_id WHERE s.project_id=? AND w.merged_into IS NULL AND w.withdrawn_at IS NULL AND w.evidence_expired=0 AND w.review_status!='ignored' ORDER BY w.id",(data.project_id,))]
            if len(rows)>1000:raise DeliveryError('range_too_large','项目超过 1000 条有效事项，请缩小项目范围')
            items=[]
            for item in rows:
                evidence=[dict(r) for r in conn.execute('SELECT e.field,m.id,m.project_source_id,m.sender,m.source_time,m.content_text,m.quote_sender,m.quote_content,m.source_kind FROM item_evidence e JOIN messages m ON m.id=e.message_id WHERE e.item_id=? ORDER BY m.source_time,m.id,e.field',(item['id'],))]
                # Carry unresolved items forward; include closed items only with period evidence.
                if not evidence or (item['work_status']=='resolved' and not scope.intersection(r['id'] for r in evidence)):continue
                clean={k:item[k] for k in ('id','project_source_id','type','review_status','work_status','version','due_at','updated_at','auto_generated')}
                clean.update({k:safe_text(item[k],aliases) if item[k] else None for k in ('title','owner','due_text','latest_progress')})
                clean['evidence']=[{'message_id':r['id'],'field':r['field'],'source_id':r['project_source_id'],'sender':safe_text(r['sender'],aliases),'timestamp':r['source_time'],
                                    'text':safe_text(r['content_text'],aliases),'quote_sender':safe_text(r['quote_sender'],aliases),'quote_text':safe_text(r['quote_content'],aliases),
                                    'source_kind':r['source_kind'],'outside_period':r['id'] not in scope} for r in evidence]
                items.append(clean)
            pending=[]
            for p in conn.execute("SELECT p.id,p.target_item_id,p.proposed_fields_json,p.evidence_ids,j.project_source_id,j.id AS job_id FROM item_proposals p JOIN ai_jobs j ON j.id=p.job_id JOIN project_sources s ON s.id=j.project_source_id WHERE s.project_id=? AND p.status='pending' AND (p.target_item_id IS NULL OR EXISTS (SELECT 1 FROM work_items w WHERE w.id=p.target_item_id AND w.withdrawn_at IS NULL)) ORDER BY p.id",(data.project_id,)):
                if scope.intersection(json.loads(p['evidence_ids'])):
                    fields=json.loads(p['proposed_fields_json']);pending.append({'id':p['id'],'job_id':p['job_id'],'source_id':p['project_source_id'],'target_item_id':p['target_item_id'],'title':safe_text(fields.get('title'),aliases)})
            coverage['pending_proposal_count']=len(pending)
            snapshot={'project_label':f'项目{data.project_id}','start_date':data.start_date.isoformat(),'end_date':data.end_date.isoformat(),'items':items,'pending_proposals':pending,'coverage':coverage}
            fingerprint=hashlib.sha256(encode(snapshot).encode()).hexdigest()
            old=conn.execute('SELECT id FROM followup_reports WHERE project_id=? AND period_start=? AND period_end=? AND item_versions=?',(data.project_id,start,end,fingerprint)).fetchone()
            if old:return self._get(conn,old[0])
            snapshot['generated_at']=iso(now_utc());content=self.markdown(snapshot)
            cur=conn.execute('INSERT INTO followup_reports(project_id,period_start,period_end,item_versions,content,coverage,created_at,snapshot_json) VALUES(?,?,?,?,?,?,?,?)',(data.project_id,start,end,fingerprint,content,encode(coverage),snapshot['generated_at'],encode(snapshot)))
            conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES(?,?,?)',('delivery_report_generate',encode({'report_id':cur.lastrowid,'project_id':data.project_id,'item_count':len(items),'message_count':len(scope)}),snapshot['generated_at']))
            return self._get(conn,cur.lastrowid)

    @staticmethod
    def _get(conn,report_id):
        row=conn.execute('SELECT * FROM followup_reports WHERE id=?',(report_id,)).fetchone()
        if not row:raise DeliveryError('report_not_found','报告不存在或因依据过期而失效',404)
        data=dict(row);data['coverage']=json.loads(data['coverage']);data['snapshot']=json.loads(data.pop('snapshot_json'))
        if not data['snapshot']:raise DeliveryError('report_legacy','旧报告缺少导出快照，请重新生成',409)
        return data

    def get(self,report_id):
        with self.database.connection() as conn:return self._get(conn,report_id)

    def list(self,project_id=None):
        with self.database.connection() as conn:
            sql='SELECT id,project_id,period_start,period_end,created_at,coverage FROM followup_reports';args=()
            if project_id:sql+=' WHERE project_id=?';args=(project_id,)
            return {'items':[{**dict(r),'start_date':datetime.fromisoformat(r['period_start']).astimezone(CST).date().isoformat(),'end_date':(datetime.fromisoformat(r['period_end']).astimezone(CST).date()-timedelta(days=1)).isoformat(),'coverage':json.loads(r['coverage'])} for r in conn.execute(sql+' ORDER BY id DESC LIMIT 100',args)]}

    @staticmethod
    def markdown(snapshot):
        c=snapshot['coverage'];m=markdown_text
        lines=[f"# {snapshot['project_label']} · 跟进报告",'',f"消息区间：{snapshot['start_date']} 至 {snapshot['end_date']}（北京时间，含结束日期）",f"当前事项快照生成于：{snapshot['generated_at']}。不还原历史时点状态。",'',
               f"区间消息 {c['message_count']} 条；分析成功覆盖 {c['analyzed_count']} 条；未成功分析 {c['unanalysed_count']} 条。",f"队列：排队 {c['job_counts']['queued']}、运行 {c['job_counts']['running']}、失败 {c['job_counts']['failed']}、取消 {c['job_counts']['cancelled']} 批。",'覆盖仅代表本机已入库文本，不能证明群聊完整或持续采集；未分析不能视作无风险。','导出使用人物/来源代号及规则脱敏，发布前仍需核对正文。','', '## 来源范围','']
        for s in c['sources']:lines.append(f"- {s['label']}：{'手动导入' if s['kind']=='import' else '本机采集'}；{s['message_count']} 条，未成功分析 {s['unanalysed_count']} 条；当前白名单{'内' if s['allowed'] else '外'}。")
        for review,label in [('confirmed','已确认事项'),('pending','AI 整理与待复核事项（不计入已确认成果）')]:
            lines+=['',f'## {label}',''];selected=[i for i in snapshot['items'] if i['review_status']==review]
            if not selected:lines.append('暂无。')
            for item in selected:
                lines+=[f"### 事项 {item['id']} · {m(item['title'])}",f"类型：{TYPES[item['type']]}；处理状态：{STATUSES[item['work_status']]}；版本：{item['version']}。",f"责任人：{m(item['owner'] or '待确认')}；期限：{m(item['due_text'] or '未明确')}；确认截止时间：{m(item['due_at'] or '未明确')}。",f"进展：{m(item['latest_progress'] or '暂无')}。",'依据：']
                grouped={}
                for e in item['evidence']:
                    if e['message_id'] not in grouped:grouped[e['message_id']]={**e,'fields':[]}
                    grouped[e['message_id']]['fields'].append(e['field'])
                for e in grouped.values():
                    fields='、'.join({'title':'事项','owner':'责任人','deadline':'期限','progress':'进展'}.get(f,f) for f in e['fields'])
                    lines.append(f"- 消息 {e['message_id']} · 来源{e['source_id']} · {m(e['sender'])} · {e['timestamp']} · {m(fields)}{' · 跨期依据' if e['outside_period'] else ''}：{m(e['text'])}"+(f"；引用：{m(e['quote_sender'])} / {m(e['quote_text'])}" if e['quote_text'] else ''))
        lines+=['','## 尚未采纳的 AI 建议','']
        lines.extend(f"- 建议 {p['id']} · {m(p['title'])}（任务 {p['job_id']}，须人工复核）" for p in snapshot['pending_proposals'])
        if not snapshot['pending_proposals']:lines.append('暂无。')
        return '\n'.join(lines)+'\n'

    def export(self,report_id,format):
        report=self.get(report_id)
        if format=='markdown':return report['content'],'text/markdown; charset=utf-8','md'
        c=report['coverage'];s=report['snapshot'];rows=[]
        for item in s['items']:
            rows.append([s['project_label'],s['start_date'],s['end_date'],s['generated_at'],c['message_count'],c['analyzed_count'],c['unanalysed_count'],item['id'],item['version'],item['review_status'],item['work_status'],item['type'],item['title'],item['owner'],item['due_text'],item['due_at'],item['latest_progress'],','.join(str(e['message_id']) for e in item['evidence']),encode(item['evidence'])])
        if not rows:rows.append([s['project_label'],s['start_date'],s['end_date'],s['generated_at'],c['message_count'],c['analyzed_count'],c['unanalysed_count']]+[None]*12)
        # Coverage and unaccepted suggestions survive CSV even when there are no confirmed items.
        headers=['项目代号','区间开始','区间结束','生成时间','区间消息数','成功分析消息数','未成功分析消息数','事项ID','版本','复核状态','处理状态','类型','标题','责任人代号','原文期限','确认截止时间','最新进展','依据消息ID','脱敏依据']
        for row in rows:row.extend([encode(c),encode(s['pending_proposals'])])
        return csv_text(headers+['覆盖详情','待采纳建议'],rows),'text/csv; charset=utf-8','csv'
